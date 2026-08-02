import 'dart:async';

import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/auth_api.dart';
import '../core/api_client.dart';
import '../core/locale_settings.dart';
import '../models/auth.dart';
import 'providers.dart';

/// Session state for the app.
///
/// On start it attempts one silent refresh: the access token lives in memory and is
/// gone after a quit, but the persisted refresh cookie is not, so exchanging it
/// restores the session without the user re-entering anything. Failure just means
/// "signed out", which is the ordinary first-launch case.
///
/// [isLoading] exists so route guards can distinguish "not signed in" from "we do
/// not know yet". Without it, every launch would bounce an authenticated user to the
/// sign-in screen for a frame before the refresh completes - and worse, a deep link
/// would be resolved against the wrong answer.
class AuthState {
  const AuthState({this.user, this.isLoading = true});

  final AuthenticatedUser? user;

  /// True until the initial session restore settles. Gate routing on this.
  final bool isLoading;

  bool get isAuthenticated => user != null;

  OrganizationSummary? get organization => user?.activeOrganization;

  /// Permission check for conditionally rendering UI.
  ///
  /// The server enforces every one of these on every request; this only decides
  /// whether to *offer* something. Hiding a control the caller cannot use is better
  /// than showing one that 403s.
  bool can(String permission) =>
      user?.permissions.contains(permission) ?? false;

  AuthState copyWith({
    AuthenticatedUser? user,
    bool? isLoading,
    bool clearUser = false,
  }) {
    return AuthState(
      user: clearUser ? null : (user ?? this.user),
      isLoading: isLoading ?? this.isLoading,
    );
  }
}

class AuthController extends StateNotifier<AuthState> {
  AuthController(this._client, this._api, this._ref)
    : super(const AuthState()) {
    // Called by the HTTP layer when a refresh fails - the session is genuinely
    // over, not merely stale.
    _client.onSessionExpired = _clearLocally;
    _restore();
  }

  final ApiClient _client;
  final AuthApi _api;
  final Ref _ref;

  Future<void> _restore() async {
    try {
      final bool restored = await _client.bootstrapSession();
      if (!restored) {
        state = const AuthState(isLoading: false);
        return;
      }
      final AuthenticatedUser principal = await _api.me();
      _applyPrincipal(principal);
      state = state.copyWith(isLoading: false);
    } catch (_) {
      await _client.clearSession();
      _resetLocale();
      state = const AuthState(isLoading: false);
    }
  }

  /// Set the principal, and adopt their organization's currency, timezone, and
  /// financial year at the same moment.
  ///
  /// One method rather than a state assignment plus a reminder, because the two must
  /// never drift: the formatters read those settings, so a principal set without them
  /// renders every amount on the next frame in the wrong currency.
  void _applyPrincipal(AuthenticatedUser principal) {
    final OrganizationSummary? organization = principal.activeOrganization;
    if (organization == null) {
      setLocaleSettings(reset: true);
    } else {
      setLocaleSettings(
        currency: organization.currency,
        timezone: organization.timezone,
        fiscalYearStartMonth: organization.fiscalYearStartMonth,
      );
    }
    state = AuthState(user: principal, isLoading: false);
  }

  void _resetLocale() => setLocaleSettings(reset: true);

  /// Store the result of a successful sign-in.
  void applySession(TokenResponse tokens) {
    _client.accessToken = tokens.accessToken;
    _applyPrincipal(tokens.user);
  }

  Future<void> signOut({bool allDevices = false}) async {
    try {
      await _api.logout(allDevices: allDevices);
    } catch (_) {
      // Sign out locally even if the call fails - the user asked to leave, and the
      // token expires on its own regardless.
    } finally {
      // Awaited rather than left to `_clearLocally`'s fire-and-forget: the user asked to
      // leave, so the cookie must be off disk before this future completes. Clearing twice
      // would be harmless but says the ownership is unclear, so this is the one caller that
      // waits.
      await _client.clearSession();
      _clearLocally();
    }
  }

  /// Re-fetch the principal after a change to profile, organization, or permissions.
  Future<void> refresh() async {
    try {
      _applyPrincipal(await _api.me());
    } catch (_) {
      await _client.clearSession();
      _clearLocally();
    }
  }

  Future<void> switchOrganization(String organizationId) async {
    final TokenResponse tokens = await _api.switchOrganization(organizationId);
    _client.accessToken = tokens.accessToken;
    _applyPrincipal(tokens.user);
    // Every cached query was scoped to the previous organization, so all of them
    // are wrong now rather than merely stale.
    clearCache(_ref);
  }

  /// Tear down after the session has ended without the user asking - an expired or revoked
  /// refresh token.
  ///
  /// **The jar is emptied too, and that is not just tidiness.** The cookie that failed is
  /// dead: the backend has either expired it or revoked its whole lineage after detecting
  /// reuse. Leaving it on disk means every subsequent launch spends a round trip presenting
  /// a credential that is guaranteed to be refused, and the sign-in screen arrives a beat
  /// later than it needs to for no reason.
  void _clearLocally() {
    // Fire-and-forget: this is called from the HTTP layer's synchronous callback, and the
    // rest of the teardown must not wait on a disk write. `signOut` has already awaited the
    // same call; repeating it costs one no-op directory delete and keeps this method correct
    // on its own, which matters because the expiry path has no other opportunity.
    unawaited(_client.clearSession());
    _resetLocale();
    state = const AuthState(isLoading: false);
    // Drop every cached query: leaving another user's figures in memory after a
    // sign-out on a shared machine would show them to the next person.
    clearCache(_ref);
  }
}

final StateNotifierProvider<AuthController, AuthState> authControllerProvider =
    StateNotifierProvider<AuthController, AuthState>(
      (Ref ref) => AuthController(
        ref.watch(apiClientProvider),
        ref.watch(authApiProvider),
        ref,
      ),
    );
