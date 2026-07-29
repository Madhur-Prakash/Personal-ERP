"""Billing — record money in and money out, without naming anyone.

The simple path through this product. A shopkeeper types a date, an amount, and what
it was for; the ledger gets a correct double-entry posting and every report picks it
up. No customer, no supplier, no invoice.

**A bill with nobody's name on it is an expense, not a payable.** That is not a
shortcut — it is the correct treatment. A payable exists because you owe a specific
party a specific amount; if the money has already left your hand, there is nothing
owed and nobody to owe it to. So money out is ``debit expense, credit cash`` and money
in is ``debit cash, credit income``. Two lines, and the accounting equation holds
without inventing a party.

**There is no billing table.** Entries are posted straight to the ledger through
:meth:`PostingService.create_entry` and read back from it. That is a deliberate
decision, and the reason is the control-account reconciliation added alongside
analytics: a parallel table holding "the user's simple view" is a cache that can
disagree with the ledger, and this codebase has already been bitten by a figure stored
in two places. Reading back costs one indexed query, and in exchange these entries
appear in the trial balance, the P&L, the dashboard, and the analytics trend
automatically, because they *are* ledger entries.

Reconstruction is exact rather than heuristic: every entry written here has precisely
two lines, one on a cash-equivalent account and one on an income or expense account,
and is tagged ``source_type="billing"``. Direction, amount, category, and method all
follow from that shape with no guessing.
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.context import RequestContext
from app.core.exceptions import BusinessRuleError, NotFoundError, ValidationError
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.db.types import ZERO
from app.modules.accounting.coa_template import SystemAccount
from app.modules.accounting.models import (
    Account,
    AccountType,
    EntryStatus,
    JournalEntry,
    JournalEntryLine,
    JournalType,
)
from app.modules.accounting.repository import POSTED_STATUSES, AccountRepository
from app.modules.accounting.service import (
    ChartOfAccountsService,
    FiscalCalendarService,
    PostingService,
)
from app.modules.organizations.models import Organization
from app.modules.users.models import User

log = get_logger(__name__)

#: Tags the ledger entries this module owns, so they can be read back and so an
#: accountant can tell a hand-entered movement from an invoice posting.
SOURCE_TYPE: Final = "billing"


class Direction(StrEnum):
    """Which way the money went."""

    #: Money received — a sale, a refund, an owner contribution.
    IN = "in"
    #: Money spent — a bill, an expense, a purchase.
    OUT = "out"

    @property
    def label(self) -> str:
        return "Money in" if self is Direction.IN else "Money out"

    @property
    def category_type(self) -> AccountType:
        """Which side of the P&L the non-cash leg belongs to."""
        return AccountType.INCOME if self is Direction.IN else AccountType.EXPENSE


@dataclass(frozen=True, slots=True)
class Category:
    """An account the user can file an entry against."""

    id: uuid.UUID
    code: str
    name: str
    direction: Direction
    #: Pre-selected in the form, so the common case needs no choice at all.
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class MoneyAccount:
    """Where the money sat or landed — a cash box or a bank account."""

    id: uuid.UUID
    code: str
    name: str
    is_default: bool = False


@dataclass(frozen=True, slots=True)
class Entry:
    """One recorded movement, reconstructed from its ledger entry."""

    id: uuid.UUID
    entry_number: str | None
    date: dt.date
    direction: Direction
    amount: Decimal
    description: str
    reference: str | None

    category_id: uuid.UUID
    category_name: str
    money_account_id: uuid.UUID
    money_account_name: str

    created_at: dt.datetime
    #: True once a reversal has cancelled it. Kept visible rather than hidden: the
    #: original and its reversal are both permanent records.
    is_reversed: bool


@dataclass(frozen=True, slots=True)
class Summary:
    from_date: dt.date
    to_date: dt.date
    money_in: Decimal
    money_out: Decimal
    entry_count: int

    @property
    def net(self) -> Decimal:
        return self.money_in - self.money_out


#: Default categories, by system key where one exists and by account code otherwise.
#: Chosen so the form opens on a sensible answer: most money in is a sale, and most
#: uncategorised money out is a general operating cost.
DEFAULT_INCOME_CODE: Final = "4100"
DEFAULT_EXPENSE_CODE: Final = "5250"


class BillingService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.accounts = AccountRepository(session)
        self.posting = PostingService(session)
        self.chart = ChartOfAccountsService(session)
        self.calendar = FiscalCalendarService(session)

    # -----------------------------------------------------------------------
    # Pick lists
    # -----------------------------------------------------------------------
    async def categories(self, organization_id: uuid.UUID) -> list[Category]:
        """Income and expense accounts, as a flat pick-list.

        Groups are excluded — you cannot post to a heading. Returned flat rather than
        as a tree because this form has one dropdown, and a shopkeeper choosing
        "Rent" does not care that it sits under "Operating Expenses".
        """
        rows = await self.accounts.list_for_org(organization_id, postable_only=True)

        categories: list[Category] = []
        for account in rows:
            if account.account_type is AccountType.INCOME:
                direction = Direction.IN
                default_code = DEFAULT_INCOME_CODE
            elif account.account_type is AccountType.EXPENSE:
                direction = Direction.OUT
                default_code = DEFAULT_EXPENSE_CODE
            else:
                continue

            categories.append(
                Category(
                    id=account.id,
                    code=account.code,
                    name=account.name,
                    direction=direction,
                    is_default=account.code == default_code,
                )
            )
        return categories

    async def money_accounts(self, organization_id: uuid.UUID) -> list[MoneyAccount]:
        """Cash and bank accounts, for "where did it come from / go to"."""
        rows = await self.accounts.list_for_org(organization_id, postable_only=True)
        cash = [a for a in rows if a.subtype.is_cash_equivalent]

        # Cash is the default: a business recording movements by hand is far more
        # often dealing in cash than reconciling a bank feed.
        default_id = next(
            (a.id for a in cash if a.system_key == SystemAccount.CASH),
            cash[0].id if cash else None,
        )
        return [
            MoneyAccount(id=a.id, code=a.code, name=a.name, is_default=a.id == default_id)
            for a in cash
        ]

    # -----------------------------------------------------------------------
    # Recording
    # -----------------------------------------------------------------------
    async def record(
        self,
        organization_id: uuid.UUID,
        actor: User,
        *,
        direction: Direction,
        entry_date: dt.date,
        amount: Decimal,
        description: str,
        category_id: uuid.UUID | None = None,
        money_account_id: uuid.UUID | None = None,
        reference: str | None = None,
        ctx: RequestContext | None = None,
    ) -> Entry:
        """Record one movement and post it to the ledger.

        ``category_id`` and ``money_account_id`` are optional: omitted, they fall back
        to the defaults, so the minimum viable entry really is a date, an amount, and
        a note — which is what was asked for.
        """
        if amount <= 0:
            raise ValidationError(
                "Enter an amount greater than zero. To correct a mistake, reverse the "
                "original entry rather than recording a negative one."
            )

        category = await self._resolve_category(organization_id, direction, category_id)
        money = await self._resolve_money_account(organization_id, money_account_id)

        # Without a fiscal year the posting fails with "no open period", which means
        # nothing to someone who never asked for a fiscal calendar. Create it on
        # demand instead: the year is derivable from the organization's own settings.
        await self._ensure_period(organization_id, entry_date)

        # Money out: the expense grows (debit), the cash shrinks (credit).
        # Money in: the cash grows (debit), the income grows (credit).
        if direction is Direction.OUT:
            debit_account, credit_account = category.id, money.id
            journal_type = JournalType.CASH
        else:
            debit_account, credit_account = money.id, category.id
            journal_type = JournalType.CASH

        from app.modules.accounting.schemas import JournalEntryCreate, JournalEntryLineInput

        journal = await self.posting.journals.get_by_type(organization_id, journal_type)
        if journal is None:
            raise BusinessRuleError(
                "This organization has no cash journal configured. "
                "Set up the chart of accounts first.",
                code="no_cash_journal",
            )

        entry = await self.posting.create_entry(
            organization_id,
            JournalEntryCreate(
                journal_id=journal.id,
                entry_date=entry_date,
                narration=description.strip(),
                reference=reference,
                lines=[
                    JournalEntryLineInput(account_id=debit_account, debit=amount, credit=ZERO),
                    JournalEntryLineInput(account_id=credit_account, debit=ZERO, credit=amount),
                ],
                # Posted immediately. A draft would mean the figure does not reach the
                # dashboard, and "I recorded it but it is not showing" is the worst
                # possible outcome for the one feature meant to be effortless.
                post=True,
            ),
            actor,
            ctx,
            source_type=SOURCE_TYPE,
        )

        log.info(
            "billing entry recorded",
            extra={
                "direction": direction.value,
                "amount": str(amount),
                "entry_number": entry.entry_number,
            },
        )
        return await self.get(organization_id, entry.id)

    async def _resolve_category(
        self, organization_id: uuid.UUID, direction: Direction, category_id: uuid.UUID | None
    ) -> Account:
        wanted = direction.category_type
        rows = await self.accounts.list_for_org(organization_id, postable_only=True)

        if category_id is not None:
            match = next((a for a in rows if a.id == category_id), None)
            if match is None:
                raise NotFoundError("Category")
            if match.account_type is not wanted:
                raise ValidationError(
                    f"{match.name} is a{'n' if wanted is AccountType.INCOME else ''} "
                    f"{match.account_type.value} account, so it cannot be used for "
                    f"{direction.label.lower()}."
                )
            return match

        default_code = DEFAULT_INCOME_CODE if direction is Direction.IN else DEFAULT_EXPENSE_CODE
        candidates = [a for a in rows if a.account_type is wanted]
        if not candidates:
            raise BusinessRuleError(
                f"No {wanted.value} accounts exist yet. Set up the chart of accounts first.",
                code="no_categories",
            )
        return next((a for a in candidates if a.code == default_code), candidates[0])

    async def _resolve_money_account(
        self, organization_id: uuid.UUID, money_account_id: uuid.UUID | None
    ) -> Account:
        rows = await self.accounts.list_for_org(organization_id, postable_only=True)
        cash = [a for a in rows if a.subtype.is_cash_equivalent]

        if money_account_id is not None:
            match = next((a for a in cash if a.id == money_account_id), None)
            if match is None:
                raise ValidationError(
                    "That is not a cash or bank account, so money cannot move through it."
                )
            return match

        if not cash:
            raise BusinessRuleError(
                "No cash or bank account exists yet. Set up the chart of accounts first.",
                code="no_money_account",
            )
        return next(
            (a for a in cash if a.system_key == SystemAccount.CASH),
            cash[0],
        )

    async def _ensure_period(self, organization_id: uuid.UUID, on: dt.date) -> None:
        start_month = (
            await self.session.execute(
                select(Organization.fiscal_year_start_month).where(
                    Organization.id == organization_id
                )
            )
        ).scalar_one_or_none() or 4

        await self.calendar.ensure_year_for(
            organization_id, fiscal_year_start_month=start_month, on=on
        )

    # -----------------------------------------------------------------------
    # Reading back
    # -----------------------------------------------------------------------
    def _entry_query(self, organization_id: uuid.UUID) -> Select[tuple[JournalEntry]]:
        """Posted billing entries, excluding the reversals that cancel them.

        ``reverse_entry`` copies ``source_type`` onto the mirror entry it creates, so
        without the ``reverses_id`` filter a cancelled ₹5,000 expense shows up here
        twice: once struck through, and once as a phantom ₹5,000 *receipt* — because
        reversing a payment debits cash. Two rows that cancel each other is precisely
        the wrong thing to show the audience this screen exists for.

        The ledger keeps both entries, as it must. This is a view over them, and the
        original already carries ``is_reversed``, which says everything the user needs.
        """
        return (
            select(JournalEntry)
            .where(
                JournalEntry.organization_id == organization_id,
                JournalEntry.source_type == SOURCE_TYPE,
                JournalEntry.status.in_(POSTED_STATUSES),
                JournalEntry.reverses_id.is_(None),
            )
            .options(selectinload(JournalEntry.lines).selectinload(JournalEntryLine.account))
        )

    async def get(self, organization_id: uuid.UUID, entry_id: uuid.UUID) -> Entry:
        row = (
            await self.session.execute(
                self._entry_query(organization_id).where(JournalEntry.id == entry_id)
            )
        ).scalar_one_or_none()
        if row is None:
            raise NotFoundError("Entry")
        return self._to_entry(row)

    async def paginate(
        self,
        organization_id: uuid.UUID,
        params: PageParams,
        *,
        direction: Direction | None = None,
        from_date: dt.date | None = None,
        to_date: dt.date | None = None,
        q: str | None = None,
    ) -> tuple[list[Entry], int]:
        """Most recent first — a day book is read backwards from today."""
        query = self._entry_query(organization_id)

        if from_date is not None:
            query = query.where(JournalEntry.entry_date >= from_date)
        if to_date is not None:
            query = query.where(JournalEntry.entry_date <= to_date)
        if q:
            query = query.where(JournalEntry.narration.ilike(f"%{q.strip()}%"))

        counted = query.options().order_by(None).subquery()
        total = (await self.session.execute(select(func.count()).select_from(counted))).scalar_one()

        rows = (
            (
                await self.session.execute(
                    query.order_by(JournalEntry.entry_date.desc(), JournalEntry.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

        entries = [self._to_entry(row) for row in rows]

        # Direction is a property of the reconstructed entry rather than a column, so
        # it is filtered here rather than in SQL. Acceptable: the query is already
        # narrowed by organization, source type, and date, and a hand-kept day book is
        # hundreds of rows a year, not millions.
        if direction is not None:
            entries = [entry for entry in entries if entry.direction is direction]
            total = len(entries)

        start = params.offset
        return entries[start : start + params.limit], total

    def _to_entry(self, row: JournalEntry) -> Entry:
        """Reconstruct the simple view from the two-line ledger entry.

        Exact, not heuristic: this module writes exactly two lines, one on a
        cash-equivalent account and one on an income or expense account. Anything else
        under this ``source_type`` would be corrupt data, so it fails loudly rather
        than guessing.
        """
        if len(row.lines) != 2:  # pragma: no cover — only reachable via manual SQL
            raise BusinessRuleError(
                f"Entry {row.entry_number} does not have the two lines a billing entry "
                "must have. It may have been edited outside the application.",
                code="billing_entry_malformed",
            )

        money_line = next(
            (line for line in row.lines if line.account.subtype.is_cash_equivalent), None
        )
        category_line = next(
            (
                line
                for line in row.lines
                if line.account.account_type in (AccountType.INCOME, AccountType.EXPENSE)
            ),
            None,
        )
        if money_line is None or category_line is None:  # pragma: no cover
            raise BusinessRuleError(
                f"Entry {row.entry_number} is not shaped like a billing entry.",
                code="billing_entry_malformed",
            )

        # The cash leg being credited means money left; debited means it arrived.
        direction = Direction.OUT if money_line.credit > 0 else Direction.IN

        return Entry(
            id=row.id,
            entry_number=row.entry_number,
            date=row.entry_date,
            direction=direction,
            amount=money_line.credit if direction is Direction.OUT else money_line.debit,
            description=row.narration,
            reference=row.reference,
            category_id=category_line.account_id,
            category_name=category_line.account.name,
            money_account_id=money_line.account_id,
            money_account_name=money_line.account.name,
            created_at=row.created_at,
            is_reversed=row.status is EntryStatus.REVERSED,
        )

    async def summary(
        self, organization_id: uuid.UUID, *, from_date: dt.date, to_date: dt.date
    ) -> Summary:
        """Money in, money out, and the net, for a window.

        Counts only what this module recorded, so it answers "what have I logged"
        rather than "what did the business earn" — the second question is the P&L's,
        and it includes invoices too.
        """
        entries, _ = await self.paginate(
            organization_id,
            PageParams(page=1, page_size=200),
            from_date=from_date,
            to_date=to_date,
        )
        # Reversed entries are excluded from the totals but stay in the list: the
        # cancellation is part of the record, its effect on the balance is not.
        live = [entry for entry in entries if not entry.is_reversed]

        return Summary(
            from_date=from_date,
            to_date=to_date,
            money_in=sum((e.amount for e in live if e.direction is Direction.IN), start=ZERO),
            money_out=sum((e.amount for e in live if e.direction is Direction.OUT), start=ZERO),
            entry_count=len(live),
        )

    # -----------------------------------------------------------------------
    # Undo
    # -----------------------------------------------------------------------
    async def reverse(
        self,
        organization_id: uuid.UUID,
        entry_id: uuid.UUID,
        actor: User,
        *,
        reason: str | None = None,
        ctx: RequestContext | None = None,
    ) -> Entry:
        """Cancel an entry by posting its mirror image.

        Not a delete, and not an edit. A posted ledger entry is immutable in this
        system, so the only honest undo is an opposite entry that nets it to zero —
        which is also what an auditor expects to see. Both rows survive.
        """
        entry = await self.get(organization_id, entry_id)
        if entry.is_reversed:
            raise BusinessRuleError(
                "This entry has already been reversed.", code="already_reversed"
            )

        await self.posting.reverse_entry(
            organization_id,
            entry_id,
            actor,
            narration=reason or f"Reversal of {entry.description}",
            ctx=ctx,
        )
        return await self.get(organization_id, entry_id)


__all__ = [
    "BillingService",
    "Category",
    "Direction",
    "Entry",
    "MoneyAccount",
    "Summary",
]
