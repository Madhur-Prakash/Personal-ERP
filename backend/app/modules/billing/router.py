"""Billing endpoints - the simple money in / money out path."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy import select

from app.core.exceptions import NotFoundError
from app.core.pagination import Page, PageParams
from app.modules.analytics.periods import local_date
from app.modules.auth.dependencies import (
    ActiveOrganizationId,
    CurrentUser,
    DbSession,
    RequestCtx,
    require_permission,
)
from app.modules.billing.schemas import (
    BillingOptions,
    BillingSummary,
    CategoryRead,
    CreateCategoryRequest,
    CreateMoneyAccountRequest,
    EntryRead,
    MoneyAccountRead,
    RecordEntryRequest,
    ReverseEntryRequest,
)
from app.modules.billing.service import BillingService, Direction, Entry
from app.modules.organizations.models import Organization
from app.modules.rbac.permissions import Permission

router = APIRouter(prefix="/billing", tags=["Billing"])


def get_billing(session: DbSession) -> BillingService:
    return BillingService(session)


BillingDep = Annotated[BillingService, Depends(get_billing)]


async def get_today(organization_id: ActiveOrganizationId, session: DbSession) -> dt.date:
    """Today in the organization's timezone.

    Not the server's UTC date: at 00:30 IST it is still yesterday in UTC, so a form
    defaulting to "today" would pre-fill the wrong date - and an entry dated a day
    early can land in a month that is already closed.
    """
    row = (
        await session.execute(
            select(Organization.timezone).where(Organization.id == organization_id)
        )
    ).scalar_one_or_none()
    if row is None:  # pragma: no cover - resolved by the auth dependency
        raise NotFoundError("Organization")
    return local_date(dt.datetime.now(dt.UTC), row)


TodayDep = Annotated[dt.date, Depends(get_today)]


def _entry(entry: Entry) -> EntryRead:
    return EntryRead(
        id=entry.id,
        entry_number=entry.entry_number,
        date=entry.date,
        direction=entry.direction,
        amount=entry.amount,
        description=entry.description,
        reference=entry.reference,
        party=entry.party,
        category_id=entry.category_id,
        category_name=entry.category_name,
        money_account_id=entry.money_account_id,
        money_account_name=entry.money_account_name,
        created_at=entry.created_at,
        is_reversed=entry.is_reversed,
    )


# ---------------------------------------------------------------------------
# Options
# ---------------------------------------------------------------------------
@router.get("/options", response_model=BillingOptions, summary="Categories and accounts")
async def options(
    organization_id: ActiveOrganizationId,
    service: BillingDep,
    session: DbSession,
    today: TodayDep,
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_READ))],
) -> BillingOptions:
    """Everything the entry form needs, in one call.

    One request rather than three, because the form cannot render usefully until it
    has all of them and three round trips would show it assembling itself.
    """
    currency = (
        await session.execute(
            select(Organization.currency).where(Organization.id == organization_id)
        )
    ).scalar_one_or_none() or "INR"

    categories = await service.categories(organization_id)
    accounts = await service.money_accounts(organization_id)

    return BillingOptions(
        categories=[
            CategoryRead(
                id=c.id,
                code=c.code,
                name=c.name,
                direction=c.direction,
                group=c.group,
                is_default=c.is_default,
            )
            for c in categories
        ],
        money_accounts=[
            MoneyAccountRead(id=a.id, code=a.code, name=a.name, is_default=a.is_default)
            for a in accounts
        ],
        today=today,
        currency=currency,
    )


@router.post(
    "/categories",
    response_model=CategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a category",
)
async def create_category(
    data: CreateCategoryRequest,
    organization_id: ActiveOrganizationId,
    user: CurrentUser,
    service: BillingDep,
    ctx: RequestCtx,
    _: Annotated[None, Depends(require_permission(Permission.ACCOUNT_WRITE))],
) -> CategoryRead:
    """Create an income or expense category from a name alone.

    The built-in list covers a general small business and a household, but it cannot
    anticipate every trade. This is the escape hatch, and deliberately the only
    account-creating path on this screen: the account code, parent group, and subtype
    are all derived, so nobody has to understand the chart of accounts to file a
    payment under "Tempo Hire".

    Guarded on `account:write` rather than `journal:write` - it does add to the chart of
    accounts, and an organization may want that narrower than day-to-day recording.
    """
    category = await service.create_category(
        organization_id, user, name=data.name, direction=data.direction, ctx=ctx
    )
    return CategoryRead(
        id=category.id,
        code=category.code,
        name=category.name,
        direction=category.direction,
        group=category.group,
        is_default=category.is_default,
    )


@router.post(
    "/money-accounts",
    response_model=MoneyAccountRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add a cash or bank account",
)
async def create_money_account(
    data: CreateMoneyAccountRequest,
    organization_id: ActiveOrganizationId,
    user: CurrentUser,
    service: BillingDep,
    ctx: RequestCtx,
    _: Annotated[None, Depends(require_permission(Permission.ACCOUNT_WRITE))],
) -> MoneyAccountRead:
    """Create a place money can sit.

    The seeded chart has one till and one current account, which covers a business
    with exactly those. A second bank, a UPI wallet, a card-settlement account, or a
    partner's petty cash are all ordinary - and without this, money that moved through
    a wallet gets filed as cash and no balance matches anything real.
    """
    account = await service.create_money_account(
        organization_id, user, name=data.name, kind=data.kind, ctx=ctx
    )
    return MoneyAccountRead(
        id=account.id, code=account.code, name=account.name, is_default=account.is_default
    )


# ---------------------------------------------------------------------------
# Record
# ---------------------------------------------------------------------------
@router.post(
    "",
    response_model=EntryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record money in or out",
)
async def record_entry(
    data: RecordEntryRequest,
    organization_id: ActiveOrganizationId,
    user: CurrentUser,
    service: BillingDep,
    ctx: RequestCtx,
    today: TodayDep,
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_WRITE))],
) -> EntryRead:
    """Record one movement. It is posted to the ledger immediately.

    Posted, not saved as a draft - the whole point of this feature is that the figure
    shows up on the dashboard, and a draft entry does not reach any report. "I recorded
    it and it is not showing" would be the worst outcome for the one screen meant to be
    effortless.

    Because it is a real ledger posting, it appears in the trial balance, the P&L, the
    cash flow statement, and the analytics trend without anything else being wired up.
    """
    entry = await service.record(
        organization_id,
        user,
        direction=data.direction,
        entry_date=data.entry_date or today,
        amount=data.amount,
        description=data.description,
        category_id=data.category_id,
        money_account_id=data.money_account_id,
        reference=data.reference,
        party=data.party,
        ctx=ctx,
    )
    return _entry(entry)


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------
@router.get("", response_model=Page[EntryRead], summary="List entries")
async def list_entries(
    organization_id: ActiveOrganizationId,
    service: BillingDep,
    params: Annotated[PageParams, Depends()],
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_READ))],
    direction: Annotated[Direction | None, Query()] = None,
    from_date: Annotated[dt.date | None, Query()] = None,
    to_date: Annotated[dt.date | None, Query()] = None,
    q: Annotated[str | None, Query(description="Search the description")] = None,
) -> Page[EntryRead]:
    """The day book, most recent first."""
    rows, total = await service.paginate(
        organization_id,
        params,
        direction=direction,
        from_date=from_date,
        to_date=to_date,
        q=q,
    )
    return Page.create([_entry(row) for row in rows], total=total, params=params)


@router.get("/summary", response_model=BillingSummary, summary="Totals for a window")
async def summary(
    organization_id: ActiveOrganizationId,
    service: BillingDep,
    today: TodayDep,
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_READ))],
    from_date: Annotated[dt.date | None, Query()] = None,
    to_date: Annotated[dt.date | None, Query()] = None,
) -> BillingSummary:
    """In, out, and the net for what this screen recorded.

    Deliberately narrower than the P&L: it answers "what have I logged here", not
    "what did the business earn", which also includes invoices. Two different
    questions, and conflating them would make the smaller number look wrong.
    """
    result = await service.summary(
        organization_id,
        from_date=from_date or today.replace(day=1),
        to_date=to_date or today,
    )
    return BillingSummary(
        from_date=result.from_date,
        to_date=result.to_date,
        money_in=result.money_in,
        money_out=result.money_out,
        net=result.net,
        entry_count=result.entry_count,
    )


@router.get("/{entry_id}", response_model=EntryRead, summary="Get one entry")
async def get_entry(
    entry_id: uuid.UUID,
    organization_id: ActiveOrganizationId,
    service: BillingDep,
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_READ))],
) -> EntryRead:
    return _entry(await service.get(organization_id, entry_id))


# ---------------------------------------------------------------------------
# Undo
# ---------------------------------------------------------------------------
@router.post("/{entry_id}/reverse", response_model=EntryRead, summary="Cancel an entry")
async def reverse_entry(
    entry_id: uuid.UUID,
    data: ReverseEntryRequest,
    organization_id: ActiveOrganizationId,
    user: CurrentUser,
    service: BillingDep,
    ctx: RequestCtx,
    _: Annotated[None, Depends(require_permission(Permission.JOURNAL_REVERSE))],
) -> EntryRead:
    """Cancel an entry by posting its mirror image.

    There is no delete and no edit. A posted ledger entry is immutable here, so the
    only honest undo is an opposite entry that nets it to zero - which is also what an
    auditor expects to find. Both rows survive, and the original stays in the list
    marked as reversed.
    """
    return _entry(
        await service.reverse(organization_id, entry_id, user, reason=data.reason, ctx=ctx)
    )


__all__ = ["router"]
