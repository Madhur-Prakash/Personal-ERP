import 'json.dart';

/// Billing contracts - money in and money out.
enum Direction {
  in_('in'),
  out('out');

  const Direction(this.wire);

  final String wire;

  static Direction parse(String value) =>
      value == 'out' ? Direction.out : Direction.in_;

  bool get isIn => this == Direction.in_;
}

/// How a money account reconciles: cash against a count, a bank against a
/// statement.
enum MoneyKind {
  cash('cash'),
  bank('bank');

  const MoneyKind(this.wire);

  final String wire;
}

/// What a place money sits in actually *is*.
///
/// Wider than [MoneyKind], which is only about *creating* a cash box or a bank
/// account. This is the read side, and [creditCard] is why it exists: a credit
/// card belongs in the same picker while being the opposite accounting object.
/// Spending on one increases what you owe rather than reducing what you hold, so
/// it must never be totalled beside a bank balance.
enum MoneyAccountKind {
  cash('cash'),
  bank('bank'),
  creditCard('credit_card');

  const MoneyAccountKind(this.wire);

  final String wire;

  /// Unknown values fall back to [bank] rather than throwing. A server that grew
  /// a fourth kind should not make the picker unusable on an older build - and
  /// [bank] is the safer guess than [cash], because it claims less.
  static MoneyAccountKind parse(String? value) => switch (value) {
    'cash' => MoneyAccountKind.cash,
    'credit_card' => MoneyAccountKind.creditCard,
    _ => MoneyAccountKind.bank,
  };

  bool get isCard => this == MoneyAccountKind.creditCard;
}

enum CardKind {
  credit('credit'),
  debit('debit');

  const CardKind(this.wire);

  final String wire;

  static CardKind parse(String value) =>
      value == 'debit' ? CardKind.debit : CardKind.credit;

  String get label => this == CardKind.credit ? 'Credit' : 'Debit';
}

/// The card scheme, for display only.
///
/// [other] is not "unknown to us, therefore broken": the card works perfectly
/// well, the software simply does not claim to recognise the scheme from its
/// leading digits. Detection is the server's job - it owns the table of issuer
/// ranges, and a second copy here would drift.
enum CardNetwork {
  visa('visa', 'Visa'),
  mastercard('mastercard', 'Mastercard'),
  rupay('rupay', 'RuPay'),
  amex('amex', 'Amex'),
  discover('discover', 'Discover'),
  diners('diners', 'Diners Club'),
  jcb('jcb', 'JCB'),
  maestro('maestro', 'Maestro'),
  other('other', 'Card');

  const CardNetwork(this.wire, this.label);

  final String wire;
  final String label;

  static CardNetwork parse(String? value) => CardNetwork.values.firstWhere(
    (CardNetwork network) => network.wire == value,
    orElse: () => CardNetwork.other,
  );
}

class Category {
  const Category({
    required this.id,
    required this.name,
    required this.direction,
    required this.group,
    required this.isDefault,
  });

  final String id;
  final String name;

  /// Income categories cannot take money out, and vice versa.
  final Direction direction;

  /// The parent group's name, used to group the picker - nearly eighty flat
  /// options is a list nobody reads to the end of.
  final String group;
  final bool isDefault;

  factory Category.fromJson(Json json) => Category(
    id: str(json, 'id'),
    name: str(json, 'name'),
    direction: Direction.parse(str(json, 'direction')),
    group: strOrNull(json, 'group') ?? '',
    isDefault: boolOf(json, 'is_default'),
  );
}

class MoneyAccount {
  const MoneyAccount({
    required this.id,
    required this.name,
    required this.isDefault,
    required this.kind,
    this.cardId,
    this.cardLast4,
  });

  final String id;
  final String name;
  final bool isDefault;

  /// Cash, a bank, or a credit card. See [MoneyAccountKind].
  final MoneyAccountKind kind;

  /// Set when a card is what identifies this option.
  ///
  /// **A debit card arrives with the same [id] as the bank account it draws on**,
  /// because it is not a separate place money lives - it is another way of
  /// touching the same one. So [id] alone cannot tell "HDFC Current" from
  /// "HDFC Debit ··4242", and this is the field that separates them. See [key].
  final String? cardId;
  final String? cardLast4;

  bool get isCard => cardId != null;

  /// A stable, unique identity for one entry in a picker.
  ///
  /// **Not [id], and that is load-bearing.** Two dropdown entries sharing a value
  /// is a picker that cannot represent the user's choice - selecting the debit
  /// card would silently snap back to the bank account. Post [id] to the API and
  /// use this for the widget's value.
  String get key => cardId ?? id;

  factory MoneyAccount.fromJson(Json json) => MoneyAccount(
    id: str(json, 'id'),
    name: str(json, 'name'),
    isDefault: boolOf(json, 'is_default'),
    kind: MoneyAccountKind.parse(strOrNull(json, 'kind')),
    cardId: strOrNull(json, 'card_id'),
    cardLast4: strOrNull(json, 'card_last4'),
  );
}

/// A card on file. **Never carries a number** - see the backend's `cards.py`.
class PaymentCard {
  const PaymentCard({
    required this.id,
    required this.label,
    required this.kind,
    required this.network,
    required this.last4,
    required this.accountId,
    required this.accountName,
    required this.isActive,
  });

  final String id;
  final String label;
  final CardKind kind;
  final CardNetwork network;

  /// Four digits as a `String` - a card ending 0042 is not the number 42.
  final String last4;

  /// The ledger account this card posts to: its own liability account for a
  /// credit card, the bank account it draws on for a debit card.
  final String accountId;
  final String accountName;
  final bool isActive;

  String get displayName => '$label ··$last4';

  factory PaymentCard.fromJson(Json json) => PaymentCard(
    id: str(json, 'id'),
    label: str(json, 'label'),
    kind: CardKind.parse(str(json, 'kind')),
    network: CardNetwork.parse(strOrNull(json, 'network')),
    last4: strOrNull(json, 'last4') ?? '',
    accountId: str(json, 'account_id'),
    accountName: strOrNull(json, 'account_name') ?? '',
    isActive: boolOf(json, 'is_active'),
  );
}

/// One account moved to another. No category, because moving your own money is
/// neither earning nor spending it.
class Transfer {
  const Transfer({
    required this.entryId,
    required this.amount,
    required this.description,
    required this.fromAccountName,
    required this.toAccountName,
  });

  final String entryId;
  final String amount;
  final String description;
  final String fromAccountName;
  final String toAccountName;

  factory Transfer.fromJson(Json json) => Transfer(
    entryId: str(json, 'entry_id'),
    amount: money(json, 'amount'),
    description: strOrNull(json, 'description') ?? '',
    fromAccountName: strOrNull(json, 'from_account_name') ?? '',
    toAccountName: strOrNull(json, 'to_account_name') ?? '',
  );
}

class BillingOptions {
  const BillingOptions({
    required this.categories,
    required this.moneyAccounts,
    required this.cards,
    required this.today,
    required this.currency,
  });

  final List<Category> categories;
  final List<MoneyAccount> moneyAccounts;

  /// Cards on file. Separate from [moneyAccounts] because the two answer
  /// different questions: that list is "where can this payment go", this one is
  /// "what have I registered" - and an archived card belongs in neither.
  final List<PaymentCard> cards;

  /// Today in the organization's timezone, not the server's UTC date.
  final String today;
  final String currency;

  /// The accounts a transfer can move between, one entry per real account.
  ///
  /// Deduplicated by [MoneyAccount.id], which drops debit cards and keeps
  /// everything else: a debit card *is* the bank account it draws on, so offering
  /// both would let someone pick a "from" and a "to" that are the same account
  /// under two names. Credit cards survive, because they own a distinct account -
  /// and paying a card bill off a bank account is the transfer people most want to
  /// record.
  ///
  /// Cash and bank accounts come first from the API, so the survivor of a
  /// duplicated pair is the bank account rather than the card. That ordering is
  /// relied on here.
  List<MoneyAccount> get transferableAccounts {
    final Set<String> seen = <String>{};
    return moneyAccounts
        .where((MoneyAccount account) => seen.add(account.id))
        .toList();
  }

  factory BillingOptions.fromJson(Json json) => BillingOptions(
    categories: listOf(json, 'categories', Category.fromJson),
    moneyAccounts: listOf(json, 'money_accounts', MoneyAccount.fromJson),
    cards: listOf(json, 'cards', PaymentCard.fromJson),
    today: str(json, 'today'),
    currency: strOrNull(json, 'currency') ?? 'INR',
  );
}

class BillingEntry {
  const BillingEntry({
    required this.id,
    this.entryNumber,
    required this.date,
    required this.direction,
    required this.amount,
    required this.description,
    this.reference,
    this.party,
    required this.categoryName,
    required this.moneyAccountName,
    required this.isReversed,
  });

  final String id;

  /// The ledger's own number, so the entry can be found in the journal.
  final String? entryNumber;
  final String date;
  final Direction direction;
  final String amount;
  final String description;
  final String? reference;

  /// Who it came from (money in) or went to (money out). Free text, not a record.
  final String? party;

  final String categoryName;
  final String moneyAccountName;

  /// Cancelled by a reversal. Still listed - the cancellation is part of the
  /// record.
  final bool isReversed;

  factory BillingEntry.fromJson(Json json) => BillingEntry(
    id: str(json, 'id'),
    entryNumber: strOrNull(json, 'entry_number'),
    date: str(json, 'date'),
    direction: Direction.parse(str(json, 'direction')),
    amount: money(json, 'amount'),
    description: str(json, 'description'),
    reference: strOrNull(json, 'reference'),
    party: strOrNull(json, 'party'),
    categoryName: strOrNull(json, 'category_name') ?? '',
    moneyAccountName: strOrNull(json, 'money_account_name') ?? '',
    isReversed: boolOf(json, 'is_reversed'),
  );
}

class BillingSummary {
  const BillingSummary({
    required this.fromDate,
    required this.toDate,
    required this.moneyIn,
    required this.moneyOut,
    required this.net,
    required this.entryCount,
  });

  final String fromDate;
  final String toDate;
  final String moneyIn;
  final String moneyOut;
  final String net;
  final int entryCount;

  factory BillingSummary.fromJson(Json json) => BillingSummary(
    fromDate: str(json, 'from_date'),
    toDate: str(json, 'to_date'),
    moneyIn: money(json, 'money_in'),
    moneyOut: money(json, 'money_out'),
    net: money(json, 'net'),
    entryCount: intOf(json, 'entry_count'),
  );
}
