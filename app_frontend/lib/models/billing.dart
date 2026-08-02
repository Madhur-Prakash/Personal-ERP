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
  });

  final String id;
  final String name;
  final bool isDefault;

  factory MoneyAccount.fromJson(Json json) => MoneyAccount(
    id: str(json, 'id'),
    name: str(json, 'name'),
    isDefault: boolOf(json, 'is_default'),
  );
}

class BillingOptions {
  const BillingOptions({
    required this.categories,
    required this.moneyAccounts,
    required this.today,
    required this.currency,
  });

  final List<Category> categories;
  final List<MoneyAccount> moneyAccounts;

  /// Today in the organization's timezone, not the server's UTC date.
  final String today;
  final String currency;

  factory BillingOptions.fromJson(Json json) => BillingOptions(
    categories: listOf(json, 'categories', Category.fromJson),
    moneyAccounts: listOf(json, 'money_accounts', MoneyAccount.fromJson),
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
