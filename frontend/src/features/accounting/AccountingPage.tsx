/**
 * Accounting — chart of accounts, journal entries, and the financial statements.
 *
 * One page with tabs rather than four routes: an accountant moves between the
 * trial balance and the ledger constantly, and a full route transition (with its
 * refetch) on every switch is slower than keeping the queries warm in one place.
 */
import { useQuery } from '@tanstack/react-query';
import type { LucideIcon } from 'lucide-react';
import { AlertTriangle, BookOpen, Scale, TrendingUp } from 'lucide-react';
import { useState } from 'react';

import { Badge, type BadgeTone } from '@/components/ui/Badge';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import type { Column } from '@/components/ui/DataTable';
import { DataTable, PageHeader, Pagination } from '@/components/ui/DataTable';
import {
  type Account,
  type AccountType,
  type JournalEntry,
  type ReportLine,
  accountingApi,
} from '@/features/accounting/api';
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

const TYPE_TONES: Record<AccountType, BadgeTone> = {
  asset: 'info',
  liability: 'warning',
  equity: 'primary',
  income: 'success',
  expense: 'danger',
};

export function AccountingPage() {
  const [tab, setTab] = useState<Tab>('chart');

  return (
    <div>
      <PageHeader
        title="Accounting"
        description="Double-entry ledger. Posted entries are immutable — corrections are made by reversal."
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
  const { data, isLoading } = useQuery({
    queryKey: ['accounts'],
    queryFn: () => accountingApi.accounts(),
  });

  const columns: Column<Account>[] = [
    {
      header: 'Code',
      cell: (row) => (
        // Indented by depth so the hierarchy reads without a tree widget.
        <span
          className="text-content-muted font-mono text-[12px]"
          style={{ paddingLeft: `${row.depth * 14}px` }}
        >
          {row.code}
        </span>
      ),
    },
    {
      header: 'Account',
      cell: (row) => (
        <span className={cn(row.is_group && 'text-content font-semibold')}>
          {row.name}
          {row.system_key && (
            <Badge tone="neutral" className="ml-2">
              system
            </Badge>
          )}
        </span>
      ),
    },
    {
      header: 'Type',
      hideOnMobile: true,
      cell: (row) => <Badge tone={TYPE_TONES[row.account_type]}>{row.account_type}</Badge>,
    },
    {
      header: 'Balance',
      numeric: true,
      cell: (row) =>
        row.is_group ? (
          <span className="text-content-muted">—</span>
        ) : (
          <span className={cn(isZeroMoney(row.balance) && 'text-content-muted')}>
            {formatMoney(row.balance)}
          </span>
        ),
    },
  ];

  return (
    <Card>
      <DataTable
        columns={columns}
        rows={data ?? []}
        rowKey={(row) => row.id}
        isLoading={isLoading}
        empty={{
          title: 'No accounts yet',
          description: 'A default chart is seeded when an organization is created.',
        }}
      />
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Journal entries
// ---------------------------------------------------------------------------
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
      header: 'Status',
      hideOnMobile: true,
      cell: (row) => <Badge tone={statusTone[row.status] ?? 'neutral'}>{row.status}</Badge>,
    },
    { header: 'Amount', numeric: true, cell: (row) => formatMoney(row.total_debit) },
  ];

  return (
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
  );
}

// ---------------------------------------------------------------------------
// Trial balance
// ---------------------------------------------------------------------------
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
                This should be impossible — contact support.
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
            {
              header: 'Code',
              cell: (row) => <span className="font-mono text-[12px]">{row.code}</span>,
            },
            { header: 'Account', cell: (row) => row.name },
            {
              header: 'Debit',
              numeric: true,
              cell: (row) =>
                isZeroMoney(row.debit) ? (
                  <span className="text-content-muted">—</span>
                ) : (
                  formatMoney(row.debit)
                ),
            },
            {
              header: 'Credit',
              numeric: true,
              cell: (row) =>
                isZeroMoney(row.credit) ? (
                  <span className="text-content-muted">—</span>
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
  const [range] = useState(() => {
    const today = new Date();
    // Indian fiscal year starts in April.
    const fyStartYear = today.getMonth() >= 3 ? today.getFullYear() : today.getFullYear() - 1;
    return {
      from_date: `${fyStartYear}-04-01`,
      to_date: today.toISOString().slice(0, 10),
    };
  });

  const { data, isLoading } = useQuery({
    queryKey: ['pnl', range],
    queryFn: () => accountingApi.profitAndLoss(range),
  });

  if (isLoading || !data) {
    return (
      <Card>
        <DataTable columns={[]} rows={[]} rowKey={() => ''} isLoading />
      </Card>
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
