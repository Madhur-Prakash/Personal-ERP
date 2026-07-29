/**
 * Accounting, sales, and purchasing API client.
 *
 * **Money is a `string` in every type here, never a `number`.** The backend
 * serialises `Decimal` as a decimal string because a JSON number is an IEEE-754
 * double in JavaScript — `1234567.89` would arrive as `1234567.8899999999`.
 * Typing these as `number` would make TypeScript happily let `Number()` creep in.
 * Format with `formatMoney`, compare with `compareMoney`.
 */
import { api } from '@/lib/api';

// ---------------------------------------------------------------------------
// Shared
// ---------------------------------------------------------------------------
export interface Page<T> {
  items: T[];
  meta: {
    page: number;
    page_size: number;
    total_items: number;
    total_pages: number;
    has_next: boolean;
    has_previous: boolean;
  };
}

/** A money amount as it crosses the wire. Never widen this to `number`. */
export type Money = string;

export interface PageQuery {
  page?: number;
  page_size?: number;
}

// ---------------------------------------------------------------------------
// Accounting — chart of accounts
// ---------------------------------------------------------------------------
export type AccountType = 'asset' | 'liability' | 'equity' | 'income' | 'expense';

export interface Account {
  id: string;
  code: string;
  name: string;
  account_type: AccountType;
  subtype: string;
  parent_id: string | null;
  depth: number;
  is_group: boolean;
  is_active: boolean;
  is_system: boolean;
  system_key: string | null;
  description: string | null;
  normal_balance: 'debit' | 'credit';
  is_postable: boolean;
  total_debit: Money;
  total_credit: Money;
  balance: Money;
}

export interface Journal {
  id: string;
  code: string;
  name: string;
  journal_type: string;
  number_prefix: string;
  is_active: boolean;
}

export interface AccountingPeriod {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: 'open' | 'closed' | 'locked';
  accepts_postings: boolean;
}

export interface FiscalYear {
  id: string;
  name: string;
  start_date: string;
  end_date: string;
  status: string;
  periods: AccountingPeriod[];
}

// ---------------------------------------------------------------------------
// Accounting — journal entries
// ---------------------------------------------------------------------------
export type EntryStatus = 'draft' | 'posted' | 'reversed';

export interface JournalEntryLine {
  id: string;
  line_number: number;
  account_id: string;
  account_code: string;
  account_name: string;
  debit: Money;
  credit: Money;
  description: string | null;
}

export interface JournalEntry {
  id: string;
  journal_id: string;
  journal_code: string;
  entry_number: string | null;
  entry_date: string;
  narration: string;
  reference: string | null;
  status: EntryStatus;
  total_debit: Money;
  total_credit: Money;
  currency: string;
  posted_at: string | null;
  reversed_at: string | null;
  reverses_id: string | null;
  source_type: string | null;
  lines: JournalEntryLine[];
}

export interface JournalEntryLineInput {
  account_id: string;
  debit?: Money;
  credit?: Money;
  description?: string | null;
}

export interface JournalEntryCreate {
  journal_id: string;
  entry_date: string;
  narration: string;
  reference?: string | null;
  lines: JournalEntryLineInput[];
  post?: boolean;
}

// ---------------------------------------------------------------------------
// Accounting — reports
// ---------------------------------------------------------------------------
export interface TrialBalanceRow {
  account_id: string;
  code: string;
  name: string;
  account_type: AccountType;
  debit: Money;
  credit: Money;
}

export interface TrialBalance {
  as_of: string;
  rows: TrialBalanceRow[];
  total_debit: Money;
  total_credit: Money;
  is_balanced: boolean;
}

export interface ReportLine {
  label: string;
  amount: Money;
  level: number;
  is_total: boolean;
  account_code: string | null;
}

export interface ProfitAndLoss {
  from_date: string;
  to_date: string;
  income: ReportLine[];
  expenses: ReportLine[];
  total_income: Money;
  total_expenses: Money;
  cost_of_goods_sold: Money;
  gross_profit: Money;
  net_profit: Money;
}

export interface BalanceSheet {
  as_of: string;
  assets: ReportLine[];
  liabilities: ReportLine[];
  equity: ReportLine[];
  total_assets: Money;
  total_liabilities: Money;
  total_equity: Money;
  current_period_earnings: Money;
  is_balanced: boolean;
}

export interface LedgerLine {
  entry_id: string;
  entry_number: string | null;
  entry_date: string;
  narration: string;
  journal_code: string;
  debit: Money;
  credit: Money;
  running_balance: Money;
}

export interface AccountLedger {
  account: Account;
  from_date: string;
  to_date: string;
  opening_balance: Money;
  closing_balance: Money;
  total_debit: Money;
  total_credit: Money;
  lines: LedgerLine[];
}

export const accountingApi = {
  accounts: (params?: { account_type?: AccountType; postable_only?: boolean }) =>
    api.get<Account[]>('/accounts', { params }),

  journals: () => api.get<Journal[]>('/journals'),

  fiscalYears: () => api.get<FiscalYear[]>('/fiscal-years'),

  closePeriod: (periodId: string, lock = false) =>
    api.post<{ message: string }>(`/fiscal-years/periods/${periodId}/close`, null, {
      params: { lock },
    }),

  entries: (params?: PageQuery & { status?: EntryStatus; account_id?: string }) =>
    api.get<Page<JournalEntry>>('/journal-entries', { params }),

  entry: (id: string) => api.get<JournalEntry>(`/journal-entries/${id}`),

  createEntry: (body: JournalEntryCreate) => api.post<JournalEntry>('/journal-entries', body),

  postEntry: (id: string) => api.post<JournalEntry>(`/journal-entries/${id}/post`),

  reverseEntry: (id: string, body: { reversal_date?: string; narration?: string }) =>
    api.post<JournalEntry>(`/journal-entries/${id}/reverse`, body),

  trialBalance: (params?: { as_of?: string }) =>
    api.get<TrialBalance>('/reports/trial-balance', { params }),

  profitAndLoss: (params: { from_date: string; to_date: string }) =>
    api.get<ProfitAndLoss>('/reports/profit-and-loss', { params }),

  balanceSheet: (params?: { as_of?: string }) =>
    api.get<BalanceSheet>('/reports/balance-sheet', { params }),

  ledger: (accountId: string, params: { from_date: string; to_date: string }) =>
    api.get<AccountLedger>(`/accounts/${accountId}/ledger`, { params }),
};
