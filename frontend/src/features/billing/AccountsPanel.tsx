/**
 * Accounts and cards - where money sits, and what it moves through.
 *
 * Split out of `BillingPage` because it answers a different question. That screen is the
 * fast path for recording a movement; this is the occasional bit of setup that makes the
 * pickers on it useful. Someone opens it when a new card arrives, not six times a day.
 *
 * Two things here are worth knowing before changing anything:
 *
 * 1. **A card number is typed, sent once, and gone.** It lives in a `useState` for as
 *    long as the form is open and is cleared the moment the request succeeds. The response
 *    has no field for it, nothing caches it, and `autoComplete` is off so the browser is
 *    not invited to keep it either. Only the network and the last four digits come back.
 * 2. **A credit card is a liability, not a place you have money.** It shows in the "paid
 *    from" picker because you genuinely can pay with it, but it is never totalled beside a
 *    bank balance, because the number means the opposite thing.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ArrowLeftRight, CreditCard, Landmark, RotateCcw, Wallet } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';

import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card as UICard, CardBody, CardHeader } from '@/components/ui/Card';
import { InfoTip } from '@/components/ui/InfoTip';
import { Input } from '@/components/ui/Input';
import { NumberInput } from '@/components/ui/NumberInput';
import { Select } from '@/components/ui/Select';
import { transferableAccounts } from '@/features/billing/accountPicker';
import {
  type BillingOptions,
  type Card,
  type CardKind,
  type CardNetwork,
  type MoneyAccount,
  billingApi,
} from '@/features/billing/api';
import { ApiError } from '@/lib/api';
import { cn } from '@/lib/cn';
import { formatMoney } from '@/lib/format';

const NETWORK_LABELS: Record<CardNetwork, string> = {
  visa: 'Visa',
  mastercard: 'Mastercard',
  rupay: 'RuPay',
  amex: 'Amex',
  discover: 'Discover',
  diners: 'Diners Club',
  jcb: 'JCB',
  maestro: 'Maestro',
  // Not "Unknown": the card works perfectly well, the software just does not claim to
  // recognise the scheme from its leading digits.
  other: 'Card',
};

// ---------------------------------------------------------------------------
// Transfer
// ---------------------------------------------------------------------------

/**
 * Move money between two of your own accounts.
 *
 * **There is no category field, and that is not an omission.** Moving your own money is
 * neither earning it nor spending it, so there is no income or expense line for it to go
 * against - which is also why a transfer is left out of the money-in and money-out totals.
 * Counting one would show income that never came from anywhere and an expense that bought
 * nothing.
 */
export function TransferForm({
  options,
  onClose,
}: {
  options: BillingOptions;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const accounts = transferableAccounts(options.money_accounts);

  const [fromId, setFromId] = useState(
    accounts.find((account) => account.is_default)?.id ?? accounts[0]?.id ?? '',
  );
  const [toId, setToId] = useState('');
  const [amount, setAmount] = useState('');
  const [entryDate, setEntryDate] = useState(options.today);
  const [description, setDescription] = useState('');

  const transfer = useMutation({
    mutationFn: () =>
      billingApi.transfer({
        from_account_id: fromId,
        to_account_id: toId,
        amount,
        entry_date: entryDate,
        ...(description.trim() ? { description: description.trim() } : {}),
      }),
    onSuccess: (result) => {
      // The ledger changed, so every balance derived from it is stale - but the day book
      // and its totals are not, because a transfer is deliberately excluded from both.
      void queryClient.invalidateQueries({ queryKey: ['analytics-dashboard'] });
      void queryClient.invalidateQueries({ queryKey: ['trial-balance'] });
      void queryClient.invalidateQueries({ queryKey: ['accounts'] });

      toast.success(`Moved ${formatMoney(result.amount, options.currency)}`, {
        description: `${result.from_account_name} → ${result.to_account_name}`,
      });

      setAmount('');
      setDescription('');
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not make the transfer'),
  });

  const parsed = Number(amount);
  const sameAccount = fromId !== '' && fromId === toId;
  const canSave =
    fromId !== '' && toId !== '' && !sameAccount && Number.isFinite(parsed) && parsed > 0;

  const accountOptions = accounts.map((account) => ({ value: account.id, label: account.name }));

  return (
    <UICard className="mb-4">
      <CardHeader
        title="Move money between accounts"
        description="A transfer is not income or an expense, so it does not appear in your money-in and money-out totals."
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
            if (canSave) transfer.mutate();
          }}
        >
          <div className="grid items-end gap-3 sm:grid-cols-[1fr_auto_1fr]">
            <Select
              label="From"
              value={fromId}
              onChange={(event) => setFromId(event.target.value)}
              options={accountOptions}
              hint="The account the money leaves."
            />
            <span className="text-content-muted hidden pb-2.5 sm:block" aria-hidden title="to">
              <ArrowLeftRight className="h-4 w-4" />
            </span>
            <Select
              label="To"
              value={toId}
              onChange={(event) => setToId(event.target.value)}
              options={accountOptions}
              placeholder="Choose an account"
              error={sameAccount ? 'Pick a different account.' : undefined}
              hint="The account it arrives in. Paying off a credit card goes here."
            />
          </div>

          <div className="grid gap-3 sm:grid-cols-[9rem_10rem_1fr]">
            <NumberInput
              label="Amount"
              required
              autoFocus
              placeholder="0.00"
              value={amount}
              onValueChange={setAmount}
              className="text-[15px] tabular-nums"
            />
            <Input
              label="Date"
              type="date"
              value={entryDate}
              max={options.today}
              onChange={(event) => setEntryDate(event.target.value)}
            />
            <Input
              label="Note"
              placeholder="Cash deposited at branch"
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              hint="Optional - left blank, the ledger names both accounts."
            />
          </div>

          <div className="border-border flex items-center justify-between gap-3 border-t pt-3">
            <p className="text-content-muted text-[12px]">
              Posts to your books as one entry against both accounts.
            </p>
            <Button type="submit" disabled={!canSave || transfer.isPending}>
              {transfer.isPending ? 'Moving…' : 'Move money'}
            </Button>
          </div>
        </form>
      </CardBody>
    </UICard>
  );
}

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

/**
 * Everything registered, and the forms to add to it.
 *
 * Placed below the day book on purpose: it is setup, and the screen's job is recording.
 */
export function AccountsPanel({ options }: { options: BillingOptions }) {
  const [showArchived, setShowArchived] = useState(false);
  const [addingCard, setAddingCard] = useState(false);

  // Archived cards are fetched separately rather than folded into `billing-options`,
  // because that payload feeds the pickers and an archived card must never reach one.
  const { data: cards } = useQuery({
    queryKey: ['billing-cards', showArchived],
    queryFn: () => billingApi.cards(showArchived ? { include_archived: true } : undefined),
  });

  const listed = cards ?? options.cards;
  const accounts = transferableAccounts(options.money_accounts).filter(
    (account) => !account.card_id,
  );
  const banks = accounts.filter((account) => account.kind === 'bank');

  return (
    <UICard className="mt-4">
      <CardHeader
        title="Accounts & cards"
        description="Where your money sits, and the cards you spend on. These are the choices offered when recording a payment."
        action={
          <Button variant="secondary" onClick={() => setAddingCard((open) => !open)}>
            {addingCard ? 'Close' : 'Add a card'}
          </Button>
        }
      />
      <CardBody className="space-y-5">
        {addingCard && (
          <AddCardForm
            banks={banks}
            onCancel={() => setAddingCard(false)}
            onAdded={() => setAddingCard(false)}
          />
        )}

        <section>
          <h3 className="text-content-secondary mb-2 text-[13px] font-medium">Cash & bank</h3>
          <ul className="divide-border divide-y">
            {accounts.map((account) => (
              <li key={account.id} className="flex items-center gap-3 py-2.5">
                <span className="text-content-muted shrink-0" aria-hidden>
                  {account.kind === 'cash' ? (
                    <Wallet className="h-4 w-4" />
                  ) : (
                    <Landmark className="h-4 w-4" />
                  )}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="text-content block truncate text-[13px]">{account.name}</span>
                  <span className="text-content-muted block text-[11px]">{account.code}</span>
                </span>
                {account.is_default && <Badge tone="primary">Default</Badge>}
              </li>
            ))}
          </ul>
        </section>

        <section>
          <div className="mb-2 flex items-center justify-between gap-2">
            <h3 className="text-content-secondary flex items-center gap-1.5 text-[13px] font-medium">
              Cards
              <InfoTip label="Cards">
                <p>
                  Only the card network and the last four digits are stored. The number you type is
                  used to work those out and is never saved.
                </p>
                <p className="mt-2">
                  A credit card is a liability, so what you spend on it is money you owe - it is
                  never added to your cash and bank balance.
                </p>
              </InfoTip>
            </h3>
            <button
              type="button"
              onClick={() => setShowArchived((shown) => !shown)}
              className="text-content-muted hover:text-content text-[12px]"
            >
              {showArchived ? 'Hide archived' : 'Show archived'}
            </button>
          </div>

          {listed.length === 0 ? (
            <p className="text-content-muted py-2 text-[13px]">
              No cards yet. Add one to record what you spend on it.
            </p>
          ) : (
            <ul className="divide-border divide-y">
              {listed.map((card) => (
                <CardRow key={card.id} card={card} />
              ))}
            </ul>
          )}
        </section>
      </CardBody>
    </UICard>
  );
}

function CardRow({ card }: { card: Card }) {
  const queryClient = useQueryClient();

  const toggle = useMutation({
    mutationFn: () =>
      card.is_active ? billingApi.archiveCard(card.id) : billingApi.restoreCard(card.id),
    onSuccess: (updated) => {
      void queryClient.invalidateQueries({ queryKey: ['billing-cards'] });
      // The pickers come from this payload, and an archived card must leave them.
      void queryClient.invalidateQueries({ queryKey: ['billing-options'] });
      toast.success(updated.is_active ? `Restored ${updated.label}` : `Archived ${updated.label}`, {
        description: updated.is_active
          ? 'It can be chosen when recording a payment again.'
          : 'Past entries still name it; it is no longer offered.',
      });
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not update the card'),
  });

  return (
    <li className={cn('flex items-center gap-3 py-2.5', !card.is_active && 'opacity-60')}>
      <span className="text-content-muted shrink-0" aria-hidden>
        <CreditCard className="h-4 w-4" />
      </span>
      <span className="min-w-0 flex-1">
        <span className="text-content block truncate text-[13px]">
          {card.label} <span className="text-content-muted tabular-nums">··{card.last4}</span>
        </span>
        <span className="text-content-muted block text-[11px]">
          {NETWORK_LABELS[card.network]} · {card.account_name}
        </span>
      </span>
      <Badge tone={card.kind === 'credit' ? 'warning' : 'info'}>
        {card.kind === 'credit' ? 'Credit' : 'Debit'}
      </Badge>
      <button
        type="button"
        disabled={toggle.isPending}
        onClick={() => toggle.mutate()}
        title={card.is_active ? 'Archive this card' : 'Restore this card'}
        className="text-content-muted hover:text-content text-[12px] disabled:opacity-40"
      >
        {card.is_active ? (
          <>
            <span aria-hidden>Archive</span>
            <span className="sr-only">Archive {card.label}</span>
          </>
        ) : (
          <>
            <RotateCcw className="h-3.5 w-3.5" aria-hidden />
            <span className="sr-only">Restore {card.label}</span>
          </>
        )}
      </button>
    </li>
  );
}

/**
 * The Luhn check digit, so a typo is caught before a round trip.
 *
 * A duplicate of the server's check, and deliberately so: the server remains the
 * authority, this only saves someone a request to be told they mistyped one digit. Safe to
 * duplicate because Luhn is a fixed algorithm that cannot drift - unlike the network
 * detection, which is a table of issuer ranges and is left entirely to the server.
 */
function passesLuhn(digits: string): boolean {
  if (!/^\d+$/.test(digits)) return false;
  let total = 0;
  const parity = digits.length % 2;
  for (let index = 0; index < digits.length; index += 1) {
    let value = Number(digits[index]);
    if (index % 2 === parity) {
      value *= 2;
      if (value > 9) value -= 9;
    }
    total += value;
  }
  return total % 10 === 0;
}

/**
 * Register a card from its number.
 *
 * **The number is never stored, here or on the server.** It is held in state while the
 * form is open, sent once, and cleared on success. `autoComplete="off"` keeps the browser
 * from offering to remember it, which is the one place a "helpful" default would undo the
 * whole arrangement.
 */
function AddCardForm({
  banks,
  onCancel,
  onAdded,
}: {
  banks: MoneyAccount[];
  onCancel: () => void;
  onAdded: () => void;
}) {
  const queryClient = useQueryClient();
  const [label, setLabel] = useState('');
  const [kind, setKind] = useState<CardKind>('credit');
  const [number, setNumber] = useState('');
  const [bankId, setBankId] = useState(banks[0]?.id ?? '');

  const digits = number.replace(/[\s-]/g, '');
  const longEnough = digits.length >= 12;
  const numberLooksWrong = longEnough && !passesLuhn(digits);

  const add = useMutation({
    mutationFn: () =>
      billingApi.addCard({
        label: label.trim(),
        kind,
        card_number: number,
        ...(kind === 'debit' && bankId ? { bank_account_id: bankId } : {}),
      }),
    onSuccess: (card) => {
      // Cleared first, before anything can await: the number has done its only job.
      setNumber('');
      setLabel('');

      void queryClient.invalidateQueries({ queryKey: ['billing-cards'] });
      void queryClient.invalidateQueries({ queryKey: ['billing-options'] });
      // A credit card creates a liability account, so the chart of accounts has changed.
      void queryClient.invalidateQueries({ queryKey: ['accounts'] });
      void queryClient.invalidateQueries({ queryKey: ['trial-balance'] });

      toast.success(`Added ${card.label} ··${card.last4}`, {
        description:
          card.kind === 'credit'
            ? `${NETWORK_LABELS[card.network]} credit card. What you spend on it is recorded as money owed.`
            : `${NETWORK_LABELS[card.network]} debit card on ${card.account_name}.`,
      });
      onAdded();
    },
    onError: (error) =>
      toast.error(error instanceof ApiError ? error.message : 'Could not add the card'),
  });

  const needsBank = kind === 'debit';
  const canSave =
    label.trim() !== '' && longEnough && !numberLooksWrong && (!needsBank || bankId !== '');

  return (
    <form
      className="border-border bg-surface-sunken/50 space-y-3 rounded-lg border border-dashed p-3"
      onSubmit={(event) => {
        event.preventDefault();
        if (canSave) add.mutate();
      }}
    >
      <div className="grid gap-3 sm:grid-cols-[1fr_11rem]">
        <Input
          label="Name this card"
          autoFocus
          required
          placeholder="HDFC Millennia"
          value={label}
          onChange={(event) => setLabel(event.target.value)}
          hint="How you refer to it. Shown with the last four digits."
        />
        <Select
          label="Kind"
          value={kind}
          onChange={(event) => setKind(event.target.value as CardKind)}
          options={[
            { value: 'credit', label: 'Credit card' },
            { value: 'debit', label: 'Debit card' },
          ]}
          hint={
            kind === 'credit'
              ? 'Spending on it is money you owe.'
              : 'Spends from a bank account you already have.'
          }
        />
      </div>

      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label="Card number"
          required
          /* Off, not "cc-number". The browser filling or storing a card number is exactly
             what this design avoids - nothing here keeps one, so nothing should offer to. */
          autoComplete="off"
          inputMode="numeric"
          placeholder="0000 0000 0000 0000"
          value={number}
          onChange={(event) => setNumber(event.target.value)}
          className="tabular-nums"
          error={numberLooksWrong ? 'Check that number - a digit looks wrong.' : undefined}
          hint="Only the network and the last four digits are kept. The number itself is never stored."
        />
        {needsBank && (
          <Select
            label="Draws on"
            value={bankId}
            onChange={(event) => setBankId(event.target.value)}
            options={banks.map((account) => ({ value: account.id, label: account.name }))}
            placeholder={banks.length === 0 ? 'No bank accounts yet' : undefined}
            hint="A debit card spends from an account you already have, so it gets no account of its own."
            error={banks.length === 0 ? 'Add a bank account first.' : undefined}
          />
        )}
      </div>

      <div className="flex flex-wrap items-center justify-end gap-2">
        <Button type="button" variant="ghost" onClick={onCancel} disabled={add.isPending}>
          Cancel
        </Button>
        <Button type="submit" disabled={!canSave || add.isPending}>
          {add.isPending ? 'Adding…' : 'Add card'}
        </Button>
      </div>
    </form>
  );
}
