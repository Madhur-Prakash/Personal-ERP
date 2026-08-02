/// Accounts and cards - where money sits, and what it moves through.
///
/// Split out of `billing_screen.dart` because it answers a different question. That
/// screen is the fast path for recording a movement; this is the occasional bit of
/// setup that makes the pickers on it useful. Someone opens it when a new card
/// arrives, not six times a day.
///
/// Two things here are worth knowing before changing anything:
///
/// 1. **A card number is typed, sent once, and gone.** It lives in a
///    [TextEditingController] for as long as the dialog is open and is disposed with
///    it. [PaymentCard] has no field for it, nothing caches it, and no autofill hint
///    is set, so the platform is not invited to keep it either. Only the network and
///    the last four digits come back.
/// 2. **A credit card is a liability, not a place you have money.** It appears in the
///    "paid from" picker because you genuinely can pay with it, but it is never
///    totalled beside a bank balance, because the number means the opposite thing.
library;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';

import '../../core/card_number.dart';
import '../../core/format.dart';
import '../../models/billing.dart';
import '../../state/data_providers.dart';
import '../../state/providers.dart';
import '../../theme/app_theme.dart';
import '../../theme/tokens.dart';
import '../../widgets/app_badge.dart';
import '../../widgets/app_button.dart';
import '../../widgets/app_card.dart';
import '../../widgets/app_input.dart';
import '../../widgets/app_modal.dart';
import '../../widgets/app_select.dart';
import '../../widgets/info_tip.dart';
import '../../widgets/primitives.dart';
import '../../widgets/toast.dart';

/// Accounts split into "Cash & bank" and "Cards", for a picker.
///
/// Grouped rather than flat because the two are not interchangeable: one is money you
/// have, the other can be money you owe, and a heading says so without needing a
/// sentence of explanation on a dropdown.
///
/// Option values are [MoneyAccount.key], **not the account id** - a debit card and the
/// bank account it draws on share an id, and two options with one value is a picker
/// that cannot represent the user's choice.
List<SelectGroup> moneyAccountGroups(List<MoneyAccount> accounts) {
  final List<SelectGroup> groups = <SelectGroup>[];
  for (final MoneyAccount account in accounts) {
    final String label = account.isCard ? 'Cards' : 'Cash & bank';
    final SelectOption option = SelectOption(
      value: account.key,
      label: account.name,
    );
    final SelectGroup? existing = groups
        .where((SelectGroup g) => g.label == label)
        .firstOrNull;
    if (existing != null) {
      existing.options.add(option);
    } else {
      groups.add(SelectGroup(label: label, options: <SelectOption>[option]));
    }
  }
  return groups;
}

/// The account a [MoneyAccount.key] came from.
MoneyAccount? accountForKey(List<MoneyAccount> accounts, String key) =>
    accounts.where((MoneyAccount a) => a.key == key).firstOrNull;

/// Ask for a new place money can sit, create it, and return it.
///
/// The seeded chart gives one till and one current account, which covers a business with
/// exactly those. A second bank, a UPI wallet, a card-settlement account, or a partner's
/// petty cash are all ordinary - and without this the only choices are the seeded two, so
/// money that moved through a wallet gets filed as cash and no balance matches anything
/// real.
///
/// **The bank fields appear only for a bank account** and vanish for cash in hand rather
/// than being disabled. Cash has no bank, no number and no holder, so the server ignores
/// them, and a field that will never become usable explains that worse than no field at all.
///
/// A top-level function rather than a method, because two places offer this: the "+ Add
/// account" link on the recording form, which also selects what it just made, and the "Add
/// an account" button on the accounts panel, which does not. Returns null if the dialog was
/// dismissed or the request failed - the caller decides whether that matters.
Future<MoneyAccount?> showAddMoneyAccountDialog(
  BuildContext context,
  WidgetRef ref,
) async {
  final TextEditingController name = TextEditingController();
  final TextEditingController bank = TextEditingController();
  final TextEditingController holder = TextEditingController();
  final TextEditingController number = TextEditingController();
  MoneyKind kind = MoneyKind.bank;

  void disposeAll() {
    name.dispose();
    bank.dispose();
    holder.dispose();
    number.dispose();
  }

  try {
    final bool? confirmed = await showAppModal<bool>(
      context: context,
      title: 'New account',
      description: "A second bank, a UPI wallet, a partner's petty cash.",
      builder: (BuildContext context) => StatefulBuilder(
        builder: (BuildContext context, void Function(void Function()) rebuild) => Column(
          spacing: 12,
          children: <Widget>[
            AppInput(
              label: 'Account name',
              controller: name,
              autofocus: true,
              required: true,
              placeholder: 'Name of the account',
              hint: 'What you call it on this screen.',
            ),
            AppSelect(
              label: 'Behaves like',
              value: kind.wire,
              options: const <SelectOption>[
                SelectOption(value: 'bank', label: 'A bank account'),
                SelectOption(value: 'cash', label: 'Cash in hand'),
              ],
              onChanged: (String next) => rebuild(
                () => kind = next == 'cash' ? MoneyKind.cash : MoneyKind.bank,
              ),
              // The distinction is how it gets checked, not what it is called: cash
              // against a physical count, a bank against a statement. A UPI wallet is
              // a bank.
              hint: kind == MoneyKind.bank
                  ? 'Checked against a statement'
                  : 'Checked by counting',
            ),
            if (kind == MoneyKind.bank) ...<Widget>[
              AppInput(
                label: 'Bank name',
                controller: bank,
                placeholder: 'HDFC Bank',
                hint: 'Optional.',
              ),
              AppInput(
                label: 'Account holder',
                controller: holder,
                placeholder: 'Jhon Doe',
                hint: 'Optional - whose account it is.',
              ),
              AppInput(
                label: 'Account number',
                controller: number,
                placeholder: '50100123454321',
                keyboardType: TextInputType.number,
                inputFormatters: <TextInputFormatter>[
                  FilteringTextInputFormatter.allow(RegExp(r'[\d\s-]')),
                ],
                textStyle: const TextStyle(fontFeatures: tabularFigures),
                hint:
                    'Optional. Stored encrypted; lists show the last four digits.',
              ),
            ],
          ],
        ),
      ),
      footer: (BuildContext context) => <Widget>[
        AppButton(
          onPressed: () => Navigator.of(context).pop(false),
          variant: AppButtonVariant.ghost,
          label: 'Cancel',
        ),
        AppButton(
          onPressed: () => Navigator.of(context).pop(true),
          label: 'Add',
        ),
      ],
    );

    // Checked here rather than only in the dialog: the modal's "Add" button is always
    // live, so this is what stops a nameless account becoming a request.
    if (confirmed != true || name.text.trim().isEmpty) return null;

    final bool isBank = kind == MoneyKind.bank;
    try {
      final MoneyAccount created = await ref
          .read(billingApiProvider)
          .createMoneyAccount(
            name.text.trim(),
            kind,
            // Left out entirely for cash, so the request says what it means rather than
            // sending three blanks for the server to decide to ignore.
            bankName: isBank ? bank.text.trim() : null,
            holderName: isBank ? holder.text.trim() : null,
            accountNumber: isBank ? number.text.trim() : null,
          );

      ref.invalidate(billingOptionsProvider);
      ref.invalidate(accountsProvider);

      if (context.mounted) {
        context.toastSuccess(
          'Added "${created.name}"',
          description: created.bankName,
        );
      }
      return created;
    } catch (error) {
      if (context.mounted) {
        context.toastApiError(error, 'Could not add the account');
      }
      return null;
    }
  } finally {
    // Every controller, on every path. This used to dispose only `name` on the success
    // path, which leaked the three bank fields each time an account was added.
    disposeAll();
  }
}

// =============================================================================
// Transfer
// =============================================================================

/// Move money between two of your own accounts.
///
/// **There is no category field, and that is not an omission.** Moving your own money
/// is neither earning it nor spending it, so there is no income or expense line for it
/// to go against - which is also why a transfer is left out of the money-in and
/// money-out totals. Counting one would show income that never came from anywhere and
/// an expense that bought nothing.
class TransferForm extends ConsumerStatefulWidget {
  const TransferForm({super.key, required this.options, required this.onClose});

  final BillingOptions options;
  final VoidCallback onClose;

  @override
  ConsumerState<TransferForm> createState() => _TransferFormState();
}

class _TransferFormState extends ConsumerState<TransferForm> {
  final TextEditingController _amount = TextEditingController();
  final TextEditingController _description = TextEditingController();

  late String _entryDate;
  late String _fromId;
  late String _toId;
  bool _saving = false;

  List<MoneyAccount> get _accounts => widget.options.transferableAccounts;

  /// The first account that is not [exclude], for seeding or un-clashing the other side.
  String _otherThan(String exclude) =>
      _accounts.where((MoneyAccount a) => a.id != exclude).firstOrNull?.id ?? '';

  @override
  void initState() {
    super.initState();
    _entryDate = widget.options.today;
    final List<MoneyAccount> accounts = _accounts;
    _fromId =
        accounts.where((MoneyAccount a) => a.isDefault).firstOrNull?.id ??
        (accounts.isEmpty ? '' : accounts.first.id);
    // Defaulted too, rather than left blank. **The first account that is not the "from"** -
    // the one thing a transfer cannot be is an account to itself, so seeding both sides with
    // the default account would open the form already invalid.
    _toId = _otherThan(_fromId);
  }

  @override
  void dispose() {
    _amount.dispose();
    _description.dispose();
    super.dispose();
  }

  bool get _sameAccount => _fromId.isNotEmpty && _fromId == _toId;

  bool get _canSave {
    final double amount = double.tryParse(_amount.text) ?? 0;
    return amount > 0 &&
        _fromId.isNotEmpty &&
        _toId.isNotEmpty &&
        !_sameAccount;
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      final Transfer result = await ref
          .read(billingApiProvider)
          .transfer(
            fromAccountId: _fromId,
            toAccountId: _toId,
            amount: _amount.text,
            entryDate: _entryDate,
            description: _description.text.trim(),
          );

      // Every balance derived from the ledger is stale - but the day book and its
      // totals are not, because a transfer is deliberately excluded from both. They
      // are refreshed anyway: `invalidateLedger` is one list kept in one place, and a
      // second nearly-identical list that omitted two providers would be the kind of
      // thing that silently rots.
      invalidateLedger(ref);

      if (!mounted) return;
      context.toastSuccess(
        'Moved ${formatMoney(result.amount, currency: widget.options.currency)}',
        description: '${result.fromAccountName} → ${result.toAccountName}',
      );

      _amount.clear();
      _description.clear();
      setState(() {});
    } catch (error) {
      if (mounted) context.toastApiError(error, 'Could not make the transfer');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final List<SelectOption> options = <SelectOption>[
      for (final MoneyAccount account in _accounts)
        SelectOption(value: account.id, label: account.name),
    ];

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            title: 'Move money between accounts',
            description:
                'A transfer is not income or an expense, so it does not appear in '
                'your money-in and money-out totals.',
            action: AppButton(
              onPressed: widget.onClose,
              variant: AppButtonVariant.ghost,
              label: 'Close',
            ),
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 12,
              children: <Widget>[
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 12,
                  children: <Widget>[
                    Expanded(
                      child: AppSelect(
                        label: 'From',
                        value: _fromId,
                        options: options,
                        onChanged: (String next) => setState(() {
                          _fromId = next;
                          // Move "to" out of the way rather than leaving the form on an
                          // error the user did not make: choosing the account that happened
                          // to be the destination is a normal thing to do.
                          if (_toId == next) _toId = _otherThan(next);
                        }),
                        hint: 'The account the money leaves.',
                      ),
                    ),
                    Padding(
                      padding: const EdgeInsets.only(top: 30),
                      child: Icon(
                        LucideIcons.arrowLeftRight,
                        size: 16,
                        color: t.contentMuted,
                      ),
                    ),
                    Expanded(
                      child: AppSelect(
                        label: 'To',
                        value: _toId,
                        options: options,
                        onChanged: (String next) =>
                            setState(() => _toId = next),
                        error: _sameAccount
                            ? 'Pick a different account.'
                            : null,
                        hint:
                            'The account it arrives in. Paying off a credit card '
                            'goes here.',
                      ),
                    ),
                  ],
                ),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 12,
                  children: <Widget>[
                    SizedBox(
                      width: 144,
                      child: AppNumberInput(
                        label: 'Amount',
                        controller: _amount,
                        required: true,
                        autofocus: true,
                        placeholder: '0.00',
                        decimals: 2,
                        textStyle: const TextStyle(
                          fontSize: 15,
                          fontFeatures: tabularFigures,
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                    ),
                    AppDateInput(
                      label: 'Date',
                      value: _entryDate,
                      maximum: widget.options.today,
                      width: 160,
                      onChanged: (String next) =>
                          setState(() => _entryDate = next),
                    ),
                    Expanded(
                      child: AppInput(
                        label: 'Note',
                        controller: _description,
                        placeholder: 'Cash deposited at branch',
                        hint:
                            'Optional - left blank, the ledger names both accounts.',
                      ),
                    ),
                  ],
                ),
                Container(
                  padding: const EdgeInsets.only(top: 12),
                  decoration: BoxDecoration(
                    border: Border(top: BorderSide(color: t.border)),
                  ),
                  child: Row(
                    children: <Widget>[
                      Expanded(
                        child: Text(
                          'Posts to your books as one entry against both accounts.',
                          style: TextStyle(fontSize: 12, color: t.contentMuted),
                        ),
                      ),
                      AppButton(
                        onPressed: _canSave && !_saving ? _save : null,
                        loading: _saving,
                        label: _saving ? 'Moving…' : 'Move money',
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
// The panel
// =============================================================================

/// Everything registered, and the way to add to it.
///
/// Placed below the day book on purpose: it is setup, and the screen's job is
/// recording.
class AccountsPanel extends ConsumerStatefulWidget {
  const AccountsPanel({
    super.key,
    required this.options,
    this.standalone = false,
  });

  final BillingOptions options;

  /// True when this *is* the screen rather than a panel at the foot of one.
  ///
  /// Only suppresses the card's own title and description, because the page header has
  /// already said both and repeating them reads as a bug. The "Add a card" action stays
  /// either way - it is the point of the header, not decoration.
  final bool standalone;

  @override
  ConsumerState<AccountsPanel> createState() => _AccountsPanelState();
}

class _AccountsPanelState extends ConsumerState<AccountsPanel> {
  bool _showArchived = false;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;

    // Falls back to the options payload while the dedicated request is in flight, so
    // the list does not blink empty on first paint. That payload only ever holds
    // active cards, which is exactly right for the default view.
    final List<PaymentCard> cards =
        ref.watch(billingCardsProvider(_showArchived)).valueOrNull ??
        widget.options.cards;

    final List<MoneyAccount> accounts = widget.options.transferableAccounts
        .where((MoneyAccount a) => !a.isCard)
        .toList(growable: false);

    return AppCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          CardHeader(
            title: widget.standalone ? null : 'Accounts & cards',
            description: widget.standalone
                ? null
                : 'Where your money sits, and the cards you spend on. These are the '
                      'choices offered when recording a payment.',
            // Both actions, matching the web accounts page. Adding an account used to be
            // reachable only from the "+ Add account" link on the recording form, which
            // meant the screen dedicated to accounts was the one place you could not make
            // one.
            action: Row(
              mainAxisSize: MainAxisSize.min,
              spacing: 8,
              children: <Widget>[
                AppButton(
                  onPressed: () => showAddMoneyAccountDialog(context, ref),
                  variant: AppButtonVariant.secondary,
                  leftIcon: LucideIcons.plus,
                  label: 'Add an account',
                ),
                AppButton(
                  onPressed: _addCard,
                  variant: AppButtonVariant.secondary,
                  leftIcon: LucideIcons.creditCard,
                  label: 'Add a card',
                ),
              ],
            ),
          ),
          CardBody(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              spacing: 20,
              children: <Widget>[
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 8,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Text(
                          'Cash & bank',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                            color: t.contentSecondary,
                          ),
                        ),
                        const SizedBox(width: 6),
                        InfoTip(
                          label: 'Cash and bank',
                          children: <Widget>[
                            infoText(
                              'An account number is stored encrypted, and stored in '
                              'full - unlike a card number, which is never kept at '
                              'all. You need the account number to be paid and to '
                              'match a statement, so keeping only four digits would '
                              'make it useless.',
                            ),
                            infoText('Lists show the last four digits only.'),
                          ],
                        ),
                      ],
                    ),
                    for (final (int index, MoneyAccount account)
                        in accounts.indexed)
                      _AccountRow(account: account, divided: index > 0),
                  ],
                ),
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  spacing: 8,
                  children: <Widget>[
                    Row(
                      children: <Widget>[
                        Text(
                          'Cards',
                          style: TextStyle(
                            fontSize: 13,
                            fontWeight: FontWeight.w500,
                            color: t.contentSecondary,
                          ),
                        ),
                        const SizedBox(width: 6),
                        InfoTip(
                          label: 'Cards',
                          children: <Widget>[
                            infoText(
                              'Only the card network and the last four digits are '
                              'stored. The number you type is used to work those out '
                              'and is never saved.',
                            ),
                            infoText(
                              'A credit card is a liability, so what you spend on it '
                              'is money you owe - it is never added to your cash and '
                              'bank balance.',
                            ),
                          ],
                        ),
                        const Spacer(),
                        AppTextLink(
                          label: _showArchived
                              ? 'Hide archived'
                              : 'Show archived',
                          fontSize: 12,
                          onTap: () =>
                              setState(() => _showArchived = !_showArchived),
                        ),
                      ],
                    ),
                    if (cards.isEmpty)
                      Text(
                        'No cards yet. Add one to record what you spend on it.',
                        style: TextStyle(fontSize: 13, color: t.contentMuted),
                      )
                    else
                      for (final (int index, PaymentCard card) in cards.indexed)
                        _CardRow(card: card, divided: index > 0),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// Register a card from its number.
  ///
  /// **The number never leaves this method.** It is typed into a controller that is
  /// disposed on the way out, sent once, and the response has no field for it - so
  /// there is nowhere in app state for it to end up even by accident.
  Future<void> _addCard() async {
    final TextEditingController label = TextEditingController();
    final TextEditingController number = TextEditingController();
    final TextEditingController holder = TextEditingController();
    final List<MoneyAccount> banks = widget.options.transferableAccounts
        .where((MoneyAccount a) => !a.isCard && a.kind == MoneyAccountKind.bank)
        .toList(growable: false);

    CardKind kind = CardKind.credit;
    String bankId = banks.isEmpty ? '' : banks.first.id;

    final bool? confirmed = await showAppModal<bool>(
      context: context,
      title: 'Add a card',
      description:
          'Only the network and the last four digits are kept. The number itself is '
          'never stored.',
      builder: (BuildContext context) => StatefulBuilder(
        builder: (BuildContext context, void Function(void Function()) rebuild) {
          final String digits = normaliseCardNumber(number.text);
          // Only complained about once it *could* be a card number - flagging a
          // check-digit failure after four digits would just mean "you have not
          // finished typing", shown as an error.
          final bool looksWrong =
              isPlausibleCardNumber(digits) && !passesLuhn(digits);

          return Column(
            spacing: 12,
            children: <Widget>[
              AppInput(
                label: 'Name this card',
                controller: label,
                autofocus: true,
                required: true,
                placeholder: 'HDFC Millennia',
                hint: 'How you refer to it. Shown with the last four digits.',
                onChanged: (_) => rebuild(() {}),
              ),
              AppSelect(
                label: 'Kind',
                value: kind.wire,
                options: const <SelectOption>[
                  SelectOption(value: 'credit', label: 'Credit card'),
                  SelectOption(value: 'debit', label: 'Debit card'),
                ],
                onChanged: (String next) =>
                    rebuild(() => kind = CardKind.parse(next)),
                hint: kind == CardKind.credit
                    ? 'Spending on it is money you owe.'
                    : 'Spends from a bank account you already have.',
              ),
              AppInput(
                label: 'Card number',
                controller: number,
                required: true,
                placeholder: '0000 0000 0000 0000',
                keyboardType: TextInputType.number,
                // Digits, spaces and dashes only, so a paste with letters in it is
                // rejected at the field rather than by the API.
                inputFormatters: <TextInputFormatter>[
                  FilteringTextInputFormatter.allow(RegExp(r'[\d\s-]')),
                ],
                // 19 digits plus the separators a person types between groups.
                maxLength: 25,
                // No `autofillHints`, deliberately. Offering the platform's saved
                // card here is the one "helpful" default that would undo the whole
                // arrangement - nothing in this app keeps a card number, so nothing
                // should invite the OS to hand one over or store one back.
                textStyle: const TextStyle(fontFeatures: tabularFigures),
                error: looksWrong
                    ? 'Check that number - a digit looks wrong.'
                    : null,
                hint: 'Only the network and the last four digits are kept.',
                onChanged: (_) => rebuild(() {}),
              ),
              AppInput(
                label: 'Name on the card',
                controller: holder,
                placeholder: 'Jhon Doe',
                // No `autofillHints` here either. This field *is* stored, but it sits
                // beside the number, and letting the platform treat this as a
                // saved-card form is exactly what would offer to fill - and keep -
                // the number next to it.
                hint: 'Optional. Kept as typed, unlike the number.',
              ),
              if (kind == CardKind.debit)
                AppSelect(
                  label: 'Draws on',
                  value: bankId,
                  options: <SelectOption>[
                    for (final MoneyAccount account in banks)
                      SelectOption(value: account.id, label: account.name),
                  ],
                  placeholder: banks.isEmpty ? 'No bank accounts yet' : null,
                  onChanged: (String next) => rebuild(() => bankId = next),
                  error: banks.isEmpty ? 'Add a bank account first.' : null,
                  hint:
                      'A debit card spends from an account you already have, so '
                      'it gets no account of its own.',
                ),
            ],
          );
        },
      ),
      footer: (BuildContext context) => <Widget>[
        AppButton(
          onPressed: () => Navigator.of(context).pop(false),
          variant: AppButtonVariant.ghost,
          label: 'Cancel',
        ),
        AppButton(
          onPressed: () => Navigator.of(context).pop(true),
          label: 'Add card',
        ),
      ],
    );

    final String typed = number.text;
    final String name = label.text.trim();
    final bool debit = kind == CardKind.debit;

    // Checked again on the way out rather than only inside the dialog: the modal's
    // "Add card" button is always live, so this is what actually stops a half-filled
    // form from becoming a request.
    if (confirmed != true ||
        name.isEmpty ||
        !isPlausibleCardNumber(normaliseCardNumber(typed)) ||
        (debit && bankId.isEmpty)) {
      label.dispose();
      number.dispose();
      holder.dispose();
      return;
    }

    try {
      final PaymentCard created = await ref
          .read(billingApiProvider)
          .addCard(
            label: name,
            kind: kind,
            cardNumber: typed,
            holderName: holder.text.trim(),
            bankAccountId: debit ? bankId : null,
          );

      // A credit card creates a liability account, so the chart of accounts and every
      // report built on it have genuinely changed. A debit card creates nothing.
      invalidateCards(ref, ledgerChanged: created.kind == CardKind.credit);

      if (!mounted) return;
      context.toastSuccess(
        'Added ${created.displayName}',
        description: created.kind == CardKind.credit
            ? '${created.network.label} credit card. What you spend on it is '
                  'recorded as money owed.'
            : '${created.network.label} debit card on ${created.accountName}.',
      );
    } catch (error) {
      if (mounted) context.toastApiError(error, 'Could not add the card');
    } finally {
      label.dispose();
      number.dispose();
    }
  }
}

/// One cash or bank account, with its details editable in place.
///
/// Editable here and not only on the add form, because the account most organizations
/// actually use - "Primary Bank Account" - is created by the chart template before anyone
/// has said which bank it is. Without this it would be the only account that could never
/// carry its own details.
class _AccountRow extends ConsumerStatefulWidget {
  const _AccountRow({required this.account, required this.divided});

  final MoneyAccount account;

  /// Whether to draw a rule above this row. False for the first one, so the list is
  /// divided *between* its items - what the web client's `divide-y` does. A rule above
  /// the first row would read as a heading underline instead.
  final bool divided;

  @override
  ConsumerState<_AccountRow> createState() => _AccountRowState();
}

class _AccountRowState extends ConsumerState<_AccountRow> {
  bool _editing = false;

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final MoneyAccount account = widget.account;

    return Container(
      padding: const EdgeInsets.symmetric(vertical: 10),
      decoration: BoxDecoration(
        border: widget.divided
            ? Border(top: BorderSide(color: t.border))
            : null,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: <Widget>[
          Row(
            spacing: 12,
            children: <Widget>[
              Icon(
                account.kind == MoneyAccountKind.cash
                    ? LucideIcons.wallet
                    : LucideIcons.landmark,
                size: 16,
                color: t.contentMuted,
              ),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: <Widget>[
                    Text.rich(
                      TextSpan(
                        children: <InlineSpan>[
                          TextSpan(text: account.name),
                          if (account.accountNumberLast4 != null)
                            TextSpan(
                              text: ' ··${account.accountNumberLast4}',
                              style: TextStyle(
                                color: t.contentMuted,
                                fontFeatures: const <FontFeature>[
                                  FontFeature.tabularFigures(),
                                ],
                              ),
                            ),
                        ],
                      ),
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 13, color: t.content),
                    ),
                    Text(
                      account.subtitle,
                      overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 11, color: t.contentMuted),
                    ),
                  ],
                ),
              ),
              if (account.isDefault)
                const AppBadge('Default', tone: BadgeTone.primary),
              // Cash in hand has no bank, no number and no holder, so there is nothing
              // here to open.
              if (account.kind != MoneyAccountKind.cash)
                AppButton(
                  onPressed: () => setState(() => _editing = !_editing),
                  variant: AppButtonVariant.link,
                  size: AppButtonSize.sm,
                  label: _editing
                      ? 'Close'
                      : account.bankName == null
                      ? 'Add details'
                      : 'Edit',
                ),
            ],
          ),
          if (_editing)
            _BankDetailsForm(
              account: account,
              onDone: () => setState(() => _editing = false),
            ),
        ],
      ),
    );
  }
}

/// Which bank, whose name, which number.
///
/// Loads the existing values first, **including the full account number** - this is the one
/// place the app fetches it, and it does so because the alternative is an edit form that
/// silently wipes a number the user cannot see. Saving replaces the whole set, so clearing
/// a field clears it on the server.
class _BankDetailsForm extends ConsumerStatefulWidget {
  const _BankDetailsForm({required this.account, required this.onDone});

  final MoneyAccount account;
  final VoidCallback onDone;

  @override
  ConsumerState<_BankDetailsForm> createState() => _BankDetailsFormState();
}

class _BankDetailsFormState extends ConsumerState<_BankDetailsForm> {
  final TextEditingController _bank = TextEditingController();
  final TextEditingController _holder = TextEditingController();
  final TextEditingController _number = TextEditingController();

  /// Whether the fetched values have been copied into the controllers yet.
  ///
  /// A one-shot latch rather than a rebuild-time assignment: the provider can emit more
  /// than once, and re-seeding on a later emission would throw away whatever the user had
  /// typed in the meantime.
  bool _seeded = false;
  bool _saving = false;

  @override
  void dispose() {
    _bank.dispose();
    _holder.dispose();
    _number.dispose();
    super.dispose();
  }

  Future<void> _save() async {
    setState(() => _saving = true);
    try {
      await ref
          .read(billingApiProvider)
          .saveBankDetails(
            widget.account.id,
            bankName: _bank.text.trim(),
            holderName: _holder.text.trim(),
            accountNumber: _number.text.trim(),
          );
      invalidateBankDetails(ref);
      if (!mounted) return;
      context.toastSuccess('Saved details for ${widget.account.name}');
      widget.onDone();
    } catch (error) {
      if (mounted) context.toastApiError(error, 'Could not save the details');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final AsyncValue<BankDetails> details = ref.watch(
      bankDetailsProvider(widget.account.id),
    );

    final BankDetails? loaded = details.valueOrNull;
    if (loaded != null && !_seeded) {
      _seeded = true;
      _bank.text = loaded.bankName ?? '';
      _holder.text = loaded.holderName ?? '';
      _number.text = loaded.accountNumber ?? '';
    }

    final bool loading = loaded == null;

    return Container(
      margin: const EdgeInsets.only(top: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: t.surfaceSunken,
        borderRadius: BorderRadius.circular(Radii.lg),
        border: Border.all(color: t.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        spacing: 12,
        children: <Widget>[
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            spacing: 12,
            children: <Widget>[
              Expanded(
                child: AppInput(
                  label: 'Bank name',
                  controller: _bank,
                  autofocus: true,
                  enabled: !loading,
                  placeholder: 'HDFC Bank',
                ),
              ),
              Expanded(
                child: AppInput(
                  label: 'Account holder',
                  controller: _holder,
                  enabled: !loading,
                  placeholder: 'Jhon Doe',
                ),
              ),
            ],
          ),
          AppInput(
            label: 'Account number',
            controller: _number,
            enabled: !loading,
            placeholder: '50100123454321',
            keyboardType: TextInputType.number,
            inputFormatters: <TextInputFormatter>[
              FilteringTextInputFormatter.allow(RegExp(r'[\d\s-]')),
            ],
            textStyle: const TextStyle(fontFeatures: tabularFigures),
            hint: loading
                ? 'Loading…'
                : 'Stored encrypted. Clear it to remove it.',
          ),
          Row(
            mainAxisAlignment: MainAxisAlignment.end,
            spacing: 8,
            children: <Widget>[
              AppButton(
                onPressed: _saving ? null : widget.onDone,
                variant: AppButtonVariant.ghost,
                label: 'Cancel',
              ),
              AppButton(
                onPressed: loading || _saving ? null : _save,
                loading: _saving,
                label: _saving ? 'Saving…' : 'Save details',
              ),
            ],
          ),
        ],
      ),
    );
  }
}

class _CardRow extends ConsumerStatefulWidget {
  const _CardRow({required this.card, required this.divided});

  final PaymentCard card;

  /// See [_AccountRow.divided].
  final bool divided;

  @override
  ConsumerState<_CardRow> createState() => _CardRowState();
}

class _CardRowState extends ConsumerState<_CardRow> {
  bool _busy = false;

  Future<void> _toggle() async {
    setState(() => _busy = true);
    final PaymentCard card = widget.card;
    try {
      final PaymentCard updated = card.isActive
          ? await ref.read(billingApiProvider).archiveCard(card.id)
          : await ref.read(billingApiProvider).restoreCard(card.id);

      // The card's own liability account is untouched either way, so the ledger has
      // not changed - only which cards the pickers offer.
      invalidateCards(ref);

      if (!mounted) return;
      context.toastSuccess(
        updated.isActive
            ? 'Restored ${updated.label}'
            : 'Archived ${updated.label}',
        description: updated.isActive
            ? 'It can be chosen when recording a payment again.'
            : 'Past entries still name it; it is no longer offered.',
      );
    } catch (error) {
      if (mounted) context.toastApiError(error, 'Could not update the card');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final AppTokens t = context.tokens;
    final PaymentCard card = widget.card;

    return Opacity(
      opacity: card.isActive ? 1 : 0.6,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          border: widget.divided
              ? Border(top: BorderSide(color: t.border))
              : null,
        ),
        child: Row(
          spacing: 12,
          children: <Widget>[
            Icon(LucideIcons.creditCard, size: 16, color: t.contentMuted),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: <Widget>[
                  Text.rich(
                    TextSpan(
                      children: <InlineSpan>[
                        TextSpan(text: card.label),
                        TextSpan(
                          text: ' ··${card.last4}',
                          style: TextStyle(
                            color: t.contentMuted,
                            fontFeatures: const <FontFeature>[
                              FontFeature.tabularFigures(),
                            ],
                          ),
                        ),
                      ],
                    ),
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 13, color: t.content),
                  ),
                  Text(
                    card.subtitle,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 11, color: t.contentMuted),
                  ),
                ],
              ),
            ),
            AppBadge(
              card.kind.label,
              tone: card.kind == CardKind.credit
                  ? BadgeTone.warning
                  : BadgeTone.info,
            ),
            // An AppButton rather than an AppTextLink, whose `onTap` is non-nullable
            // and so has no disabled state. Double-firing an archive is harmless, but
            // a control that stays live while its request is in flight looks broken.
            AppButton(
              onPressed: _busy ? null : _toggle,
              variant: AppButtonVariant.link,
              size: AppButtonSize.sm,
              label: card.isActive ? 'Archive' : 'Restore',
              semanticLabel: card.isActive
                  ? 'Archive ${card.label}'
                  : 'Restore ${card.label}',
            ),
          ],
        ),
      ),
    );
  }
}
