/**
 * Billing — the fast path for recording money.
 *
 * This is the screen most users will only ever open, so the design target is
 * **seconds, not minutes**: two buttons, an amount, a note, done. The date defaults to
 * today, the category and the cash account default to sensible choices, and the amount
 * field takes focus so the whole entry is typeable without touching the mouse.
 *
 * The form stays open after saving. Someone catching up on a week of receipts enters
 * six things in a row, and closing after each one would make them click "Money out"
 * six times.
 *
 * Every entry posts real double-entry to the ledger, which is why the figures show up
 * on the dashboard, in the P&L, and in the analytics trend without anything else being
 * wired up.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowDownLeft, ArrowUpRight, Plus, Undo2, Wallet } from 'lucide-react';
import { useRef, useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardBody, CardHeader } from '@/components/ui/Card';
import type { Column } from '@/components/ui/DataTable';
import { DataTable, PageHeader, Pagination } from '@/components/ui/DataTable';
import { Input } from '@/components/ui/Input';
import {
  type BillingEntry,
  type BillingOptions,
  type Direction,
  billingApi,
} from '@/features/billing/api';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatDate, formatMoney } from '@/lib/format';

export function BillingPage() {
  const [composing, setComposing] = useState<Direction | null>(null);
  const [page, setPage] = useState(1);
  const [filter, setFilter] = useState<Direction | 'all'>('all');
  const [search, setSearch] = useState('');

  const { data: options } = useQuery({
    queryKey: ['billing-options'],
    queryFn: () => billingApi.options(),
  });

  const { data: summary } = useQuery({
    queryKey: ['billing-summary'],
    queryFn: () => billingApi.summary(),
  });

  const { data: entries, isLoading } = useQuery({
    queryKey: ['billing-entries', page, filter, search],
    queryFn: () =>
      billingApi.list({
        page,
        page_size: 25,
        ...(filter === 'all' ? {} : { direction: filter }),
        ...(search ? { q: search } : {}),
      }),
  });

  const currency = options?.currency ?? 'INR';

  return (
    <div>
      <PageHeader
        title="Billing"
        description="Record money coming in and going out. Each entry posts straight to your books, so the dashboard and reports update immediately."
      />

      {/* The two actions, given the prominence they deserve — this is the reason the
          screen exists, not a toolbar afterthought. */}
      <div className="mb-4 grid gap-3 sm:grid-cols-2">
        <DirectionButton
          direction="in"
          active={composing === 'in'}
          onClick={() => setComposing(composing === 'in' ? null : 'in')}
        />
        <DirectionButton
          direction="out"
          active={composing === 'out'}
          onClick={() => setComposing(composing === 'out' ? null : 'out')}
        />
      </div>

      {composing && options && (
        <EntryForm
          /* Remounting on direction change is what keeps the category selection
             correct. Switching from money-out to money-in changes which categories are
             valid, and syncing that with an effect is the "you might not need an
             effect" anti-pattern — a fresh mount just initialises it right. */
          key={composing}
          direction={composing}
          options={options}
          onClose={() => setComposing(null)}
        />
      )}

      {/* ---- Totals ---- */}
      <div className="mb-4 grid gap-3 sm:grid-cols-3">
        <TotalTile
          label="Money in"
          value={summary ? formatMoney(summary.money_in, currency) : undefined}
          tone="in"
        />
        <TotalTile
          label="Money out"
          value={summary ? formatMoney(summary.money_out, currency) : undefined}
          tone="out"
        />
        <TotalTile
          label="Net"
          value={summary ? formatMoney(summary.net, currency) : undefined}
          tone="net"
          hint={
            summary
              ? `${summary.entry_count} ${summary.entry_count === 1 ? 'entry' : 'entries'} · ${formatDate(summary.from_date)} to ${formatDate(summary.to_date)}`
              : undefined
          }
        />
      </div>

      <EntryList
        entries={entries}
        isLoading={isLoading}
        currency={currency}
        filter={filter}
        onFilter={(next) => {
          setFilter(next);
          setPage(1);
        }}
        search={search}
        onSearch={(next) => {
          setSearch(next);
          setPage(1);
        }}
        onPage={setPage}
      />
    </div>
  );
}

// ---------------------------------------------------------------------------
// The two buttons
// ---------------------------------------------------------------------------
function DirectionButton({
  direction,
  active,
  onClick,
}: {
  direction: Direction;
  active: boolean;
  onClick: () => void;
}) {
  const isIn = direction === 'in';
  const Icon = isIn ? ArrowDownLeft : ArrowUpRight;

  return (
    <button
      type="button"
      onClick={onClick}
      aria-expanded={active}
      className={cn(
        'flex items-center gap-3 rounded-xl border p-4 text-left transition-colors',
        isIn
          ? 'border-success/30 bg-success-bg hover:border-success/60'
          : 'border-danger/30 bg-danger-bg hover:border-danger/60',
        active &&
          (isIn ? 'border-success ring-success/20 ring-2' : 'border-danger ring-danger/20 ring-2'),
      )}
    >
      <span
        className={cn(
          'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg',
          isIn ? 'bg-success/15 text-success' : 'bg-danger/15 text-danger',
        )}
        aria-hidden
      >
        <Icon className="h-4.5 w-4.5" />
      </span>
      <span className="min-w-0">
        <span className="text-content block text-[14px] font-semibold">
          {isIn ? 'Money in' : 'Money out'}
        </span>
        <span className="text-content-muted block text-[12px]">
          {isIn ? 'A sale, a receipt, money received' : 'A bill, an expense, money paid'}
        </span>
      </span>
      <Plus className="text-content-muted ml-auto h-4 w-4 shrink-0" aria-hidden />
    </button>
  );
}

// ---------------------------------------------------------------------------
// The form
// ---------------------------------------------------------------------------
function EntryForm({
  direction,
  options,
  onClose,
}: {
  direction: Direction;
  options: BillingOptions;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const amountRef = useRef<HTMLInputElement>(null);

  const relevant = options.categories.filter((category) => category.direction === direction);
  const defaultCategory = relevant.find((category) => category.is_default) ?? relevant[0];
  const defaultAccount =
    options.money_accounts.find((account) => account.is_default) ?? options.money_accounts[0];

  const [amount, setAmount] = useState('');
  const [description, setDescription] = useState('');
  const [entryDate, setEntryDate] = useState(options.today);
  const [categoryId, setCategoryId] = useState(defaultCategory?.id ?? '');
  const [accountId, setAccountId] = useState(defaultAccount?.id ?? '');

  const record = useMutation({
    mutationFn: () =>
      billingApi.record({
        direction,
        amount,
        description: description.trim(),
        entry_date: entryDate,
        ...(categoryId ? { category_id: categoryId } : {}),
        ...(accountId ? { money_account_id: accountId } : {}),
      }),
    onSuccess: (entry) => {
      void queryClient.invalidateQueries({ queryKey: ['billing-entries'] });
      void queryClient.invalidateQueries({ queryKey: ['billing-summary'] });
      // The figures on the dashboard and analytics come from the ledger this just
      // wrote to, so their caches are stale the moment this succeeds.
      void queryClient.invalidateQueries({ queryKey: ['analytics-dashboard'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics-trend'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics-control-checks'] });
      void queryClient.invalidateQueries({ queryKey: ['trial-balance'] });

      toast.success(
        `${direction === 'in' ? 'Received' : 'Paid'} ${formatMoney(entry.amount, options.currency)}`,
        { description: `${entry.description} · ${entry.category_name}` },
      );

      // Kept open, with the amount and note cleared and the date retained: someone
      // catching up on a week of receipts enters several in a row on the same day.
      setAmount('');
      setDescription('');
      amountRef.current?.focus();
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not save the entry'),
  });

  const parsed = Number(amount);
  const canSave =
    amount !== '' && Number.isFinite(parsed) && parsed > 0 && description.trim() !== '';

  return (
    <Card className="mb-4">
      <CardHeader
        title={direction === 'in' ? 'Record money in' : 'Record money out'}
        description="The date, category, and account are pre-filled. Only the amount and a note are needed."
        action={
          <Button variant="ghost" onClick={onClose}>
            Close
          </Button>
        }
      />
      <CardBody>
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSave) record.mutate();
          }}
        >
          <div className="grid gap-3 sm:grid-cols-[9rem_1fr_10rem]">
            <Input
              ref={amountRef}
              label="Amount"
              required
              autoFocus
              inputMode="decimal"
              placeholder="0.00"
              value={amount}
              onChange={(event) => setAmount(event.target.value)}
              className="text-[15px] tabular-nums"
            />
            <Input
              label="What was it for?"
              required
              placeholder={direction === 'in' ? 'Counter sale' : 'Rent for August'}
              value={description}
              onChange={(event) => setDescription(event.target.value)}
            />
            <Input
              label="Date"
              type="date"
              value={entryDate}
              max={options.today}
              onChange={(event) => setEntryDate(event.target.value)}
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-2">
            <label className="block">
              <span className="text-content-secondary mb-1.5 block text-[13px] font-medium">
                Category
              </span>
              <select
                value={categoryId}
                onChange={(event) => setCategoryId(event.target.value)}
                className="border-border bg-surface text-content focus:border-primary w-full rounded-lg border px-3 py-2 text-[13px] outline-none"
              >
                {relevant.map((category) => (
                  <option key={category.id} value={category.id}>
                    {category.name}
                  </option>
                ))}
              </select>
            </label>

            <label className="block">
              <span className="text-content-secondary mb-1.5 block text-[13px] font-medium">
                {direction === 'in' ? 'Received into' : 'Paid from'}
              </span>
              <select
                value={accountId}
                onChange={(event) => setAccountId(event.target.value)}
                className="border-border bg-surface text-content focus:border-primary w-full rounded-lg border px-3 py-2 text-[13px] outline-none"
              >
                {options.money_accounts.map((account) => (
                  <option key={account.id} value={account.id}>
                    {account.name}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <div className="border-border flex items-center justify-between gap-3 border-t pt-3">
            <p className="text-content-muted text-[12px]">
              Saves to your books immediately. To correct a mistake, reverse the entry.
            </p>
            <Button type="submit" disabled={!canSave || record.isPending}>
              {record.isPending
                ? 'Saving…'
                : direction === 'in'
                  ? 'Record money in'
                  : 'Record money out'}
            </Button>
          </div>
        </form>
      </CardBody>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// The day book
// ---------------------------------------------------------------------------
function EntryList({
  entries,
  isLoading,
  currency,
  filter,
  onFilter,
  search,
  onSearch,
  onPage,
}: {
  entries:
    | { items: BillingEntry[]; meta: { page: number; total_pages: number; total_items: number } }
    | undefined;
  isLoading: boolean;
  currency: string;
  filter: Direction | 'all';
  onFilter: (next: Direction | 'all') => void;
  search: string;
  onSearch: (next: string) => void;
  onPage: (page: number) => void;
}) {
  const queryClient = useQueryClient();

  const reverse = useMutation({
    mutationFn: ({ id, reason }: { id: string; reason: string }) => billingApi.reverse(id, reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['billing-entries'] });
      void queryClient.invalidateQueries({ queryKey: ['billing-summary'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics-dashboard'] });
      void queryClient.invalidateQueries({ queryKey: ['analytics-trend'] });
      void queryClient.invalidateQueries({ queryKey: ['trial-balance'] });
      toast.success('Entry reversed', {
        description: 'The original stays on the record, cancelled by an opposite entry.',
      });
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not reverse the entry'),
  });

  const columns: Column<BillingEntry>[] = [
    {
      header: 'Date',
      cell: (row) => <span className="whitespace-nowrap">{formatDate(row.date)}</span>,
    },
    {
      header: 'Description',
      cell: (row) => (
        <div className="min-w-0">
          <p className={cn('text-content truncate', row.is_reversed && 'line-through opacity-60')}>
            {row.description}
          </p>
          <p className="text-content-muted text-[11px]">
            {row.category_name} · {row.money_account_name}
          </p>
        </div>
      ),
    },
    {
      header: 'In',
      numeric: true,
      cell: (row) =>
        row.direction === 'in' ? (
          <span
            className={cn('text-success font-medium', row.is_reversed && 'line-through opacity-60')}
          >
            {formatMoney(row.amount, currency)}
          </span>
        ) : (
          <span className="text-content-muted">—</span>
        ),
    },
    {
      header: 'Out',
      numeric: true,
      cell: (row) =>
        row.direction === 'out' ? (
          <span
            className={cn('text-danger font-medium', row.is_reversed && 'line-through opacity-60')}
          >
            {formatMoney(row.amount, currency)}
          </span>
        ) : (
          <span className="text-content-muted">—</span>
        ),
    },
    {
      header: '',
      cell: (row) =>
        row.is_reversed ? (
          <Badge tone="neutral">Reversed</Badge>
        ) : (
          <button
            type="button"
            title="Reverse this entry"
            disabled={reverse.isPending}
            onClick={() => {
              const reason = window.prompt(
                `Reverse "${row.description}"? The original stays on the record, cancelled by an opposite entry.\n\nReason (optional):`,
                '',
              );
              // `null` is Cancel; an empty string is "no reason given", which is fine.
              if (reason === null) return;
              reverse.mutate({ id: row.id, reason: reason.trim() });
            }}
            className="text-content-muted hover:text-danger text-[12px] disabled:opacity-40"
          >
            <Undo2 className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only">Reverse</span>
          </button>
        ),
    },
  ];

  return (
    <Card>
      <CardHeader
        title="Your entries"
        description="Newest first. Nothing is ever deleted — a correction is an opposite entry."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <div className="border-border flex overflow-hidden rounded-lg border">
              {(
                [
                  ['all', 'All'],
                  ['in', 'In'],
                  ['out', 'Out'],
                ] as [Direction | 'all', string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => onFilter(key)}
                  aria-pressed={filter === key}
                  className={cn(
                    'px-2.5 py-1.5 text-[12px] font-medium',
                    filter === key
                      ? 'bg-primary text-white'
                      : 'text-content-muted hover:bg-surface-sunken',
                  )}
                >
                  {label}
                </button>
              ))}
            </div>
            <Input
              placeholder="Search…"
              value={search}
              onChange={(event) => onSearch(event.target.value)}
              className="w-40"
            />
          </div>
        }
      />
      <DataTable
        columns={columns}
        rows={entries?.items ?? []}
        rowKey={(row) => row.id}
        isLoading={isLoading}
        empty={{
          title: 'Nothing recorded yet',
          description: 'Use the buttons above to record your first payment or receipt.',
        }}
      />
      {entries && (
        <Pagination
          page={entries.meta.page}
          totalPages={entries.meta.total_pages}
          totalItems={entries.meta.total_items}
          onChange={onPage}
        />
      )}
    </Card>
  );
}

function TotalTile({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string | undefined;
  tone: 'in' | 'out' | 'net';
  hint?: string | undefined;
}) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-content-muted text-[12px] font-medium">{label}</span>
        {tone === 'in' && <ArrowDownLeft className="text-success h-3.5 w-3.5" aria-hidden />}
        {tone === 'out' && <ArrowUpRight className="text-danger h-3.5 w-3.5" aria-hidden />}
        {tone === 'net' && <Wallet className="text-content-muted h-3.5 w-3.5" aria-hidden />}
      </div>
      <p
        className={cn(
          'mt-2 text-[20px] leading-none font-semibold tracking-[-0.02em] tabular-nums',
          tone === 'in' && 'text-success',
          tone === 'out' && 'text-danger',
          tone === 'net' && 'text-content',
        )}
      >
        {value ?? '—'}
      </p>
      {hint && <p className="text-content-muted mt-1.5 text-[11px]">{hint}</p>}
    </Card>
  );
}
