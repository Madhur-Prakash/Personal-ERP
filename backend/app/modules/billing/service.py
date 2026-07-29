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
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Final

from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.context import RequestContext
from app.core.exceptions import (
    BusinessRuleError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from app.core.logging import get_logger
from app.core.pagination import PageParams
from app.db.types import ZERO
from app.modules.accounting.coa_template import SystemAccount
from app.modules.accounting.models import (
    Account,
    AccountSubtype,
    AccountType,
    EntryStatus,
    JournalEntry,
    JournalEntryLine,
    JournalType,
)
from app.modules.accounting.repository import POSTED_STATUSES, AccountRepository
from app.modules.accounting.schemas import AccountCreate
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


class MoneyKind(StrEnum):
    """How a money account reconciles.

    Both are cash-equivalent for the cash flow statement. They are separate because
    they are checked differently: cash against a physical count, a bank against a
    statement — and a UPI wallet or card-settlement account behaves like a bank.
    """

    CASH = "cash"
    BANK = "bank"


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
    #: The parent group's name, so the dropdown can be grouped. A flat list of nearly
    #: eighty categories is a list nobody reads to the end of.
    group: str
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
    #: Who it came from (money in) or went to (money out). Free text.
    party: str | None

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
        await self.ensure_books(organization_id)
        # Every account, groups included: the groups are not selectable but their names
        # are what the dropdown is organised by.
        every = await self.accounts.list_for_org(organization_id, include_inactive=False)
        group_names = {account.id: account.name for account in every if account.is_group}
        rows = [account for account in every if not account.is_group]

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
                    group=group_names.get(account.parent_id or uuid.UUID(int=0))
                    or ("Income" if direction is Direction.IN else "Expenses"),
                    is_default=account.code == default_code,
                )
            )
        return categories

    async def create_category(
        self,
        organization_id: uuid.UUID,
        actor: User,
        *,
        name: str,
        direction: Direction,
        ctx: RequestContext | None = None,
    ) -> Category:
        """Add a category of the user's own.

        The template cannot anticipate every business, so this is the escape hatch —
        and it is deliberately the *only* account-creation path exposed on this screen.
        The user supplies a name and a direction; the code, the parent group, the
        subtype, and the depth are all derived. Asking a shopkeeper to choose an account
        code and a subtype to record a payment would defeat the point of the screen.

        The new account is filed under the same group the direction's own defaults live
        in, so it appears alongside the categories it belongs with rather than at the
        top level.
        """
        await self.ensure_books(organization_id)

        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("Give the category a name.")

        every = await self.accounts.list_for_org(organization_id, include_inactive=True)

        if any(a.name.casefold() == cleaned.casefold() for a in every):
            raise ConflictError(
                f'A category called "{cleaned}" already exists.',
                code="category_exists",
            )

        wanted = direction.category_type
        anchor_code = DEFAULT_INCOME_CODE if direction is Direction.IN else DEFAULT_EXPENSE_CODE
        anchor = next((a for a in every if a.code == anchor_code), None)
        parent = next(
            (a for a in every if anchor is not None and a.id == anchor.parent_id),
            None,
        ) or next((a for a in every if a.is_group and a.account_type is wanted), None)

        if parent is None:  # pragma: no cover — ensure_books guarantees a group exists
            raise BusinessRuleError(
                "The chart of accounts has no group to file this under.",
                code="no_parent_group",
            )

        account = await self.chart.create_account(
            organization_id,
            AccountCreate(
                code=self._next_code(every, parent.code),
                name=cleaned,
                account_type=wanted,
                subtype=anchor.subtype if anchor is not None else parent.subtype,
                parent_id=parent.id,
                is_group=False,
            ),
            actor,
            ctx,
        )

        log.info(
            "billing category created",
            extra={"name": cleaned, "code": account.code, "direction": direction.value},
        )
        return Category(
            id=account.id,
            code=account.code,
            name=account.name,
            direction=direction,
            group=parent.name,
            is_default=False,
        )

    async def create_money_account(
        self,
        organization_id: uuid.UUID,
        actor: User,
        *,
        name: str,
        kind: MoneyKind,
        ctx: RequestContext | None = None,
    ) -> MoneyAccount:
        """Add a cash box or a bank account.

        The seeded chart gives one of each, which covers a business with a till and a
        current account and nobody else. A second bank, a UPI wallet, a partner's
        petty cash, or the card machine's settlement account are all ordinary, and
        without this the only choices are "Cash on Hand" and "Primary Bank Account" —
        so money that moved through a wallet gets filed as cash and the balances stop
        matching anything real.

        Only a name and whether it behaves like cash or a bank. The subtype is what
        matters to the software: both are cash-equivalent for the cash flow statement,
        but they reconcile differently — cash against a physical count, a bank against
        a statement — so they are separate subtypes rather than one.
        """
        await self.ensure_books(organization_id)

        cleaned = name.strip()
        if not cleaned:
            raise ValidationError("Give the account a name.")

        every = await self.accounts.list_for_org(organization_id, include_inactive=True)
        if any(a.name.casefold() == cleaned.casefold() for a in every):
            raise ConflictError(
                f'An account called "{cleaned}" already exists.', code="account_exists"
            )

        by_code = {a.code: a for a in every}
        if kind is MoneyKind.BANK:
            # Bank accounts nest under their own group, so several read as a set.
            group = by_code.get("1120")
            parent = group if group is not None and group.is_group else by_code.get("1100")
            anchor = "1120"
            subtype = AccountSubtype.BANK
        else:
            parent = by_code.get("1100")
            # Numbered after Cash on Hand rather than from the parent, so a second till
            # sorts next to the first instead of ahead of it at 1101.
            anchor = "1110"
            subtype = AccountSubtype.CASH

        if parent is None:  # pragma: no cover — ensure_books guarantees the group
            raise BusinessRuleError(
                "The chart of accounts has no current-assets group.", code="no_parent_group"
            )

        account = await self.chart.create_account(
            organization_id,
            AccountCreate(
                code=self._next_code(every, anchor),
                name=cleaned,
                account_type=AccountType.ASSET,
                subtype=subtype,
                parent_id=parent.id,
                is_group=False,
                is_reconcilable=True,
            ),
            actor,
            ctx,
        )

        log.info(
            "money account created",
            extra={"name": cleaned, "code": account.code, "kind": kind.value},
        )
        return MoneyAccount(id=account.id, code=account.code, name=account.name, is_default=False)

    @staticmethod
    def _next_code(existing: Sequence[Account], parent_code: str) -> str:
        """The next free code inside a parent's block.

        Codes are hierarchical (``5200`` owns ``5201``-``5299``), so a new child is
        numbered inside its parent's range. Walking upward from the parent finds the
        first gap, which keeps user-added categories sorted next to their siblings
        rather than appended at the end of the chart.
        """
        taken = {account.code for account in existing}
        base = int(parent_code)
        for offset in range(1, 100):
            candidate = str(base + offset)
            if candidate not in taken:
                return candidate
        # The parent's block is full; fall back to a free code anywhere above it.
        for candidate_int in range(base + 100, base + 1000):
            candidate = str(candidate_int)
            if candidate not in taken:
                return candidate
        raise BusinessRuleError(  # pragma: no cover — 1000 codes exhausted
            "No account code is free near this group.", code="no_free_code"
        )

    async def money_accounts(self, organization_id: uuid.UUID) -> list[MoneyAccount]:
        """Cash and bank accounts, for "where did it come from / go to"."""
        await self.ensure_books(organization_id)
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
        party: str | None = None,
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

        # First, because the resolvers below need a chart to resolve against and the
        # posting needs an open period. Cheap and idempotent when both already exist.
        await self.ensure_books(organization_id, entry_date)

        category = await self._resolve_category(organization_id, direction, category_id)
        money = await self._resolve_money_account(organization_id, money_account_id)

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
                counterparty=(party or "").strip() or None,
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

    async def ensure_books(self, organization_id: uuid.UUID, on: dt.date | None = None) -> None:
        """Make sure this organization has a chart of accounts and a fiscal period.

        Called before every read and every write on this screen, and it is a **repair
        path**, not just a convenience. Organizations created through registration before
        that path seeded the books have no chart at all, so the first thing their owner
        saw here was "no income accounts exist yet" with two empty dropdowns and no way
        forward. Seeding on demand fixes those accounts the moment someone opens the
        screen, with no migration and nothing for the user to do.

        Both halves are idempotent — ``seed_defaults`` skips entirely when any account
        exists, ``ensure_year_for`` returns the existing year — so the common case costs
        one cheap existence check.
        """
        start_month = (
            await self.session.execute(
                select(Organization.fiscal_year_start_month).where(
                    Organization.id == organization_id
                )
            )
        ).scalar_one_or_none() or 4

        # `sync_template` rather than `seed_defaults`: it seeds when there is nothing,
        # and tops up by code when there is. Organizations created against an earlier
        # template would otherwise never see categories added since — which is exactly
        # what happened when the household and expanded expense lists landed.
        await self.chart.sync_template(organization_id)
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
            # The party is searched alongside the description: "Airtel" is at least as
            # likely a search as the note someone typed next to it.
            pattern = f"%{q.strip()}%"
            query = query.where(
                or_(
                    JournalEntry.narration.ilike(pattern),
                    JournalEntry.counterparty.ilike(pattern),
                )
            )

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
            party=row.counterparty,
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
    "MoneyKind",
    "Summary",
]
