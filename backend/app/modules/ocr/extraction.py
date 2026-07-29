"""Field extraction — turning OCR text into a structured document.

**This module is pure.** No OCR engine, no database, no network. It takes a string
of recognised text and returns candidate field values with confidence scores. That
matters because it is where all the product logic lives, and being pure makes it
exhaustively testable without a 2 GB model download.

**Confidence is per field, not per document.** A scan can yield a perfectly
readable GSTIN and an illegible total. Reporting one number for the whole document
would force a human to re-check everything or trust everything; reporting per field
lets the review UI highlight exactly the two values that need eyes on them.

**Nothing here is ever posted automatically.** Extraction produces a *suggestion*
that a human confirms. An OCR engine that misreads 8 as 3 would otherwise book a
₹3,000 bill as ₹8,000, and the resulting journal entry is immutable.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Final

# ---------------------------------------------------------------------------
# Confidence
# ---------------------------------------------------------------------------
#: Above this, the review UI pre-fills the field without flagging it.
HIGH_CONFIDENCE: Final = Decimal("0.85")
#: Below this, the field is presented blank rather than pre-filled — a wrong
#: default is worse than none, because a reviewer skims past a plausible value.
LOW_CONFIDENCE: Final = Decimal("0.50")


class FieldSource(StrEnum):
    """How a value was arrived at. Surfaced so a reviewer can weigh it."""

    #: Matched a strict format (GSTIN, IFSC) that is unlikely to match by accident.
    PATTERN = "pattern"
    #: Found next to an expected label ("Invoice No:", "Total").
    LABELLED = "labelled"
    #: Inferred from position or arithmetic rather than a direct match.
    INFERRED = "inferred"
    #: A human corrected it.
    MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class ExtractedField[T]:
    """One candidate value with its provenance."""

    value: T
    confidence: Decimal
    source: FieldSource
    #: The text this was read from, for the review UI to show in context.
    raw: str | None = None

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= HIGH_CONFIDENCE

    @property
    def needs_review(self) -> bool:
        return self.confidence < HIGH_CONFIDENCE


@dataclass(slots=True)
class ExtractedDocument:
    """Everything found in one scanned document."""

    supplier_name: ExtractedField[str] | None = None
    supplier_gstin: ExtractedField[str] | None = None
    invoice_number: ExtractedField[str] | None = None
    invoice_date: ExtractedField[dt.date] | None = None
    due_date: ExtractedField[dt.date] | None = None
    subtotal: ExtractedField[Decimal] | None = None
    tax_amount: ExtractedField[Decimal] | None = None
    total_amount: ExtractedField[Decimal] | None = None
    line_items: list[ExtractedLine] = field(default_factory=list)

    @property
    def overall_confidence(self) -> Decimal:
        """Mean confidence across the fields that were found.

        A summary for sorting a review queue — never a substitute for the per-field
        scores, which are what the reviewer actually acts on.
        """
        found = [
            f.confidence
            for f in (
                self.supplier_name,
                self.supplier_gstin,
                self.invoice_number,
                self.invoice_date,
                self.total_amount,
            )
            if f is not None
        ]
        if not found:
            return Decimal("0")
        return sum(found, Decimal("0")) / Decimal(len(found))

    @property
    def fields_needing_review(self) -> list[str]:
        named = {
            "supplier_name": self.supplier_name,
            "supplier_gstin": self.supplier_gstin,
            "invoice_number": self.invoice_number,
            "invoice_date": self.invoice_date,
            "total_amount": self.total_amount,
        }
        return [name for name, value in named.items() if value is None or value.needs_review]

    @property
    def totals_reconcile(self) -> bool:
        """Whether subtotal + tax equals the stated total.

        The single most useful signal in the whole pipeline: if the three numbers
        agree, all three were almost certainly read correctly, because a
        misrecognised digit would break the arithmetic. Used to *raise* confidence
        rather than to reject anything.
        """
        if self.subtotal is None or self.tax_amount is None or self.total_amount is None:
            return False
        expected = self.subtotal.value + self.tax_amount.value
        # A rupee of tolerance absorbs the supplier's own rounding.
        return abs(expected - self.total_amount.value) <= Decimal("1")


@dataclass(frozen=True, slots=True)
class ExtractedLine:
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    amount: Decimal | None
    confidence: Decimal


# ---------------------------------------------------------------------------
# Patterns
# ---------------------------------------------------------------------------
#: GSTIN: 2-digit state code, 10-char PAN, entity digit, 'Z', checksum.
#: Strict enough that a match is almost certainly a real GSTIN, which is why a hit
#: scores high without any label nearby.
GSTIN_PATTERN: Final = re.compile(r"\b(\d{2}[A-Z]{5}\d{4}[A-Z][0-9A-Z]Z[0-9A-Z])\b", re.IGNORECASE)

#: The same 15 characters, tolerating spaces OCR inserted between them.
#:
#: **Not a hypothetical.** Tesseract reads a printed ``27AABCU9603R1ZM`` as
#: ``27 AABCU9603R1ZM`` — engines break long alphanumeric runs where the letter
#: spacing widens, and an invoice's GSTIN is set in exactly that kind of type. The
#: strict pattern above misses every one of those, and the GSTIN is the field
#: supplier matching depends on, so losing it costs the reviewer the one thing the
#: scan was supposed to save them.
#:
#: A candidate found here is validated against :data:`GSTIN_PATTERN` once the spaces
#: are removed, so the shape is still enforced exactly; only contiguity is relaxed.
GSTIN_SPACED_PATTERN: Final = re.compile(r"\b(?:[0-9A-Z][ ]?){14}[0-9A-Z]\b", re.IGNORECASE)

#: Indian PAN, embedded in every GSTIN but also printed alone.
PAN_PATTERN: Final = re.compile(r"\b([A-Z]{5}\d{4}[A-Z])\b", re.IGNORECASE)

#: Invoice number, next to one of the labels suppliers actually use.
#:
#: `number` must precede `no\.?` in the alternation. Regex alternation is ordered,
#: so with `no` first, "Invoice Number: MW/01" matches the label as "No", leaving
#: "mber" to be captured as the invoice number.
INVOICE_NUMBER_PATTERN: Final = re.compile(
    r"(?:tax\s+invoice|invoice|inv|bill)\s*(?:number|no\.?|#|:)\s*[:\-#]?\s*"
    r"([A-Z0-9][A-Z0-9/\-]{1,29})",
    re.IGNORECASE,
)

#: Dates in the formats Indian invoices use. ISO last so a dd/mm value is not
#: misread as yyyy-mm.
DATE_PATTERNS: Final = (
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})\b"), "dmy"),
    (re.compile(r"\b(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2})\b"), "dmy2"),
    (re.compile(r"\b(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})\b"), "ymd"),
    (
        re.compile(
            r"\b(\d{1,2})\s*[-\s]\s*"
            r"(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\s*[-\s]\s*(\d{2,4})\b",
            re.IGNORECASE,
        ),
        "dMy",
    ),
)

MONTH_NAMES: Final = {
    "jan": 1,
    "feb": 2,
    "mar": 3,
    "apr": 4,
    "may": 5,
    "jun": 6,
    "jul": 7,
    "aug": 8,
    "sep": 9,
    "oct": 10,
    "nov": 11,
    "dec": 12,
}

#: An amount, with optional currency symbol and Indian or Western digit grouping.
AMOUNT: Final = r"(?:₹|rs\.?|inr)?\s*([\d,]+(?:\.\d{1,2})?)"

TOTAL_PATTERN: Final = re.compile(
    r"(?:grand\s+total|total\s+amount|amount\s+payable|net\s+payable|total)\s*[:\-]?\s*" + AMOUNT,
    re.IGNORECASE,
)
SUBTOTAL_PATTERN: Final = re.compile(
    r"(?:sub\s*-?\s*total|taxable\s+(?:value|amount)|amount\s+before\s+tax)\s*[:\-]?\s*" + AMOUNT,
    re.IGNORECASE,
)
TAX_PATTERN: Final = re.compile(
    r"(?:total\s+tax|tax\s+amount|gst|cgst|sgst|igst)\s*(?:@\s*[\d.]+\s*%)?\s*[:\-]?\s*" + AMOUNT,
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Extraction
# ---------------------------------------------------------------------------
def parse_amount(raw: str) -> Decimal | None:
    """Parse an amount, tolerating both digit-grouping conventions.

    Indian grouping (``1,20,000``) and Western (``120,000``) both appear, sometimes
    on the same invoice. Since commas are only ever separators here — never a
    decimal point in this locale — stripping them handles both without having to
    guess which convention is in play.
    """
    cleaned = raw.strip().replace(",", "").replace("₹", "").strip()
    cleaned = re.sub(r"^(?:rs\.?|inr)\s*", "", cleaned, flags=re.IGNORECASE)
    if not cleaned:
        return None
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        return None
    # A negative total on a purchase invoice means the parse went wrong.
    return value if value >= 0 else None


def parse_date(text: str, *, today: dt.date | None = None) -> dt.date | None:
    """Parse the first plausible date in ``text``.

    **Day-first, not month-first.** ``03/04/2026`` is 3 April in India and 4 March
    in the US, and this product's locale is India. Getting it wrong silently files a
    document in the wrong month, so the ambiguity is resolved by locale rather than
    guessed per document.
    """
    reference = today or dt.date.today()

    for pattern, order in DATE_PATTERNS:
        match = pattern.search(text)
        if match is None:
            continue

        try:
            if order == "dmy":
                day, month, year = int(match[1]), int(match[2]), int(match[3])
            elif order == "dmy2":
                day, month = int(match[1]), int(match[2])
                # A 2-digit year: assume this century.
                year = 2000 + int(match[3])
            elif order == "ymd":
                year, month, day = int(match[1]), int(match[2]), int(match[3])
            else:  # dMy
                day = int(match[1])
                month = MONTH_NAMES[match[2][:3].lower()]
                raw_year = int(match[3])
                year = raw_year if raw_year > 99 else 2000 + raw_year

            parsed = dt.date(year, month, day)
        except (ValueError, KeyError):
            continue

        # Reject dates that cannot be an invoice date. A far-future date is almost
        # always a misread, and pre-2000 is out of scope for this software.
        if parsed.year < 2000 or parsed > reference + dt.timedelta(days=365):
            continue
        return parsed

    return None


def extract_gstin(text: str) -> ExtractedField[str] | None:
    """Find a GSTIN, tolerating spaces the engine inserted.

    High confidence on a match: 15 characters in that exact shape do not occur by
    accident.

    Two passes. The contiguous form is tried first and scores highest. Failing that,
    a run of 15 alphanumerics separated by single spaces is de-spaced and checked
    against the same strict shape — scored marginally lower, because it rests on the
    additional assumption that those spaces were not in the printed document.
    """
    if match := GSTIN_PATTERN.search(text):
        return ExtractedField(
            value=match[1].upper(),
            confidence=Decimal("0.95"),
            source=FieldSource.PATTERN,
            raw=match[0],
        )

    for candidate in GSTIN_SPACED_PATTERN.finditer(text):
        collapsed = candidate[0].replace(" ", "").upper()
        if GSTIN_PATTERN.fullmatch(collapsed):
            return ExtractedField(
                value=collapsed,
                confidence=Decimal("0.90"),
                source=FieldSource.PATTERN,
                raw=candidate[0],
            )

    return None


def extract_invoice_number(text: str) -> ExtractedField[str] | None:
    """Find an invoice number next to a recognised label.

    Label-anchored only. Scanning for "something that looks like a reference" picks
    up PAN numbers, phone numbers, and HSN codes far more often than it finds the
    invoice number.
    """
    match = INVOICE_NUMBER_PATTERN.search(text)
    if match is None:
        return None

    candidate = match[1].strip().rstrip(".,;:")
    if len(candidate) < 2:
        return None

    # A candidate that is only digits is weaker — it could be a date fragment or a
    # page number that happened to follow the label.
    confidence = Decimal("0.70") if candidate.isdigit() else Decimal("0.88")
    return ExtractedField(
        value=candidate.upper(),
        confidence=confidence,
        source=FieldSource.LABELLED,
        raw=match[0].strip(),
    )


def extract_amount(
    text: str, pattern: re.Pattern[str], *, base_confidence: str = "0.80"
) -> ExtractedField[Decimal] | None:
    """Find a labelled amount, preferring the last match.

    Last, not first: "Total" appears in a column header before it appears as the
    actual figure, and on multi-page documents the meaningful total is at the end.
    """
    matches = list(pattern.finditer(text))
    if not matches:
        return None

    for match in reversed(matches):
        value = parse_amount(match[1])
        if value is not None and value > 0:
            return ExtractedField(
                value=value,
                confidence=Decimal(base_confidence),
                source=FieldSource.LABELLED,
                raw=match[0].strip(),
            )
    return None


def extract_supplier_name(text: str) -> ExtractedField[str] | None:
    """Guess the supplier from the top of the document.

    A heuristic, and scored accordingly. The supplier's name is normally the most
    prominent line in the letterhead, which after OCR means "near the top and not
    obviously something else". Low confidence on purpose — the review UI should ask.
    """
    skip = re.compile(
        r"^(?:tax\s+invoice|invoice|bill|gstin|gst|pan|phone|tel|email|www|http|date|"
        r"original|duplicate|triplicate)\b",
        re.IGNORECASE,
    )

    for line in text.splitlines()[:8]:
        candidate = line.strip()
        if len(candidate) < 3 or len(candidate) > 80:
            continue
        if skip.match(candidate):
            continue
        # Mostly digits or punctuation is an address or a number, not a name.
        letters = sum(character.isalpha() for character in candidate)
        if letters < len(candidate) * 0.5:
            continue

        return ExtractedField(
            value=candidate,
            confidence=Decimal("0.55"),
            source=FieldSource.INFERRED,
            raw=candidate,
        )
    return None


def extract_document(text: str, *, today: dt.date | None = None) -> ExtractedDocument:
    """Extract every field from recognised text.

    Confidence is raised when ``subtotal + tax == total``, because that arithmetic
    agreeing is strong independent evidence that all three numbers were read
    correctly — a single misrecognised digit would break it.
    """
    document = ExtractedDocument(
        supplier_name=extract_supplier_name(text),
        supplier_gstin=extract_gstin(text),
        invoice_number=extract_invoice_number(text),
        subtotal=extract_amount(text, SUBTOTAL_PATTERN),
        tax_amount=extract_amount(text, TAX_PATTERN, base_confidence="0.75"),
        total_amount=extract_amount(text, TOTAL_PATTERN, base_confidence="0.82"),
    )

    parsed_date = parse_date(text, today=today)
    if parsed_date is not None:
        document.invoice_date = ExtractedField(
            value=parsed_date,
            confidence=Decimal("0.78"),
            source=FieldSource.PATTERN,
            raw=parsed_date.isoformat(),
        )

    if document.totals_reconcile:
        document = _boost_reconciled_amounts(document)

    return document


def _boost_reconciled_amounts(document: ExtractedDocument) -> ExtractedDocument:
    """Raise confidence on the three amounts when they add up.

    Capped at 0.97 rather than 1.0: arithmetic agreement is powerful evidence but
    not proof — a consistently misread column could still reconcile.
    """
    for name in ("subtotal", "tax_amount", "total_amount"):
        current: ExtractedField[Decimal] | None = getattr(document, name)
        if current is None:
            continue
        setattr(
            document,
            name,
            ExtractedField(
                value=current.value,
                confidence=min(Decimal("0.97"), current.confidence + Decimal("0.15")),
                source=current.source,
                raw=current.raw,
            ),
        )
    return document
