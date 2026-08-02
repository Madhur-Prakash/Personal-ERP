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
