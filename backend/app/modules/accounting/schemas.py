"""Accounting API contracts.

Money crosses the wire as a JSON **string**, not a number. A JSON number is an
IEEE-754 double in every JavaScript client, so `1234567.89` silently becomes
`1234567.8899999999` — and a ledger that displays a cent off is a ledger nobody
trusts. Pydantic serialises `Decimal` to a string here, and the frontend formats
it without ever converting to `number`.
"""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal
from typing import Annotated, Self

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import BaseSchema, ResponseSchema, TimestampedSchema
from app.modules.accounting.models import (
    AccountSubtype,
    AccountType,
    BalanceSide,
    EntryStatus,
    JournalType,
    PeriodStatus,
)

# ---------------------------------------------------------------------------
# Field types
# ---------------------------------------------------------------------------
AccountCode = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=20, pattern=r"^[A-Za-z0-9._-]+$"
    ),
]
AccountName = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Narration = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]

#: A non-negative money amount. `max_digits`/`decimal_places` mirror the
#: `NUMERIC(18, 4)` column, so an over-precise input is rejected at the edge
#: rather than silently rounded by the database.
Amount = Annotated[Decimal, Field(ge=0, max_digits=18, decimal_places=4)]


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------
class AccountCreate(BaseSchema):
    code: AccountCode
    name: AccountName
    account_type: AccountType
    subtype: AccountSubtype
    parent_id: uuid.UUID | None = None
    description: str | None = Field(default=None, max_length=2000)
    is_group: bool = False
    is_reconcilable: bool = False


class AccountUpdate(BaseSchema):
    """All fields optional — a PATCH.

    `account_type` is deliberately absent. Changing an account's type after it
    holds postings would silently flip the sign of its balance in every historical
    report; the correct action is a new account and a transfer entry.
    """

    name: AccountName | None = None
    description: str | None = Field(default=None, max_length=2000)
    parent_id: uuid.UUID | None = None
    is_active: bool | None = None
    is_reconcilable: bool | None = None


class AccountRead(TimestampedSchema):
    id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    subtype: AccountSubtype
    parent_id: uuid.UUID | None
    depth: int
    is_group: bool
    is_active: bool
    is_system: bool
    is_reconcilable: bool
    system_key: str | None
    description: str | None

    normal_balance: BalanceSide
    is_postable: bool


class AccountWithBalance(AccountRead):
    """An account plus its computed balance, for the chart view."""

    total_debit: Decimal
    total_credit: Decimal
    #: Signed so positive always means "more of what this account is for".
    balance: Decimal


class AccountTreeNode(AccountWithBalance):
    """Recursive chart-of-accounts node.

    Nested rather than flat-with-parent-ids because the client renders a tree and
    would otherwise have to rebuild the hierarchy itself — and a subtree's rolled-up
    balance can only be computed once the tree exists.
    """

    children: list[AccountTreeNode] = Field(default_factory=list)
    #: This account's own balance plus every descendant's.
    subtree_balance: Decimal


# ---------------------------------------------------------------------------
# Fiscal calendar
# ---------------------------------------------------------------------------
class FiscalYearCreate(BaseSchema):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]
    start_date: dt.date
    end_date: dt.date
    #: Generate the monthly periods that tile this year.
    generate_periods: bool = True

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        if (self.end_date - self.start_date).days > 732:
            raise ValueError("a fiscal year cannot span more than two years")
        return self


class AccountingPeriodRead(ResponseSchema):
    id: uuid.UUID
    fiscal_year_id: uuid.UUID
    name: str
    start_date: dt.date
    end_date: dt.date
    status: PeriodStatus
    closed_at: dt.datetime | None
    accepts_postings: bool


class FiscalYearRead(TimestampedSchema):
    id: uuid.UUID
    name: str
    start_date: dt.date
    end_date: dt.date
    status: PeriodStatus
    closed_at: dt.datetime | None
    periods: list[AccountingPeriodRead] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Journals
# ---------------------------------------------------------------------------
class JournalCreate(BaseSchema):
    code: AccountCode
    name: AccountName
    journal_type: JournalType = JournalType.GENERAL
    number_prefix: Annotated[str, StringConstraints(strip_whitespace=True, max_length=10)] = "JV"
    default_account_id: uuid.UUID | None = None


class JournalRead(TimestampedSchema):
    id: uuid.UUID
    code: str
    name: str
    journal_type: JournalType
    number_prefix: str
    default_account_id: uuid.UUID | None
    is_active: bool
    is_system: bool


# ---------------------------------------------------------------------------
# Journal entries
# ---------------------------------------------------------------------------
class JournalEntryLineInput(BaseSchema):
    account_id: uuid.UUID
    debit: Amount = Decimal("0")
    credit: Amount = Decimal("0")
    description: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _exactly_one_side(self) -> Self:
        """Mirror the database's `single_sided` CHECK at the edge.

        Rejecting here gives the user a field-level message instead of a 409 from
        a constraint violation deep in the transaction.
        """
        has_debit = self.debit > 0
        has_credit = self.credit > 0
        if has_debit and has_credit:
            raise ValueError("a line cannot have both a debit and a credit")
        if not has_debit and not has_credit:
            raise ValueError("a line must have either a debit or a credit")
        return self


class JournalEntryCreate(BaseSchema):
    journal_id: uuid.UUID
    entry_date: dt.date
    narration: Narration
    reference: str | None = Field(default=None, max_length=100)
    lines: list[JournalEntryLineInput] = Field(min_length=2)
    #: Post immediately instead of saving as a draft.
    post: bool = False

    @model_validator(mode="after")
    def _must_balance(self) -> Self:
        """The double-entry rule, checked before the request reaches the service."""
        debit = sum((line.debit for line in self.lines), Decimal("0"))
        credit = sum((line.credit for line in self.lines), Decimal("0"))

        if debit != credit:
            raise ValueError(
                f"entry does not balance: debits {debit} != credits {credit} "
                f"(difference {abs(debit - credit)})"
            )
        if debit == 0:
            raise ValueError("entry total cannot be zero")

        accounts = [line.account_id for line in self.lines]
        if len(set(accounts)) == 1:
            # Both sides on one account is always a mistake, and nets to nothing.
            raise ValueError("an entry must touch at least two different accounts")
        return self


class JournalEntryUpdate(BaseSchema):
    """Drafts only. A posted entry is corrected by reversal, never by edit."""

    entry_date: dt.date | None = None
    narration: Narration | None = None
    reference: str | None = Field(default=None, max_length=100)
    lines: list[JournalEntryLineInput] | None = Field(default=None, min_length=2)

    @model_validator(mode="after")
    def _must_balance(self) -> Self:
        if self.lines is None:
            return self
        debit = sum((line.debit for line in self.lines), Decimal("0"))
        credit = sum((line.credit for line in self.lines), Decimal("0"))
        if debit != credit:
            raise ValueError(f"entry does not balance: debits {debit} != credits {credit}")
        if debit == 0:
            raise ValueError("entry total cannot be zero")
        return self


class JournalEntryLineRead(ResponseSchema):
    id: uuid.UUID
    line_number: int
    account_id: uuid.UUID
    account_code: str
    account_name: str
    debit: Decimal
    credit: Decimal
    description: str | None


class JournalEntryRead(TimestampedSchema):
    id: uuid.UUID
    journal_id: uuid.UUID
    journal_code: str
    period_id: uuid.UUID
    entry_number: str | None
    entry_date: dt.date
    narration: str
    reference: str | None
    status: EntryStatus
    total_debit: Decimal
    total_credit: Decimal
    currency: str
    posted_at: dt.datetime | None
    reversed_at: dt.datetime | None
    reverses_id: uuid.UUID | None
    source_type: str | None
    source_id: uuid.UUID | None
    lines: list[JournalEntryLineRead] = Field(default_factory=list)


class ReverseEntryRequest(BaseSchema):
    """A reversal may be dated later than the original — you cannot post into a
    closed month just because that is where the mistake was made."""

    reversal_date: dt.date | None = None
    narration: Narration | None = None


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------
class TrialBalanceRow(ResponseSchema):
    account_id: uuid.UUID
    code: str
    name: str
    account_type: AccountType
    debit: Decimal
    credit: Decimal


class TrialBalance(ResponseSchema):
    as_of: dt.date
    from_date: dt.date | None
    rows: list[TrialBalanceRow]
    total_debit: Decimal
    total_credit: Decimal
    #: Must always be true. Surfaced rather than asserted so a corrupted ledger is
    #: visible in the UI instead of raising a 500 on an otherwise-useful report.
    is_balanced: bool


class LedgerLine(ResponseSchema):
    entry_id: uuid.UUID
    entry_number: str | None
    entry_date: dt.date
    narration: str
    reference: str | None
    journal_code: str
    debit: Decimal
    credit: Decimal
    #: Balance after this line, in the account's normal direction.
    running_balance: Decimal


class AccountLedger(ResponseSchema):
    account: AccountRead
    from_date: dt.date
    to_date: dt.date
    opening_balance: Decimal
    closing_balance: Decimal
    total_debit: Decimal
    total_credit: Decimal
    lines: list[LedgerLine]


class ReportLine(ResponseSchema):
    """One row of a financial statement.

    Deliberately generic: P&L, balance sheet, and cash flow all render as a tree
    of labelled amounts, so they share one shape and one frontend component.
    """

    label: str
    amount: Decimal
    #: Indentation level for rendering.
    level: int = 0
    is_total: bool = False
    account_id: uuid.UUID | None = None
    account_code: str | None = None
    children: list[ReportLine] = Field(default_factory=list)


class ProfitAndLoss(ResponseSchema):
    from_date: dt.date
    to_date: dt.date
    income: list[ReportLine]
    expenses: list[ReportLine]
    total_income: Decimal
    total_expenses: Decimal
    gross_profit: Decimal
    cost_of_goods_sold: Decimal
    net_profit: Decimal


class BalanceSheet(ResponseSchema):
    as_of: dt.date
    assets: list[ReportLine]
    liabilities: list[ReportLine]
    equity: list[ReportLine]
    total_assets: Decimal
    total_liabilities: Decimal
    total_equity: Decimal
    #: Profit for the year to date. Until the year is closed this is not yet in
    #: retained earnings, so it is shown as its own equity line — without it the
    #: sheet would not balance.
    current_period_earnings: Decimal
    is_balanced: bool


class CashFlowStatement(ResponseSchema):
    from_date: dt.date
    to_date: dt.date
    opening_cash: Decimal
    closing_cash: Decimal
    net_change: Decimal
    inflows: list[ReportLine]
    outflows: list[ReportLine]
    total_inflows: Decimal
    total_outflows: Decimal
    #: `opening + inflows - outflows == closing`. Surfaced for the same reason as
    #: `TrialBalance.is_balanced`.
    reconciles: bool
