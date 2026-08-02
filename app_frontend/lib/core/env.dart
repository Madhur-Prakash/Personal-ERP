/// Validated build-time environment.
///
/// The web app parses `import.meta.env` with Zod and throws on a bad value,
/// because a missing base URL silently becomes `undefined` and surfaces later as
/// a request to `undefined/api/v1/auth/login`. The desktop equivalent is
/// `--dart-define`, which has the same failure mode: a typo'd key just yields the
/// default, and the app talks to the wrong host without complaint.
///
/// So the same validation runs here, at first access, and names the variable it
/// is unhappy about.
///
/// ```
/// flutter run -d windows \
///   --dart-define=API_BASE_URL=https://erp.example.com \
///   --dart-define=API_V1_PREFIX=/api/v1
/// ```
abstract final class Env {
  /// **`127.0.0.1`, not `localhost`, and that matters.**
  ///
  /// `docker compose` publishes a port on IPv4 only, while `localhost` on Windows resolves
  /// to `::1` before `127.0.0.1`. A client that takes the first answer gets "connection
  /// refused" against a server that is running perfectly well - and because a failed
  /// session restore is indistinguishable from "not signed in", it presents as the sign-in
  /// screen with no explanation at all.
  ///
  /// The web app does not hit this: it is *served from* the origin it calls, so the browser
  /// never resolves a hostname for the API. A desktop client has no such luck, so it names
  /// the address family it means.
  static const String _rawBaseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'http://127.0.0.1:8000',
  );

  static const String _rawPrefix = String.fromEnvironment(
    'API_V1_PREFIX',
    defaultValue: '/api/v1',
  );

  static const String appName = String.fromEnvironment(
    'APP_NAME',
    defaultValue: 'Personal ERP',
  );

  /// True in a debug or profile build. Gates the stack trace on the error screen,
  /// which in a release build would leak internals to no benefit.
  static const bool isDev = !bool.fromEnvironment('dart.vm.product');

  static final String apiBaseUrl = _validatedBaseUrl();
  static final String apiPrefix = _validatedPrefix();

  /// `http://host:8000/api/v1` - what the Dio instance is rooted at.
  static String get apiRoot => '$apiBaseUrl$apiPrefix';

  /// Absolute URL for a versioned API path.
  static String url(String path) =>
      '$apiRoot${path.startsWith('/') ? path : '/$path'}';

  static String _validatedBaseUrl() {
    final Uri? parsed = Uri.tryParse(_rawBaseUrl);
    if (parsed == null || !parsed.hasScheme || parsed.host.isEmpty) {
      throw StateError(
        'Invalid frontend environment:\n'
        '  API_BASE_URL: must be an absolute URL, got "$_rawBaseUrl"',
      );
    }
    // Trailing slash stripped so joining a path never yields a double slash,
    // which some proxies treat as a different route.
    return _rawBaseUrl.endsWith('/')
        ? _rawBaseUrl.substring(0, _rawBaseUrl.length - 1)
        : _rawBaseUrl;
  }

  static String _validatedPrefix() {
    if (!_rawPrefix.startsWith('/')) {
      throw StateError(
        'Invalid frontend environment:\n'
        '  API_V1_PREFIX: must start with "/", got "$_rawPrefix"',
      );
    }
    return _rawPrefix;
  }
}
