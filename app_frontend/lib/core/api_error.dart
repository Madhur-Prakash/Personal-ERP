import 'package:dio/dio.dart';

/// A normalised API failure.
///
/// Every call site gets the same shape - a machine-readable [code], a displayable
/// [message], and [fieldErrors] ready to attach to a form - instead of each one
/// unwrapping `error.response.data['error']['details']['fields']` for itself.
///
/// Mirrors `frontend/src/lib/api.ts`, including the two awkward cases: the
/// password policy answers with a *list* of reasons rather than a field map, and
/// a request that never reached the app has no envelope at all.
class ApiError implements Exception {
  ApiError(
    this.message, {
    this.code = 'unknown_error',
    this.status = 0,
    this.details = const <String, dynamic>{},
    this.requestId,
  });

  final String message;
  final String code;
  final int status;
  final Map<String, dynamic> details;

  /// The backend's per-request id. Shown on the error screen because it is what
  /// makes a user report actionable - it maps directly to the log lines for that
  /// exact request.
  final String? requestId;

  /// Per-field messages from a 422, keyed by field name.
  Map<String, String> get fieldErrors {
    final Object? fields = details['fields'];
    if (fields is Map) {
      return fields.map(
        (Object? key, Object? value) =>
            MapEntry<String, String>('$key', '$value'),
      );
    }
    // The password policy returns a list of reasons rather than a field map.
    final Object? password = details['password'];
    if (password is List) {
      return <String, String>{'password': password.join('. ')};
    }
    return const <String, String>{};
  }

  bool get isValidation => status == 422;
  bool get isUnauthenticated => status == 401;
  bool get isForbidden => status == 403;
  bool get isNotFound => status == 404;

  /// True for conditions a retry might resolve - offline, timeout, 5xx.
  bool get isRetryable => status == 0 || status >= 500;

  /// Normalise anything thrown by Dio, or by us, into one of these.
  static ApiError from(Object error) {
    if (error is ApiError) return error;

    if (error is DioException) {
      final Response<dynamic>? response = error.response;
      final Object? body = response?.data;

      if (body is Map && body['error'] is Map) {
        final Map<Object?, Object?> envelope =
            body['error'] as Map<Object?, Object?>;
        final Object? rawDetails = envelope['details'];
        return ApiError(
          '${envelope['message'] ?? 'Something went wrong'}',
          code: '${envelope['code'] ?? 'unknown_error'}',
          status: response?.statusCode ?? 0,
          details: rawDetails is Map
              ? rawDetails.map(
                  (Object? k, Object? v) => MapEntry<String, dynamic>('$k', v),
                )
              : const <String, dynamic>{},
          requestId: envelope['request_id'] as String?,
        );
      }

      // No envelope: the request never reached the app - the host is down, the
      // laptop is offline, a proxy answered. Say so plainly rather than
      // rendering "null".
      if (response == null) {
        final bool timedOut =
            error.type == DioExceptionType.connectionTimeout ||
            error.type == DioExceptionType.sendTimeout ||
            error.type == DioExceptionType.receiveTimeout;
        return ApiError(
          timedOut
              ? 'The request timed out. Check your connection and try again.'
              : 'Could not reach the server. Check your connection and try again.',
          code: 'network_error',
        );
      }

      return ApiError(
        error.message ?? 'Request failed',
        code: 'http_error',
        status: response.statusCode ?? 0,
      );
    }

    return ApiError(error is Exception ? '$error' : 'Something went wrong');
  }

  @override
  String toString() => message;
}
