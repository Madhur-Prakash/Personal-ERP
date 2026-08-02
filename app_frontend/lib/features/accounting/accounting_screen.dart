import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../core/format.dart';
import '../../core/locale_settings.dart';
import '../../models/accounting.dart';
import '../../models/analytics.dart';
import '../../models/page.dart';
import '../../state/data_providers.dart';
import '../../theme/app_theme.dart';
import '../../theme/oklch.dart';
import '../../theme/tokens.dart';
import '../../widgets/app_badge.dart';
import '../../widgets/app_card.dart';
import '../../widgets/data_table.dart';
import '../../widgets/info_tip.dart';
import '../../widgets/metric_tile.dart';
import '../../widgets/primitives.dart';
import 'accounting_charts.dart';
import 'report_range.dart';

/// Accounting - chart of accounts, journal entries, and the financial statements.
///
/// One screen with tabs rather than five routes: an accountant moves between the trial
/// balance and the ledger constantly, and a full route transition on every switch is slower
/// than keeping the queries warm in one place.
class AccountingScreen extends ConsumerWidget {
  const AccountingScreen({super.key, this.tab});

  final String? tab;

  static const List<(String, String)> _tabs = <(String, String)>[
    ('chart', 'Chart of accounts'),
    ('entries', 'Journal entries'),
    ('trial-balance', 'Trial balance'),
    ('pnl', 'Profit & loss'),
    ('balance-sheet', 'Balance sheet'),
  ];

  /// Narrows an untrusted query parameter to a known tab, so a hand-edited value falls
  /// back to the default instead of breaking the screen.
  String get _active {
    final bool known = _tabs.any(((String, String) entry) => entry.$1 == tab);
    return known ? tab! : 'chart';
  }

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        const PageHeader(
          title: 'Accounting',
          description:
              'Double-entry ledger. Posted entries are immutable - corrections are made by '
              'reversal.',
        ),
        AppTabs(
          tabs: _tabs,
          active: _active,
          semanticLabel: 'Accounting views',
          // `replace` keeps tab switching out of the back stack.
          onChanged: (String next) => context.replace('/accounting?tab=$next'),
        ),
        switch (_active) {
          'entries' => const _JournalEntriesTab(),
          'trial-balance' => const _TrialBalanceTab(),
          'pnl' => const _ProfitAndLossTab(),
          'balance-sheet' => const _BalanceSheetTab(),
          _ => const _ChartOfAccountsTab(),
        },
      ],
    );
  }
}

// =============================================================================
// A range-driven tab
// =============================================================================
/// Holds the report range for the tabs that have one.
///
/// One range control drives every chart on a tab. Separate filters per chart would let two
/// panels sit side by side showing different periods, which is a reliable way to draw a
/// wrong conclusion from correct numbers.
mixin _RangeState<T extends StatefulWidget> on State<T> {
  RangePreset preset = RangePreset.yearToDate;
  DateRange? customRange;

  DateRange resolvedRange(PeriodOptions? periods) {
    final int fiscalStart =
        periods?.fiscalYearStartMonth ?? localeSettings().fiscalYearStartMonth;
    // The server's today, in the organization's timezone - not the machine's.
    final DateTime today = periods?.today != null
        ? DateTime.parse(periods!.today)
        : DateTime.now();

    if (preset == RangePreset.custom) {
      final DateRange custom =
          customRange ??
          resolveRange(RangePreset.yearToDate, today, fiscalStart);
      // A reversed range would be rejected by the server anyway; collapsing it keeps the
      // report on screen while the user is mid-edit rather than flashing an error.
      return custom.toDate.compareTo(custom.fromDate) < 0
          ? DateRange(fromDate: custom.toDate, toDate: custom.toDate)
          : custom;
    }
    return resolveRange(preset, today, fiscalStart);
  }

  Widget rangeSelector(PeriodOptions? periods) {
    final int fiscalStart =
        periods?.fiscalYearStartMonth ?? localeSettings().fiscalYearStartMonth;
    final DateTime today = periods?.today != null
        ? DateTime.parse(periods!.today)
        : DateTime.now();

    return ReportRangeSelector(
      preset: preset,
      custom:
          customRange ??
          resolveRange(RangePreset.yearToDate, today, fiscalStart),
      today: today,
      fiscalStartMonth: fiscalStart,
      onPresetChanged: (RangePreset next) => setState(() {
        // Seed the custom fields from whatever is on screen, so switching to Custom does
        // not blank the report.
        if (next == RangePreset.custom) {
          customRange = resolvedRange(periods);
        }
        preset = next;
      }),
      onCustomChanged: (DateRange next) => setState(() => customRange = next),
    );
  }
}

// =============================================================================
// Chart of accounts
// =============================================================================
class _ChartOfAccountsTab extends ConsumerStatefulWidget {
  const _ChartOfAccountsTab();

  @override
  ConsumerState<_ChartOfAccountsTab> createState() =>
      _ChartOfAccountsTabState();
}

class _ChartOfAccountsTabState extends ConsumerState<_ChartOfAccountsTab>
    with _RangeState {
  @override
  Widget build(BuildContext context) {
    final PeriodOptions? periods = ref.watch(periodOptionsProvider).valueOrNull;
    final DateRange range = resolvedRange(periods);
    final String currency = localeSettings().currency;

    // Balances are point-in-time, so only the end of the range applies - "cash over March"
    // is not a number.
    final AsyncValue<List<Account>> accounts = ref.watch(
      accountsProvider(range.toDate),
    );
    // The waterfall's closing bar must equal the dashboard's net profit, so it is built
    // from the statement rather than recomputed.
    final AsyncValue<ProfitAndLoss> report = ref.watch(
      profitAndLossProvider(range),
    );
    final Trend? trend = ref.watch(trendForRangeProvider(range)).valueOrNull;

    final List<Account> rows = accounts.valueOrNull ?? const <Account>[];

    // The 114-row table is gone. It listed every account in the template, of which four
    // hold a balance, so it was a hundred rows of zero in front of the four figures anyone
    // came here for. The charts show what has money; the trial balance is the place to read
    // exact per-account figures.
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 16,
      children: <Widget>[
        AppCard(
          child: CardHeader(
            title: 'Period',
            description:
                'Every chart below covers ${range.fromDate} to ${range.toDate}.',
            action: rangeSelector(periods),
          ),
        ),
        ProfitWaterfallCard(
          report: report.valueOrNull,
          currency: currency,
          isLoading: report.isLoading,
        ),
        if (accounts.isLoading)
          AppCard(
            padding: const EdgeInsets.all(20),
            child: const Skeleton(height: 256),
          )
        else ...<Widget>[
          LayoutBuilder(
            builder: (BuildContext context, BoxConstraints constraints) {
              final Widget balances = AccountBalancesChart(
                accounts: rows,
                currency: currency,
              );
              final Widget mix = SpendingMixChart(
                accounts: rows,
                currency: currency,
              );
              if (constraints.maxWidth < 1180) {
                return Column(spacing: 16, children: <Widget>[balances, mix]);
              }
              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                spacing: 16,
                children: <Widget>[
                  Expanded(child: balances),
                  Expanded(child: mix),
                ],
              );
            },
          ),
          TrendCard(points: trend?.points, currency: currency),
          BalanceByTypeChart(accounts: rows, currency: currency),
        ],
      ],
    );
  }
}

// =============================================================================
// Journal entries
// =============================================================================
class _JournalEntriesTab extends ConsumerStatefulWidget {
  const _JournalEntriesTab();

  @override
  ConsumerState<_JournalEntriesTab> createState() => _JournalEntriesTabState();
}

class _JournalEntriesTabState extends ConsumerState<_JournalEntriesTab> {
  int _page = 1;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final AsyncValue<Paged<JournalEntry>> entries = ref.watch(
      journalEntriesProvider(_page),
    );
    final Paged<JournalEntry>? page = entries.valueOrNull;
    final String currency = localeSettings().currency;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 16,
      children: <Widget>[
        CashMovementChart(
          entries: page?.items ?? const <JournalEntry>[],
          currency: currency,
        ),
        AppCard(
          child: Column(
            children: <Widget>[
              AppDataTable<JournalEntry>(
                rows: page?.items ?? const <JournalEntry>[],
                rowKey: (JournalEntry row) => row.id,
                isLoading: entries.isLoading,
                empty: const EmptyState(
                  title: 'No journal entries',
                  description:
                      'Entries appear here as invoices, bills, and payments are posted.',
                ),
                columns: <AppColumn<JournalEntry>>[
                  AppColumn<JournalEntry>(
                    header: 'Number',
                    fixedWidth: 110,
                    cell: (JournalEntry row) => Text(
                      row.entryNumber ?? 'draft',
                      style: monoStyle(
                        color: row.entryNumber == null
                            ? t.contentMuted
                            : t.content,
                      ),
                    ),
                  ),
                  AppColumn<JournalEntry>(
                    header: 'Date',
                    fixedWidth: 116,
                    cell: (JournalEntry row) => Text(formatDate(row.entryDate)),
                  ),
                  AppColumn<JournalEntry>(
                    header: 'Narration',
                    cell: (JournalEntry row) => Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(row.narration, overflow: TextOverflow.ellipsis),
                        Text(
                          row.journalCode +
                              (row.reference != null
                                  ? ' · ${row.reference}'
                                  : ''),
                          style: TextStyle(fontSize: 11, color: t.contentMuted),
                        ),
                      ],
                    ),
                  ),
                  AppColumn<JournalEntry>(
                    header: 'Money',
                    hideOnNarrow: true,
                    fixedWidth: 150,
                    cell: (JournalEntry row) => row.cashDirection == null
                        // No cash leg, or a transfer between your own accounts that nets
                        // to nothing.
                        ? Text(
                            'no cash movement',
                            style: TextStyle(
                              fontSize: 12,
                              color: t.contentMuted,
                            ),
                          )
                        : Text(
                            '${row.cashDirection == 'in' ? 'In' : 'Out'} '
                            '${formatMoney(row.cashAmount, currency: currency)}',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w500,
                              color: row.cashDirection == 'in'
                                  ? t.success
                                  : t.danger,
                            ),
                          ),
                  ),
                  AppColumn<JournalEntry>(
                    header: 'Status',
                    hideOnNarrow: true,
                    fixedWidth: 170,
                    cell: (JournalEntry row) => row.isReversed
                        ? const AppBadge(
                            'Reversed - cancelled',
                            tone: BadgeTone.warning,
                            tooltip:
                                'Cancelled by an opposite entry. Both remain on the record.',
                          )
                        : row.reversesId != null
                        ? const AppBadge(
                            'Reversal entry',
                            tooltip: 'This entry cancels an earlier one.',
                          )
                        : AppBadge(
                            row.status,
                            tone: switch (row.status) {
                              'posted' => BadgeTone.success,
                              'reversed' => BadgeTone.warning,
                              _ => BadgeTone.neutral,
                            },
                          ),
                  ),
                  AppColumn<JournalEntry>(
                    header: 'Amount',
                    numeric: true,
                    cell: (JournalEntry row) => Text(
                      formatMoney(row.totalDebit, currency: currency),
                      style: TextStyle(
                        color: row.isReversed ? t.contentMuted : t.content,
                        decoration: row.isReversed
                            ? TextDecoration.lineThrough
                            : null,
                      ),
                    ),
                  ),
                ],
              ),
              if (page != null)
                Pagination(
                  page: page.meta.page,
                  totalPages: page.meta.totalPages,
                  totalItems: page.meta.totalItems,
                  onChanged: (int next) => setState(() => _page = next),
                ),
            ],
          ),
        ),
      ],
    );
  }
}

// =============================================================================
// Trial balance
// =============================================================================
class _TrialBalanceTab extends ConsumerWidget {
  const _TrialBalanceTab();

  /// Did this account have movement that cancelled out?
  ///
  /// Distinct from "no activity": an account whose charge was reversed has a story, an
  /// untouched account does not, and showing both as two dashes conflates them.
  static bool _netsToNil(TrialBalanceRow row) =>
      isZeroMoney(row.debit) &&
      isZeroMoney(row.credit) &&
      !(isZeroMoney(row.grossDebit) && isZeroMoney(row.grossCredit));

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppTokens t = context.tokens;
    final AsyncValue<TrialBalance> balance = ref.watch(trialBalanceProvider);
    final TrialBalance? data = balance.valueOrNull;
    final String currency = localeSettings().currency;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 16,
      children: <Widget>[
        // Surfaced rather than hidden: an unbalanced ledger is the single most serious
        // condition this system can be in.
        if (data != null && !data.isBalanced)
          AppCard(
            borderColour: t.danger.at(0.4),
            background: t.dangerBg,
            padding: const EdgeInsets.all(20),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 12,
              children: <Widget>[
                Padding(
                  padding: const EdgeInsets.only(top: 2),
                  child: Icon(
                    LucideIcons.triangleAlert,
                    size: 16,
                    color: t.danger,
                  ),
                ),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: <Widget>[
                      Text(
                        'Ledger does not balance',
                        style: TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          color: t.danger,
                        ),
                      ),
                      Text(
                        'Debits ${formatMoney(data.totalDebit, currency: currency)} ≠ '
                        'credits ${formatMoney(data.totalCredit, currency: currency)}. '
                        'This should be impossible - contact support.',
                        style: TextStyle(
                          fontSize: 12,
                          color: t.contentSecondary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        AppCard(
          child: Column(
            children: <Widget>[
              CardHeader(
                // The ⓘ rather than a paragraph under the heading: the explanation is long
                // enough to push the figures down the screen, and most visits do not need
                // it.
                titleWidget: Row(
                  mainAxisSize: MainAxisSize.min,
                  spacing: 6,
                  children: <Widget>[
                    Text(
                      'Trial balance',
                      style: TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w600,
                        color: t.content,
                      ),
                    ),
                    InfoTip(
                      label: 'the trial balance',
                      children: <Widget>[
                        infoText(
                          'Every account that has money in it, and which side that money '
                          'sits on.',
                        ),
                        infoRich(<String>[
                          '',
                          'Debit',
                          ' is what you have and what you have spent. ',
                          'Credit',
                          ' is what you owe and what you have earned. They are just the two '
                              'sides of an entry, not good and bad.',
                        ]),
                        infoText(
                          'Every entry puts the same amount on both sides, so the two totals '
                          'at the bottom must match. That is the one thing this table proves '
                          '- and if they ever did not match, something would be wrong with '
                          'the books themselves rather than with any single entry.',
                        ),
                        infoRich(<String>[
                          '',
                          'A cash or bank account should appear under Debit.',
                          ' If one shows under Credit, the books say more went out of it '
                              'than ever went in - which is impossible for real cash, and '
                              'usually means money that came from a different account was '
                              'recorded against this one. The totals still balance, because '
                              'a wrong pair of entries balances just as well as a right one.',
                        ]),
                        infoRich(<String>[
                          '',
                          'Dealt with',
                          " lists the people and businesses behind an account's balance, "
                              'from the From/To field on the Billing screen. A dash means '
                              'those entries did not name anyone.',
                        ]),
                      ],
                    ),
                  ],
                ),
                description: data == null
                    ? null
                    : 'As at ${formatDate(data.asOf)}',
                action: data?.isBalanced == true
                    ? const AppBadge(
                        'Balanced',
                        tone: BadgeTone.success,
                        dot: true,
                      )
                    : null,
              ),
              AppDataTable<TrialBalanceRow>(
                rows: data?.rows ?? const <TrialBalanceRow>[],
                rowKey: (TrialBalanceRow row) => row.accountId,
                isLoading: balance.isLoading,
                empty: const EmptyState(
                  title: 'Nothing posted yet',
                  description: 'Post an entry to see balances.',
                ),
                footer: data == null
                    ? null
                    : <Widget>[
                        const FooterCell('Total', numeric: false),
                        const SizedBox.shrink(),
                        FooterCell(
                          formatMoney(data.totalDebit, currency: currency),
                        ),
                        FooterCell(
                          formatMoney(data.totalCredit, currency: currency),
                        ),
                      ],
                columns: <AppColumn<TrialBalanceRow>>[
                  AppColumn<TrialBalanceRow>(
                    header: 'Account',
                    flex: 2,
                    cell: (TrialBalanceRow row) => Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: <Widget>[
                        Text(row.name),
                        if (_netsToNil(row))
                          Padding(
                            padding: const EdgeInsets.only(top: 4),
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              spacing: 6,
                              children: <Widget>[
                                Padding(
                                  padding: const EdgeInsets.only(top: 2),
                                  child: Icon(
                                    LucideIcons.undo2,
                                    size: 14,
                                    color: t.warning,
                                  ),
                                ),
                                Expanded(
                                  child: Text.rich(
                                    TextSpan(
                                      children: <InlineSpan>[
                                        TextSpan(
                                          text: formatMoney(
                                            row.grossDebit,
                                            currency: currency,
                                          ),
                                          style: const TextStyle(
                                            fontWeight: FontWeight.w600,
                                          ),
                                        ),
                                        const TextSpan(
                                          text:
                                              ' was posted here and then reversed, so '
                                              'it does not affect the balance.',
                                        ),
                                      ],
                                    ),
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: t.warning,
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                      ],
                    ),
                  ),
                  AppColumn<TrialBalanceRow>(
                    header: 'Dealt with',
                    hideOnNarrow: true,
                    cell: (TrialBalanceRow row) => _Parties(names: row.parties),
                  ),
                  AppColumn<TrialBalanceRow>(
                    header: 'Debit',
                    numeric: true,
                    cell: (TrialBalanceRow row) => isZeroMoney(row.debit)
                        ? Text('-', style: TextStyle(color: t.contentMuted))
                        : Text(formatMoney(row.debit, currency: currency)),
                  ),
                  AppColumn<TrialBalanceRow>(
                    header: 'Credit',
                    numeric: true,
                    cell: (TrialBalanceRow row) => isZeroMoney(row.credit)
                        ? Text('-', style: TextStyle(color: t.contentMuted))
                        : Text(formatMoney(row.credit, currency: currency)),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// The parties an account has dealt with.
///
/// One column, not a from/to pair. An account that both received from and paid the same
/// person showed that name in both columns, which reads as a contradiction even though it is
/// exactly what happened - because direction belongs to a transaction and this row is a
/// balance over many of them.
///
/// A dash means the entries behind this balance named nobody, which is the honest answer for
/// anything recorded before naming the party became required.
class _Parties extends StatelessWidget {
  const _Parties({required this.names});

  final List<String> names;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    if (names.isEmpty) {
      return Text('-', style: TextStyle(color: t.contentMuted));
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          names.first,
          overflow: TextOverflow.ellipsis,
          style: TextStyle(fontSize: 12, color: t.content),
        ),
        if (names.length > 1)
          // Counted, with the names in the tooltip: a cell that grew with the number of
          // parties would set the row height for the whole table.
          Tooltip(
            message: names.skip(1).join(', '),
            child: Text(
              'and ${names.length - 1} more',
              style: TextStyle(fontSize: 11, color: t.contentMuted),
            ),
          ),
      ],
    );
  }
}

// =============================================================================
// Profit & loss
// =============================================================================
class _ProfitAndLossTab extends ConsumerStatefulWidget {
  const _ProfitAndLossTab();

  @override
  ConsumerState<_ProfitAndLossTab> createState() => _ProfitAndLossTabState();
}

class _ProfitAndLossTabState extends ConsumerState<_ProfitAndLossTab>
    with _RangeState {
  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final PeriodOptions? periods = ref.watch(periodOptionsProvider).valueOrNull;
    final DateRange range = resolvedRange(periods);
    final AsyncValue<ProfitAndLoss> report = ref.watch(
      profitAndLossProvider(range),
    );
    final ProfitAndLoss? data = report.valueOrNull;
    final String currency = localeSettings().currency;

    if (data == null) {
      return Column(
        spacing: 16,
        children: <Widget>[
          AppCard(
            child: CardHeader(
              title: 'Profit & loss',
              action: rangeSelector(periods),
            ),
          ),
          AppCard(
            padding: const EdgeInsets.all(20),
            child: const Skeleton(height: 240),
          ),
        ],
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      spacing: 16,
      children: <Widget>[
        TileGrid(
          maxColumns: 3,
          children: <Widget>[
            MetricTile(
              label: 'Revenue',
              value: formatMoney(data.totalIncome, currency: currency),
              icon: LucideIcons.trendingUp,
              valueSize: 20,
              uppercaseLabel: true,
            ),
            MetricTile(
              label: 'Gross profit',
              value: formatMoney(data.grossProfit, currency: currency),
              icon: LucideIcons.scale,
              valueSize: 20,
              uppercaseLabel: true,
            ),
            MetricTile(
              label: 'Net profit',
              value: formatMoney(data.netProfit, currency: currency),
              icon: LucideIcons.bookOpen,
              valueSize: 20,
              uppercaseLabel: true,
              valueTone: isNegativeMoney(data.netProfit) ? t.danger : t.success,
            ),
          ],
        ),
        AppCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: <Widget>[
              CardHeader(
                title: 'Profit & loss',
                description:
                    '${formatDate(data.fromDate)} to ${formatDate(data.toDate)}',
                action: rangeSelector(periods),
              ),
              CardBody(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 20,
                  children: <Widget>[
                    _ReportSection(
                      title: 'Income',
                      lines: data.income,
                      total: data.totalIncome,
                      currency: currency,
                    ),
                    _ReportSection(
                      title: 'Expenses',
                      lines: data.expenses,
                      total: data.totalExpenses,
                      currency: currency,
                    ),
                    Container(
                      padding: const EdgeInsets.only(top: 12),
                      decoration: BoxDecoration(
                        border: Border(top: BorderSide(color: t.border)),
                      ),
                      child: Row(
                        children: <Widget>[
                          Text(
                            'Net profit',
                            style: TextStyle(
                              fontSize: 14,
                              fontWeight: FontWeight.w600,
                              color: t.content,
                            ),
                          ),
                          const Spacer(),
                          Text(
                            formatMoney(data.netProfit, currency: currency),
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w600,
                              color: t.content,
                              fontFeatures: tabularFigures,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

// =============================================================================
// Balance sheet
// =============================================================================
class _BalanceSheetTab extends ConsumerWidget {
  const _BalanceSheetTab();

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final AppTokens t = context.tokens;
    final AsyncValue<BalanceSheet> sheet = ref.watch(balanceSheetProvider);
    final BalanceSheet? data = sheet.valueOrNull;
    final String currency = localeSettings().currency;

    if (data == null) {
      return AppCard(
        padding: const EdgeInsets.all(20),
        child: const Skeleton(height: 280),
      );
    }

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            title: 'Balance sheet',
            description: 'As at ${formatDate(data.asOf)}',
            action: AppBadge(
              data.isBalanced ? 'Balanced' : 'Out of balance',
              tone: data.isBalanced ? BadgeTone.success : BadgeTone.danger,
              dot: true,
            ),
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 20,
              children: <Widget>[
                _ReportSection(
                  title: 'Assets',
                  lines: data.assets,
                  total: data.totalAssets,
                  currency: currency,
                ),
                _ReportSection(
                  title: 'Liabilities',
                  lines: data.liabilities,
                  total: data.totalLiabilities,
                  currency: currency,
                ),
                _ReportSection(
                  title: 'Equity',
                  lines: data.equity,
                  total: data.totalEquity,
                  currency: currency,
                ),
                Container(
                  padding: const EdgeInsets.only(top: 12),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: t.border)),
                  ),
                  child: Row(
                    children: <Widget>[
                      Text(
                        'Liabilities + equity',
                        style: TextStyle(
                          fontSize: 14,
                          fontWeight: FontWeight.w600,
                          color: t.content,
                        ),
                      ),
                      const Spacer(),
                      Text(
                        // Displayed for the reader to check against total assets. The
                        // authoritative check is `isBalanced`, computed server-side.
                        formatMoney(
                          sumMoney(<String>[
                            data.totalLiabilities,
                            data.totalEquity,
                          ]),
                          currency: currency,
                        ),
                        style: TextStyle(
                          fontSize: 15,
                          fontWeight: FontWeight.w600,
                          color: t.content,
                          fontFeatures: tabularFigures,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

// =============================================================================
// Shared report pieces
// =============================================================================
class _ReportSection extends StatelessWidget {
  const _ReportSection({
    required this.title,
    required this.lines,
    required this.total,
    required this.currency,
  });

  final String title;
  final List<ReportLine> lines;
  final String total;
  final String currency;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: <Widget>[
        Text(
          title.toUpperCase(),
          style: TextStyle(
            fontSize: 11,
            fontWeight: FontWeight.w600,
            letterSpacing: 0.8,
            color: t.contentMuted,
          ),
        ),
        const SizedBox(height: 6),
        if (lines.isEmpty)
          Text(
            'Nothing to report',
            style: TextStyle(fontSize: 13, color: t.contentMuted),
          )
        else
          for (final ReportLine line in lines)
            Padding(
              padding: EdgeInsets.only(
                left: (line.level - 1) * 12.0,
                bottom: 4,
              ),
              child: Row(
                children: <Widget>[
                  if (line.accountCode != null) ...<Widget>[
                    Text(
                      line.accountCode!,
                      style: monoStyle(fontSize: 11, color: t.contentMuted),
                    ),
                    const SizedBox(width: 8),
                  ],
                  Expanded(
                    child: Text(
                      line.label,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 13, color: t.contentSecondary),
                    ),
                  ),
                  Text(
                    formatMoney(line.amount, currency: currency),
                    style: TextStyle(
                      fontSize: 13,
                      color: t.content,
                      fontFeatures: tabularFigures,
                    ),
                  ),
                ],
              ),
            ),
        Container(
          margin: const EdgeInsets.only(top: 6),
          padding: const EdgeInsets.only(top: 6),
          decoration: BoxDecoration(
            border: Border(top: BorderSide(color: t.border.at(0.6))),
          ),
          child: Row(
            children: <Widget>[
              Text(
                'Total ${title.toLowerCase()}',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: t.content,
                ),
              ),
              const Spacer(),
              Text(
                formatMoney(total, currency: currency),
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w500,
                  color: t.content,
                  fontFeatures: tabularFigures,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}
