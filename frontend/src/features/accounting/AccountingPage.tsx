/**
 * Accounting - chart of accounts, journal entries, and the financial statements.
 *
 * One page with tabs rather than four routes: an accountant moves between the
 * trial balance and the ledger constantly, and a full route transition (with its
 * refetch) on every switch is slower than keeping the queries warm in one place.
 */
import { useQuery } from '@tanstack/react-query';
import { useNavigate, useSearch } from '@tanstack/react-router';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, BookOpen, Scale, TrendingUp, Undo2 } from 'lucide-react';
import { useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import type { Column } from '@/components/ui/DataTable';
import { DataTable, PageHeader, Pagination } from '@/components/ui/DataTable';
import { Skeleton } from '@/components/ui/Skeleton';
import {
  type JournalEntry,
  type ReportLine,
  type TrialBalanceRow,
  accountingApi,
} from '@/features/accounting/api';
import {
  AccountBalancesChart,
  BalanceByTypeChart,
  CashMovementChart,
} from '@/features/accounting/AccountingCharts';
import { SpendingMixChart, TrendChart } from '@/features/accounting/CompositionCharts';
import { ProfitWaterfallChart } from '@/features/accounting/WaterfallChart';
import { useReportRange } from '@/features/accounting/ReportRange';
import { analyticsApi } from '@/features/analytics/api';
import { cn } from '@/lib/cn';
import { formatDate, formatMoney, isZeroMoney } from '@/lib/format';

type Tab = 'chart' | 'entries' | 'trial-balance' | 'pnl' | 'balance-sheet';

const TABS: { key: Tab; label: string }[] = [
  { key: 'chart', label: 'Chart of accounts' },
  { key: 'entries', label: 'Journal entries' },
  { key: 'trial-balance', label: 'Trial balance' },
  { key: 'pnl', label: 'Profit & loss' },
  { key: 'balance-sheet', label: 'Balance sheet' },
];

/** Narrows an untrusted search param to a known tab, so a hand-edited query
 *  string falls back to the default instead of breaking the page. */
const TAB_KEYS = ['chart', 'entries', 'trial-balance', 'pnl', 'balance-sheet'] as const;

function isTab(value: unknown): value is Tab {
  return typeof value === 'string' && (TAB_KEYS as readonly string[]).includes(value);
}

export function AccountingPage() {
  // The tab lives in the URL, not in component state, so a reload returns to it and
  // the view can be linked to. Read untyped and narrowed by `isTab`: that is safer
  // than a typed `from`, because a hand-edited query string then falls back to the
  // default rather than throwing.
  const navigate = useNavigate();
  const search = useSearch({ strict: false });
  const tab: Tab = isTab(search.tab) ? search.tab : 'chart';
  const setTab = (next: Tab) => {
    // `replace` keeps tab switching out of the back stack.
    void navigate({ to: '/accounting', search: { tab: next }, replace: true });
  };

  return (
    <div>
      <PageHeader
        title="Accounting"
        description="Double-entry ledger. Posted entries are immutable - corrections are made by reversal."
      />

      <div
        className="border-border mb-4 flex gap-1 overflow-x-auto border-b"
        role="tablist"
        aria-label="Accounting views"
      >
        {TABS.map((item) => (
          <button
            key={item.key}
            type="button"
            role="tab"
            aria-selected={tab === item.key}
            onClick={() => setTab(item.key)}
            className={cn(
              'shrink-0 border-b-2 px-3 py-2 text-[13px] font-medium transition-colors',
              tab === item.key
                ? 'border-primary text-content'
                : 'text-content-muted hover:text-content border-transparent',
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {tab === 'chart' && <ChartOfAccounts />}
      {tab === 'entries' && <JournalEntries />}
      {tab === 'trial-balance' && <TrialBalanceReport />}
      {tab === 'pnl' && <ProfitAndLossReport />}
      {tab === 'balance-sheet' && <BalanceSheetReport />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Chart of accounts
// ---------------------------------------------------------------------------
function ChartOfAccounts() {
  // One range control drives every chart on this tab. Separate filters per chart would
  // let two panels sit side by side showing different periods, which is a reliable way to
  // draw a wrong conclusion from correct numbers.
  const { range, control } = useReportRange();

  const { data, isLoading } = useQuery({
    // Balances are point-in-time, so only the end of the range applies — "cash over
    // March" is not a number.
    queryKey: ['accounts', range.to_date],
    queryFn: () => accountingApi.accounts({ as_of: range.to_date }),
  });

  // The waterfall's closing bar must equal the dashboard's net profit, so it is built
  // from the statement rather than recomputed.
  const { data: report, isLoading: reportLoading } = useQuery({
    queryKey: ['pnl', range],
    queryFn: () => accountingApi.profitAndLoss(range),
  });

  const { data: trend } = useQuery({
    queryKey: ['analytics-trend', range],
    queryFn: () => analyticsApi.trend('last_12_months', range),
  });

  const accounts = data ?? [];

  // The 114-row table is gone. It listed every account in the template, of which four
  // hold a balance, so it was a hundred rows of ₹0.00 in front of the four figures
  // anyone came here for. The charts show what has money; the trial balance is the
  // place to read exact per-account figures.
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="Period"
          description={`Every chart below covers ${range.from_date} to ${range.to_date}.`}
          action={control}
        />
      </Card>

      <ProfitWaterfallChart report={report} isLoading={reportLoading} />

      {isLoading ? (
        <Card>
          <CardBody className="pt-5">
            <Skeleton className="h-64 w-full" />
          </CardBody>
        </Card>
      ) : (
        <>
          <div className="grid gap-4 xl:grid-cols-2">
            <AccountBalancesChart accounts={accounts} />
            <SpendingMixChart accounts={accounts} />
          </div>

          <TrendChart points={trend?.points} />

          <BalanceByTypeChart accounts={accounts} />
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Journal entries
// ---------------------------------------------------------------------------
function Parties({ names }: { names: string[] }) {
  if (names.length === 0) return <span className="text-content-muted">-</span>;

  const [first, ...rest] = names;
  return (
    <div className="min-w-0">
      <p className="text-content truncate text-[12px]">{first}</p>
      {rest.length > 0 && (
        // Named in the tooltip rather than listed: a cell that grows with the number of
        // parties would set the row height for the whole table.
        <p className="text-content-muted truncate text-[11px]" title={rest.join(', ')}>
          and {rest.length} more
        </p>
      )}
    </div>
  );
}

function JournalEntries() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useQuery({
    queryKey: ['journal-entries', page],
    queryFn: () => accountingApi.entries({ page, page_size: 25 }),
  });

  const statusTone: Record<string, BadgeTone> = {
    draft: 'neutral',
    posted: 'success',
    reversed: 'warning',
  };

  const columns: Column<JournalEntry>[] = [
    {
      header: 'Number',
      cell: (row) => (
        <span className="font-mono text-[12px]">
          {row.entry_number ?? <span className="text-content-muted">draft</span>}
        </span>
      ),
    },
    { header: 'Date', cell: (row) => formatDate(row.entry_date) },
    {
      header: 'Narration',
      cell: (row) => (
        <div>
          <p className="text-content">{row.narration}</p>
          <p className="text-content-muted text-[11px]">
            {row.journal_code}
            {row.reference && ` · ${row.reference}`}
          </p>
        </div>
      ),
    },
    {
      header: 'Money',
      hideOnMobile: true,
      cell: (row) =>
        row.cash_direction === null ? (
          // No cash leg, or a transfer between your own accounts that nets to nothing.
          <span className="text-content-muted text-[12px]">no cash movement</span>
        ) : (
          <span
            className={cn(
              'text-[12px] font-medium',
              row.cash_direction === 'in' ? 'text-success' : 'text-danger',
            )}
          >
            {row.cash_direction === 'in' ? 'In' : 'Out'} {formatMoney(row.cash_amount)}
          </span>
        ),
    },
    {
      header: 'Status',
      hideOnMobile: true,
      cell: (row) =>
        row.status === 'reversed' ? (
          <Badge tone="warning" title="Cancelled by an opposite entry. Both remain on the record.">
            Reversed - cancelled
          </Badge>
        ) : row.reverses_id ? (
          <Badge tone="neutral" title="This entry cancels an earlier one.">
            Reversal entry
          </Badge>
        ) : (
          <Badge tone={statusTone[row.status] ?? 'neutral'}>{row.status}</Badge>
        ),
    },
    {
      header: 'Amount',
      numeric: true,
      cell: (row) => (
        <span className={cn(row.status === 'reversed' && 'text-content-muted line-through')}>
          {formatMoney(row.total_debit)}
        </span>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <CashMovementChart entries={data?.items ?? []} />

      <Card>
        <DataTable
          columns={columns}
          rows={data?.items ?? []}
          rowKey={(row) => row.id}
          isLoading={isLoading}
          empty={{
            title: 'No journal entries',
            description: 'Entries appear here as invoices, bills, and payments are posted.',
          }}
        />
        {data && (
          <Pagination
            page={data.meta.page}
            totalPages={data.meta.total_pages}
            totalItems={data.meta.total_items}
            onChange={setPage}
          />
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Trial balance
// ---------------------------------------------------------------------------
/**
 * Did this account have movement that cancelled out?
 *
 * Distinct from "no activity": an account whose ₹100 charge was reversed has a story,
 * an untouched account does not, and showing both as two dashes conflates them.
 */
function netsToNil(row: TrialBalanceRow): boolean {
  return (
    isZeroMoney(row.debit) &&
    isZeroMoney(row.credit) &&
    !(isZeroMoney(row.gross_debit) && isZeroMoney(row.gross_credit))
  );
}

function TrialBalanceReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['trial-balance'],
    queryFn: () => accountingApi.trialBalance(),
  });

  return (
    <div className="space-y-4">
      {data && !data.is_balanced && (
        // Surfaced rather than hidden: an unbalanced ledger is the single most
        // serious condition this system can be in.
        <Card className="border-danger/40 bg-danger-bg">
          <CardBody className="flex items-start gap-3">
            <AlertTriangle className="text-danger mt-0.5 h-4 w-4 shrink-0" />
            <div>
              <p className="text-danger text-[13px] font-semibold">Ledger does not balance</p>
              <p className="text-content-secondary text-[12px]">
                Debits {formatMoney(data.total_debit)} ≠ credits {formatMoney(data.total_credit)}.
                This should be impossible - contact support.
              </p>
            </div>
          </CardBody>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Trial balance"
          description={data ? `As at ${formatDate(data.as_of)}` : undefined}
          action={
            data?.is_balanced ? (
              <Badge tone="success" dot>
                Balanced
              </Badge>
            ) : undefined
          }
        />
        <DataTable
          columns={[
            // {
            //   header: 'Code',
            //   cell: (row) => <span className="font-mono text-[12px]">{row.code}</span>,
            // },
            {
              header: 'Account',
              cell: (row) => (
                <div>
                  <span className="text-content">{row.name}</span>
                  {netsToNil(row) && (
                    <p className="text-warning mt-1 flex items-start gap-1.5 text-[13px]">
                      <Undo2 className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
                      <span>
                        <strong className="font-semibold">{formatMoney(row.gross_debit)}</strong>{' '}
                        was posted here and then reversed, so it does not affect the balance.
                      </span>
                    </p>
                  )}
                </div>
              ),
            },
            {
              header: 'Money from',
              hideOnMobile: true,
              cell: (row) => <Parties names={row.money_from} />,
            },
            {
              header: 'Money to',
              hideOnMobile: true,
              cell: (row) => <Parties names={row.money_to} />,
            },
            {
              header: 'Debit',
              numeric: true,
              cell: (row) =>
                isZeroMoney(row.debit) ? (
                  <span className="text-content-muted">-</span>
                ) : (
                  formatMoney(row.debit)
                ),
            },
            {
              header: 'Credit',
              numeric: true,
              cell: (row) =>
                isZeroMoney(row.credit) ? (
                  <span className="text-content-muted">-</span>
                ) : (
                  formatMoney(row.credit)
                ),
            },
          ]}
          rows={data?.rows ?? []}
          rowKey={(row) => row.account_id}
          isLoading={isLoading}
          empty={{ title: 'Nothing posted yet', description: 'Post an entry to see balances.' }}
          footer={
            data ? (
              <>
                <td className="px-3 py-2.5" colSpan={2}>
                  Total
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {formatMoney(data.total_debit)}
                </td>
                <td className="px-3 py-2.5 text-right tabular-nums">
                  {formatMoney(data.total_credit)}
                </td>
              </>
            ) : undefined
          }
        />
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profit & loss
// ---------------------------------------------------------------------------
function ProfitAndLossReport() {
  // The range is a control now, and the fiscal-year start comes from the server rather
  // than a hardcoded April - which was wrong for any organization on a January year and
  // duplicated a rule the backend already owns.
  const { range, control } = useReportRange();

  const { data, isLoading } = useQuery({
    queryKey: ['pnl', range],
    queryFn: () => accountingApi.profitAndLoss(range),
  });

  if (isLoading || !data) {
    return (
      <div className="space-y-4">
        <Card>
          <CardHeader title="Profit & loss" action={control} />
        </Card>
        <Card>
          <DataTable columns={[]} rows={[]} rowKey={() => ''} isLoading />
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Revenue" value={data.total_income} tone="success" icon={TrendingUp} />
        <StatTile label="Gross profit" value={data.gross_profit} tone="info" icon={Scale} />
        <StatTile
          label="Net profit"
          value={data.net_profit}
          tone={data.net_profit.startsWith('-') ? 'danger' : 'success'}
          icon={BookOpen}
        />
      </div>

      <Card>
        <CardHeader
          title="Profit & loss"
          description={`${formatDate(data.from_date)} to ${formatDate(data.to_date)}`}
          action={control}
        />
        <CardBody className="space-y-5">
          <ReportSection title="Income" lines={data.income} total={data.total_income} />
          <ReportSection title="Expenses" lines={data.expenses} total={data.total_expenses} />
          <div className="border-border flex items-center justify-between border-t pt-3">
            <span className="text-content text-[14px] font-semibold">Net profit</span>
            <span className="text-content text-[15px] font-semibold tabular-nums">
              {formatMoney(data.net_profit)}
            </span>
          </div>
        </CardBody>
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Balance sheet
// ---------------------------------------------------------------------------
function BalanceSheetReport() {
  const { data, isLoading } = useQuery({
    queryKey: ['balance-sheet'],
    queryFn: () => accountingApi.balanceSheet(),
  });

  if (isLoading || !data) {
    return (
      <Card>
        <DataTable columns={[]} rows={[]} rowKey={() => ''} isLoading />
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title="Balance sheet"
        description={`As at ${formatDate(data.as_of)}`}
        action={
          <Badge tone={data.is_balanced ? 'success' : 'danger'} dot>
            {data.is_balanced ? 'Balanced' : 'Out of balance'}
          </Badge>
        }
      />
      <CardBody className="space-y-5">
        <ReportSection title="Assets" lines={data.assets} total={data.total_assets} />
        <ReportSection
          title="Liabilities"
          lines={data.liabilities}
          total={data.total_liabilities}
        />
        <ReportSection title="Equity" lines={data.equity} total={data.total_equity} />

        <div className="border-border flex items-center justify-between border-t pt-3">
          <span className="text-content text-[14px] font-semibold">Liabilities + equity</span>
          <span className="text-content text-[15px] font-semibold tabular-nums">
            {formatMoney(
              // Displayed for the reader to check against total assets. The
              // authoritative check is `is_balanced`, computed server-side.
              data.total_assets,
            )}
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Shared report pieces
// ---------------------------------------------------------------------------
function ReportSection({
  title,
  lines,
  total,
}: {
  title: string;
  lines: ReportLine[];
  total: string;
}) {
  return (
    <div>
      <p className="text-content-muted mb-1.5 text-[11px] font-semibold tracking-wider uppercase">
        {title}
      </p>
      {lines.length === 0 ? (
        <p className="text-content-muted py-1 text-[13px]">Nothing to report</p>
      ) : (
        <div className="space-y-0.5">
          {lines.map((line) => (
            <div
              key={`${line.account_code ?? ''}-${line.label}`}
              className="flex items-center justify-between py-1 text-[13px]"
              style={{ paddingLeft: `${(line.level - 1) * 12}px` }}
            >
              <span className="text-content-secondary">
                {line.account_code && (
                  <span className="text-content-muted mr-2 font-mono text-[11px]">
                    {line.account_code}
                  </span>
                )}
                {line.label}
              </span>
              <span className="text-content tabular-nums">{formatMoney(line.amount)}</span>
            </div>
          ))}
        </div>
      )}
      <div className="border-border/60 mt-1.5 flex items-center justify-between border-t pt-1.5 text-[13px] font-medium">
        <span className="text-content">Total {title.toLowerCase()}</span>
        <span className="text-content tabular-nums">{formatMoney(total)}</span>
      </div>
    </div>
  );
}

function StatTile({
  label,
  value,
  tone,
  icon: Icon,
}: {
  label: string;
  value: string;
  tone: BadgeTone;
  icon: LucideIcon;
}) {
  const toneClass: Record<string, string> = {
    success: 'text-success',
    danger: 'text-danger',
    info: 'text-info',
    primary: 'text-primary',
    warning: 'text-warning',
    neutral: 'text-content',
  };
  return (
    <Card>
      <CardBody>
        <div className="flex items-center gap-2">
          <Icon className={cn('h-3.5 w-3.5', toneClass[tone])} aria-hidden />
          <p className="text-content-muted text-[11px] font-semibold tracking-wider uppercase">
            {label}
          </p>
        </div>
        <p className="text-content mt-1.5 text-[20px] font-semibold tabular-nums">
          {formatMoney(value)}
        </p>
      </CardBody>
    </Card>
  );
}
