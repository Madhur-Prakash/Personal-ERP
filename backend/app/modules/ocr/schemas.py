"""Document intelligence API contracts."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field

from app.core.schemas import BaseSchema, ResponseSchema, TimestampedSchema
from app.modules.ocr.engines import DocumentFormat
from app.modules.ocr.models import DocumentKind, DocumentStatus
from app.modules.purchasing.schemas import BillCreate, BillRead

Confidence = Annotated[Decimal, Field(ge=0, le=1, max_digits=9, decimal_places=4)]


# ---------------------------------------------------------------------------
# Capabilities
# ---------------------------------------------------------------------------
class OcrCapabilities(ResponseSchema):
    """What this deployment can actually read.

    Exposed so the UI can say "install Tesseract to enable scanning" instead of
    offering an upload button that fails, and so an operator can tell a missing
    dependency from a broken one without reading logs.
    """

    enabled: bool
    engines: list[str]
    formats: list[DocumentFormat]
    max_bytes: int
    #: False when the extra is installed but no engine is usable — almost always a
    #: missing Tesseract binary.
    any_engine_available: bool


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------
class DocumentSummary(TimestampedSchema):
    """Review-queue row. Deliberately excludes the recognised text, which is
    kilobytes per document and would dominate a page of 25."""

    id: uuid.UUID
    original_filename: str
    content_type: DocumentFormat
    byte_size: int
    kind: DocumentKind
    status: DocumentStatus

    extracted_supplier_name: str | None
    extracted_supplier_gstin: str | None
    extracted_invoice_number: str | None
    extracted_invoice_date: dt.date | None
    extracted_total_amount: Decimal | None

    overall_confidence: Decimal | None
    totals_reconcile: bool
    needs_review: bool
    is_duplicate: bool

    matched_supplier_id: uuid.UUID | None
    matched_supplier_name: str | None = None
    bill_id: uuid.UUID | None
    duplicate_of_id: uuid.UUID | None


class DocumentRead(DocumentSummary):
    """Full document detail for the review screen."""

    sha256: str
    engine: str | None
    engine_confidence: Decimal | None
    page_count: int | None

    extracted_subtotal: Decimal | None
    extracted_tax_amount: Decimal | None

    #: Per-field confidence as decimal strings, e.g. ``{"total_amount": "0.9700"}``.
    #: Strings, not numbers: JSON has one numeric type and it is a float, so a
    #: confidence would round-trip through binary floating point for no reason.
    field_confidence: dict[str, str]
    low_confidence_fields: list[str]

    failure_code: str | None
    failure_message: str | None

    bill_number: str | None = None
    reviewed_at: dt.datetime | None
    notes: str | None


class DocumentText(ResponseSchema):
    """The recognised text, on its own endpoint.

    Separate because it is large and rarely needed — but it is the only honest
    answer to "where did this number come from?", so it stays reachable.
    """

    document_id: uuid.UUID
    engine: str | None
    engine_confidence: Decimal | None
    page_count: int | None
    text: str


class DuplicateWarning(ResponseSchema):
    """An earlier document that looks like the same invoice."""

    document_id: uuid.UUID
    status: DocumentStatus
    bill_id: uuid.UUID | None
    bill_number: str | None
    uploaded_at: dt.datetime
    reason: str


class UploadResult(ResponseSchema):
    """The outcome of one upload.

    Carries the duplicate warning alongside the document rather than as an error:
    the upload succeeded, and whether a near-identical invoice already exists is
    information the reviewer needs, not a reason to refuse the file.
    """

    document: DocumentRead
    duplicate: DuplicateWarning | None = None
    #: True when this exact file had already been uploaded, so the existing
    #: document is being returned instead of a second copy being created.
    already_uploaded: bool = False


class ConfirmResult(ResponseSchema):
    """The document and the bill it became.

    Both, because both changed: the caller needs the new bill to navigate to, and the
    document's status to update the review queue without a second request.
    """

    document: DocumentRead
    bill: BillRead


class ConfirmDocumentRequest(BaseSchema):
    """Reviewed values, submitted as the bill they should become.

    **This is a ``BillCreate``, not a set of overrides on the extracted fields.**
    Confirming a document must be exactly as safe as typing the bill in by hand,
    which means going through the same schema and the same service — duplicate
    invoice-number refusal, period locks, GST resolution, and ledger posting all
    included. Any parallel path would eventually diverge from the real one, and the
    divergence would be in the code that writes to the ledger.
    """

    bill: BillCreate


class RejectDocumentRequest(BaseSchema):
    reason: Annotated[str, Field(min_length=3, max_length=500)]


class ReviewNotesRequest(BaseSchema):
    notes: str | None = Field(default=None, max_length=2000)
