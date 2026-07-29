/**
 * Billing API client — money in and money out.
 *
 * Amounts are `string`, as everywhere else: a JSON number is an IEEE-754 double in
 * JavaScript, and these figures post to the ledger.
 */
import { api } from '@/lib/api';
import type { Money, Page, PageQuery } from '@/features/accounting/api';

export type Direction = 'in' | 'out';

export interface Category {
  id: string;
  code: string;
  name: string;
  /** Income categories cannot take money out, and vice versa. */
  direction: Direction;
  /** The parent group's name, used for `optgroup` — nearly eighty flat options is
   *  a list nobody reads to the end of. */
  group: string;
  is_default: boolean;
}

export interface MoneyAccount {
  id: string;
  code: string;
  name: string;
  is_default: boolean;
}

export interface BillingOptions {
  categories: Category[];
  money_accounts: MoneyAccount[];
  /** Today in the organization's timezone, not the server's UTC date. */
  today: string;
  currency: string;
}

export interface BillingEntry {
  id: string;
  /** The ledger's own number, so the entry can be found in the journal. */
  entry_number: string | null;
  date: string;
  direction: Direction;
  amount: Money;
  description: string;
  reference: string | null;
  /** Who it came from (money in) or went to (money out). Free text, not a record. */
  party: string | null;

  category_id: string;
  category_name: string;
  money_account_id: string;
  money_account_name: string;

  created_at: string;
  /** Cancelled by a reversal. Still listed — the cancellation is part of the record. */
  is_reversed: boolean;
}

export interface BillingSummary {
  from_date: string;
  to_date: string;
  money_in: Money;
  money_out: Money;
  net: Money;
  entry_count: number;
}

export interface RecordEntryBody {
  direction: Direction;
  amount: Money;
  description: string;
  entry_date?: string;
  category_id?: string;
  money_account_id?: string;
  reference?: string;
  party?: string;
}

export const billingApi = {
  options: () => api.get<BillingOptions>('/billing/options'),

  list: (
    params?: PageQuery & {
      direction?: Direction;
      from_date?: string;
      to_date?: string;
      q?: string;
    },
  ) => api.get<Page<BillingEntry>>('/billing', { params }),

  summary: (params?: { from_date?: string; to_date?: string }) =>
    api.get<BillingSummary>('/billing/summary', { params }),

  record: (body: RecordEntryBody) => api.post<BillingEntry>('/billing', body),

  /**
   * Add a category from a name alone. The account code, parent group, and subtype are
   * derived server-side — nobody should need to understand the chart of accounts to
   * file a payment under a name the built-in list does not have.
   */
  createCategory: (name: string, direction: Direction) =>
    api.post<Category>('/billing/categories', { name, direction }),

  /**
   * Cancel an entry by posting its mirror image. There is no delete and no edit —
   * a posted ledger entry is immutable, so an opposite entry is the only honest undo.
   */
  reverse: (id: string, reason?: string) =>
    api.post<BillingEntry>(`/billing/${id}/reverse`, reason ? { reason } : {}),
};
