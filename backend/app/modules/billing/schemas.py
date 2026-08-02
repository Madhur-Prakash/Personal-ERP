"""Billing API contracts."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated

from pydantic import Field, StringConstraints

from app.core.schemas import BaseSchema, ResponseSchema
from app.modules.billing.models import CardKind, CardNetwork
from app.modules.billing.service import Direction, MoneyAccountKind, MoneyKind

#: A money amount on the way in. Positive only - a correction is a reversal, not a
#: negative entry, because a ledger records what happened rather than the net of it.
#: `decimal_places=2` because a person typing an amount by hand means rupees and
#: paise; the column keeps 4 for computed figures.
Amount = Annotated[Decimal, Field(gt=0, max_digits=18, decimal_places=2)]

Description = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=500)]
#: Who the money was with. Stripped, so a field holding only spaces is rejected rather
#: than stored as whitespace that looks filled in on screen.
Party = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class RecordEntryRequest(BaseSchema):
    """What the form sends.

    Only three fields are required: which way, when, and how much - plus a note,
    because an amount with no description is unidentifiable a month later and the
    ledger's narration cannot be blank.

    `category_id` and `money_account_id` are optional and fall back to sensible
    defaults, so a first entry needs no understanding of the chart of accounts.
    """

    direction: Direction
    amount: Amount
    description: Description
    #: Defaults to today, resolved in the organization's own timezone.
    entry_date: dt.date | None = None
    category_id: uuid.UUID | None = None
    money_account_id: uuid.UUID | None = None
    reference: str | None = Field(default=None, max_length=100)
    #: Who it came from, or who it went to. **Required.**
    #:
    #: Free text, not a foreign key: most parties in a small business are never worth a
    #: master record, and forcing one is the friction this screen exists to remove. But
    #: an amount with no counterparty is nearly as unidentifiable a month later as one
    #: with no description, so it is asked for rather than offered.
    #:
    #: Enforced here and not only in the form, because a rule the browser keeps and the
    #: API does not is not a rule. The form is the only thing that creates these entries,
    #: so there is no import or scanning path that this locks out.
    party: Party


class ReverseEntryRequest(BaseSchema):
    reason: str | None = Field(default=None, max_length=500)


class CategoryRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name: str
    #: Which way this category applies. Income categories cannot take money out.
    direction: Direction
    #: The parent group's name, so the dropdown can use `optgroup`. A flat list of
    #: nearly eighty categories is one nobody reads to the end of.
    group: str
    is_default: bool


class CreateCategoryRequest(BaseSchema):
    """Add a category of your own.

    Only a name and a direction. The code, parent group, and subtype are derived -
    asking someone to pick an account code and a subtype in order to record a payment
    would defeat the purpose of this screen.
    """

    name: Annotated[str, Field(min_length=1, max_length=150)]
    direction: Direction


class CreateMoneyAccountRequest(BaseSchema):
    """Add a cash box or bank account.

    A name and which of the two it behaves like. Everything else - the account code,
    the parent group, the subtype - is derived, for the same reason the category form
    derives them: nobody should need the chart of accounts to add a UPI wallet.
    """

    name: Annotated[str, Field(min_length=1, max_length=150)]
    kind: MoneyKind = MoneyKind.BANK


class MoneyAccountRead(ResponseSchema):
    id: uuid.UUID
    code: str
    name: str
    is_default: bool
    #: What this place actually is. `credit_card` is a **liability**, not cash, and the
    #: client uses this to say so rather than showing a card beside a bank balance as
    #: though the two meant the same thing.
    kind: MoneyAccountKind = MoneyAccountKind.CASH
    #: Set when a card is what identifies this option. A debit card shares its `id` with
    #: the bank account it draws on, so the card id is what tells the two entries apart.
    card_id: uuid.UUID | None = None
    card_last4: str | None = None
    card_network: str | None = None


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------
class AddCardRequest(BaseSchema):
    """Put a card on file.

    **The number is used and discarded; only the last four digits and the network are
    stored.** Constrained here to shape only - digits, spaces and dashes, within the
    lengths ISO/IEC 7812 allows - with the check digit and the scheme worked out in the
    service. The pattern rejects letters without quoting the value back, which matters:
    the 422 handler forwards messages and never inputs, and a message that echoed the
    digits would undo that.
    """

    label: Annotated[str, Field(min_length=1, max_length=80)]
    kind: CardKind

    #: As typed or pasted. Spaces and dashes are fine.
    card_number: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True,
            min_length=12,
            # 19 digits plus the separators a person types between groups of four.
            max_length=25,
            pattern=r"^[\d\s-]+$",
        ),
    ]

    #: Required for a debit card, ignored for a credit card. A debit card is a way of
    #: using a bank account you already have, so it names that account rather than
    #: creating one - which would double-count the same money.
    bank_account_id: uuid.UUID | None = None


class CardRead(ResponseSchema):
    """A card on file. **There is no field for a number, by design.**"""

    id: uuid.UUID
    label: str
    kind: CardKind
    network: CardNetwork
    #: Four digits, as a string - a card ending 0042 is not the number 42.
    last4: str
    #: The ledger account this card's postings land on. Its own liability account for a
    #: credit card; the bank account it draws on for a debit card.
    account_id: uuid.UUID
    account_name: str
    is_active: bool


# ---------------------------------------------------------------------------
# Transfers
# ---------------------------------------------------------------------------
class TransferRequest(BaseSchema):
    """Move money between two of your own accounts.

    No category, and that is not an omission: moving your own money is neither earning
    nor spending it, so there is no income or expense line to file it against.
    """

    from_account_id: uuid.UUID
    to_account_id: uuid.UUID
    amount: Amount
    #: Defaults to today, resolved in the organization's own timezone.
    entry_date: dt.date | None = None
    #: Optional. Left blank, the ledger narration names both accounts.
    description: Annotated[str | None, Field(default=None, max_length=500)] = None
    reference: str | None = Field(default=None, max_length=100)


class TransferRead(ResponseSchema):
    entry_id: uuid.UUID
    entry_number: str | None
    date: dt.date
    amount: Decimal
    description: str
    from_account_id: uuid.UUID
    from_account_name: str
    to_account_id: uuid.UUID
    to_account_name: str


class BillingOptions(ResponseSchema):
    """Everything the form needs to render, in one request.

    Served rather than hard-coded so the categories follow the organization's actual
    chart of accounts - including any account it has added itself.
    """

    categories: list[CategoryRead]
    money_accounts: list[MoneyAccountRead]
    #: Cards on file, for the accounts panel. Separate from `money_accounts` because the
    #: two answer different questions: that list is "where can this payment go", this one
    #: is "what have I registered" - and an archived card belongs in neither.
    cards: list[CardRead]
    #: Today in the organization's timezone, so the date field opens on the right day
    #: rather than on the server's UTC date.
    today: dt.date
    currency: str


class EntryRead(ResponseSchema):
    id: uuid.UUID
    #: The ledger's own number for this entry, so it can be found in the journal.
    entry_number: str | None
    date: dt.date
    direction: Direction
    amount: Decimal
    description: str
    reference: str | None
    party: str | None

    category_id: uuid.UUID
    category_name: str
    money_account_id: uuid.UUID
    money_account_name: str

    created_at: dt.datetime
    #: Cancelled by a reversal. Still listed - the cancellation is part of the record.
    is_reversed: bool


class BillingSummary(ResponseSchema):
    from_date: dt.date
    to_date: dt.date
    money_in: Decimal
    money_out: Decimal
    net: Decimal
    entry_count: int
