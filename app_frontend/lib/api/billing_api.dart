import '../core/api_client.dart';
import '../models/billing.dart';
import '../models/json.dart';
import '../models/page.dart';

/// Billing bindings - money in and money out.
///
/// Amounts are `String`, as everywhere else: these figures post to the ledger.
class BillingApi {
  const BillingApi(this._client);

  final ApiClient _client;

  Future<BillingOptions> options() async =>
      BillingOptions.fromJson(await _client.get<Json>('/billing/options'));

  Future<Paged<BillingEntry>> list({
    int page = 1,
    int pageSize = 25,
    Direction? direction,
    String? query,
  }) async => Paged<BillingEntry>.fromJson(
    await _client.get<Json>(
      '/billing',
      query: <String, dynamic>{
        'page': page,
        'page_size': pageSize,
        'direction': direction?.wire,
        'q': query,
      },
    ),
    BillingEntry.fromJson,
  );

  Future<BillingSummary> summary() async =>
      BillingSummary.fromJson(await _client.get<Json>('/billing/summary'));

  Future<BillingEntry> record({
    required Direction direction,
    required String amount,
    required String description,
    required String party,
    String? entryDate,
    String? categoryId,
    String? moneyAccountId,
    String? reference,
  }) async => BillingEntry.fromJson(
    await _client.post<Json>(
      '/billing',
      body: <String, dynamic>{
        'direction': direction.wire,
        'amount': amount,
        'description': description,
        // Required - the API rejects a blank.
        'party': party,
        'entry_date': ?entryDate,
        if (categoryId != null && categoryId.isNotEmpty)
          'category_id': categoryId,
        if (moneyAccountId != null && moneyAccountId.isNotEmpty)
          'money_account_id': moneyAccountId,
        if (reference != null && reference.isNotEmpty) 'reference': reference,
      },
    ),
  );

  /// Add a category from a name alone.
  ///
  /// The account code, parent group, and subtype are derived server-side - nobody
  /// should need to understand the chart of accounts to file a payment under a name
  /// the built-in list does not have.
  Future<Category> createCategory(String name, Direction direction) async =>
      Category.fromJson(
        await _client.post<Json>(
          '/billing/categories',
          body: <String, dynamic>{'name': name, 'direction': direction.wire},
        ),
      );

  /// Add a place money can sit - a second bank, a UPI wallet, a partner's petty
  /// cash. The seeded chart only has one till and one current account.
  Future<MoneyAccount> createMoneyAccount(String name, MoneyKind kind) async =>
      MoneyAccount.fromJson(
        await _client.post<Json>(
          '/billing/money-accounts',
          body: <String, dynamic>{'name': name, 'kind': kind.wire},
        ),
      );

  Future<List<PaymentCard>> cards({bool includeArchived = false}) async {
    final List<dynamic> rows = await _client.get<List<dynamic>>(
      '/billing/cards',
      query: <String, dynamic>{if (includeArchived) 'include_archived': true},
    );
    return rows.cast<Json>().map(PaymentCard.fromJson).toList(growable: false);
  }

  /// Register a card from its number.
  ///
  /// **The number goes up once and is never stored** - not by the server, and not
  /// here. [PaymentCard] has no field for it, so there is nowhere for it to end up
  /// in app state; only the network and the last four digits come back. The caller
  /// is expected to clear whatever field it was typed into as soon as this
  /// returns.
  Future<PaymentCard> addCard({
    required String label,
    required CardKind kind,
    required String cardNumber,
    String? bankAccountId,
  }) async => PaymentCard.fromJson(
    await _client.post<Json>(
      '/billing/cards',
      body: <String, dynamic>{
        'label': label,
        'kind': kind.wire,
        'card_number': cardNumber,
        // Required for a debit card, ignored for a credit card: a debit card is a
        // way of using an account you already have, so it names that account
        // instead of creating one that would double-count the same money.
        if (kind == CardKind.debit &&
            bankAccountId != null &&
            bankAccountId.isNotEmpty)
          'bank_account_id': bankAccountId,
      },
    ),
  );

  /// Stop offering a card without deleting it - past entries still name it.
  Future<PaymentCard> archiveCard(String id) async => PaymentCard.fromJson(
    await _client.post<Json>('/billing/cards/$id/archive'),
  );

  Future<PaymentCard> restoreCard(String id) async => PaymentCard.fromJson(
    await _client.post<Json>('/billing/cards/$id/restore'),
  );

  /// Move money between two of your own accounts.
  ///
  /// No category, and that is not an omission: moving your own money is neither
  /// earning nor spending it, so there is no income or expense line for it to go
  /// against. It is tagged so the money-in and money-out totals ignore it -
  /// counting a transfer would show income that never arrived from anywhere.
  Future<Transfer> transfer({
    required String fromAccountId,
    required String toAccountId,
    required String amount,
    String? entryDate,
    String? description,
  }) async => Transfer.fromJson(
    await _client.post<Json>(
      '/billing/transfers',
      body: <String, dynamic>{
        'from_account_id': fromAccountId,
        'to_account_id': toAccountId,
        'amount': amount,
        'entry_date': ?entryDate,
        if (description != null && description.isNotEmpty)
          'description': description,
      },
    ),
  );

  /// Cancel an entry by posting its mirror image.
  ///
  /// There is no delete and no edit - a posted ledger entry is immutable, so an
  /// opposite entry is the only honest undo.
  Future<BillingEntry> reverse(String id, {String? reason}) async =>
      BillingEntry.fromJson(
        await _client.post<Json>(
          '/billing/$id/reverse',
          body: <String, dynamic>{
            if (reason != null && reason.isNotEmpty) 'reason': reason,
          },
        ),
      );
}
