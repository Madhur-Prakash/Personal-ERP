"""Scanned documents - the inbox between a supplier's PDF and the ledger.

**A document is a suggestion, never a posting.** Extraction produces candidate
values that a human confirms; confirming hands them to the existing
:class:`~app.modules.purchasing.receiving.BillService`, which applies every rule it
already applies to a hand-entered bill. Nothing here writes to the ledger. An engine
that reads ``8`` as ``3`` would otherwise book a ₹3,000 bill as ₹8,000, and the
resulting journal entry is immutable - correctable only by a reversal that is now
part of the permanent record.

**Extracted values are typed columns, not one JSONB blob.** They have to be
queryable: duplicate detection looks up ``(supplier_gstin, invoice_number)``, and
the review queue sorts by amount and date. Per-field *confidence* is JSONB, because
nothing queries it - it is read once, by the screen that decides which fields to
highlight.

**Duplicate detection warns; it does not block.** Two axes, and they behave
differently on purpose:

* *Byte-identical file* - a hard uniqueness constraint. The same bytes are the same
  document, full stop, and re-uploading them is an accident worth intercepting.
* *Same supplier and invoice number* - a warning with a link, never a rejection.
  Paying one supplier invoice twice is the most expensive clerical error in
  purchasing, so it must be surfaced loudly; but the values it compares were read by
  an OCR engine, and refusing a genuine invoice because a digit was misread would
  make the feature worse than manual entry.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, OrgScopedMixin, SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.types import LedgerDate, Money, Rate, enum_column
from app.modules.ocr.engines import DocumentFormat
from app.modules.ocr.extraction import HIGH_CONFIDENCE

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.purchasing.models import Bill, Supplier
    from app.modules.users.models import User


class DocumentKind(StrEnum):
    """What the uploader says the document is.

    Declared by the user rather than inferred. Classifying a document type from its
    text is a coin flip on a bad scan, and guessing wrong sends an invoice down the
    wrong workflow - whereas the person uploading it already knows.
    """

    #: A supplier's bill. The only kind that can currently be turned into a Bill.
    PURCHASE_INVOICE = "purchase_invoice"
    #: Proof of payment - a card slip, a UPI screenshot.
    RECEIPT = "receipt"
    #: A supplier's quotation, kept for reference.
    QUOTATION = "quotation"
    OTHER = "other"

    @property
    def is_actionable(self) -> bool:
        """Whether confirming it can create an accounting document."""
        return self is DocumentKind.PURCHASE_INVOICE


class DocumentStatus(StrEnum):
    """Where a document is in the review pipeline."""

    #: Stored, not yet read. Recognition is synchronous today, so this is
    #: short-lived - but it is the state a background worker would consume, so it
    #: exists now and no schema change is needed to add one.
    UPLOADED = "uploaded"
    #: Read successfully; candidate fields are on the row awaiting a human.
    EXTRACTED = "extracted"
    #: A human accepted the values and an accounting document was created.
    CONFIRMED = "confirmed"
    #: A human decided it is not usable - a duplicate, or the wrong file.
    REJECTED = "rejected"
    #: The engine or the parse failed. ``failure_code`` says why.
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in (DocumentStatus.CONFIRMED, DocumentStatus.REJECTED)

    @property
    def is_reviewable(self) -> bool:
        return self is DocumentStatus.EXTRACTED


class Document(Base, UUIDPrimaryKeyMixin, OrgScopedMixin, TimestampMixin, SoftDeleteMixin):
    """An uploaded file, what was read out of it, and what became of it."""

    # --- The file -----------------------------------------------------------
    #: As supplied by the client. Display only - never used to build a path.
    #: A filename is attacker-controlled text; joining it onto a directory is
    #: how ``../../etc/passwd`` becomes a write target.
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)

    content_type: Mapped[DocumentFormat] = mapped_column(
        enum_column(DocumentFormat, length=40), nullable=False
    )
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False)

    #: Lowercase hex SHA-256 of the file. Both the storage address and the
    #: duplicate key - content addressing means identical uploads cannot occupy
    #: two blobs, and it is a checksum for free.
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    #: Path relative to ``settings.upload_dir``. Relative so the install can be
    #: moved or restored to a different directory without rewriting every row.
    storage_path: Mapped[str] = mapped_column(String(255), nullable=False)

    # --- Classification and state ------------------------------------------
    kind: Mapped[DocumentKind] = mapped_column(
        enum_column(DocumentKind, length=20),
        nullable=False,
        default=DocumentKind.PURCHASE_INVOICE,
        server_default=text("'purchase_invoice'"),
    )
    status: Mapped[DocumentStatus] = mapped_column(
        enum_column(DocumentStatus, length=20),
        nullable=False,
        default=DocumentStatus.UPLOADED,
        server_default=text("'uploaded'"),
        index=True,
    )

    # --- Recognition --------------------------------------------------------
    engine: Mapped[str | None] = mapped_column(String(40), nullable=True)

    #: Mean per-word confidence reported by the engine, 0-1. Distinct from
    #: ``overall_confidence``: this is "could the pixels be read", that is "do the
    #: values make sense". A crisp scan of an unfamiliar layout scores high here and
    #: low there, and the two failures need different fixes.
    engine_confidence: Mapped[Rate | None] = mapped_column(default=None)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)

    #: The full recognised text.
    #:
    #: Kept because it is the only way to answer "where did this number come from?"
    #: months later, and because re-running extraction after a parser improvement
    #: must not require the original file to still be on disk. It also makes the
    #: documents full-text searchable without touching the blobs.
    recognised_text: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Extracted candidates ----------------------------------------------
    extracted_supplier_name: Mapped[str | None] = mapped_column(String(250), nullable=True)
    extracted_supplier_gstin: Mapped[str | None] = mapped_column(String(15), nullable=True)
    extracted_invoice_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    extracted_invoice_date: Mapped[LedgerDate | None] = mapped_column(default=None)
    extracted_subtotal: Mapped[Money | None] = mapped_column(default=None)
    extracted_tax_amount: Mapped[Money | None] = mapped_column(default=None)
    extracted_total_amount: Mapped[Money | None] = mapped_column(default=None)

    #: ``{"total_amount": "0.97", ...}`` - per-field confidence, as strings so the
    #: Decimals survive the JSON round trip without becoming floats.
    field_confidence: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    #: Mean confidence across the fields that were found. Indexed: the review queue
    #: is "show me the least trustworthy documents first".
    overall_confidence: Mapped[Rate | None] = mapped_column(default=None, index=True)

    #: Whether ``subtotal + tax == total`` in the extracted figures. Stored rather
    #: than recomputed because it is the strongest single trust signal available and
    #: the review list filters on it.
    totals_reconcile: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )

    # --- Outcome ------------------------------------------------------------
    failure_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    failure_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    #: Resolved from the extracted GSTIN. A GSTIN is a strict, unique, and
    #: government-issued identifier, which makes it a far safer match key than a
    #: fuzzy comparison of company names.
    matched_supplier_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("supplier.id", ondelete="SET NULL"), nullable=True, index=True
    )

    #: The bill this document became. ``RESTRICT``, not ``SET NULL``: a posted bill
    #: must keep its source document reachable, and severing the link silently would
    #: leave an entry in the books whose evidence cannot be found.
    bill_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("bill.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    #: An earlier document that appears to be the same invoice. Advisory - see the
    #: module docstring on why this is not a constraint.
    duplicate_of_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("document.id", ondelete="SET NULL"), nullable=True
    )

    # `app_user`, not `user`: USER is a reserved word in PostgreSQL.
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- Relationships ------------------------------------------------------
    organization: Mapped[Organization] = relationship(lazy="raise")
    matched_supplier: Mapped[Supplier | None] = relationship(lazy="raise")
    bill: Mapped[Bill | None] = relationship(lazy="raise")
    uploaded_by: Mapped[User | None] = relationship(
        lazy="raise", foreign_keys=[uploaded_by_user_id]
    )

    __table_args__ = (
        # The same bytes are the same document. Partial on `deleted_at` so a
        # document that was deleted does not permanently poison its own hash.
        Index(
            "uq_document_org_sha256",
            "organization_id",
            "sha256",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # Duplicate lookup: "has this supplier's invoice N been seen before?"
        Index(
            "ix_document_invoice_identity",
            "organization_id",
            "extracted_supplier_gstin",
            "extracted_invoice_number",
            postgresql_where=text("extracted_invoice_number IS NOT NULL"),
        ),
        # The review queue: pending documents for one organization, newest first.
        Index(
            "ix_document_review_queue",
            "organization_id",
            "status",
            "created_at",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )

    @property
    def needs_review(self) -> bool:
        """Whether a human should look at the values before they are used."""
        if self.overall_confidence is None:
            return True
        return self.overall_confidence < HIGH_CONFIDENCE

    @property
    def is_duplicate(self) -> bool:
        return self.duplicate_of_id is not None

    @property
    def low_confidence_fields(self) -> list[str]:
        """Field names the review UI should highlight.

        Read from the stored map rather than recomputed, so what a reviewer sees is
        what the extractor actually concluded at the time - a later parser
        improvement must not silently rewrite the history of a document someone
        already signed off.
        """
        flagged: list[str] = []
        for name, raw in self.field_confidence.items():
            try:
                if Decimal(str(raw)) < HIGH_CONFIDENCE:
                    flagged.append(name)
            except ArithmeticError:  # pragma: no cover - malformed stored value
                flagged.append(name)
        return sorted(flagged)
