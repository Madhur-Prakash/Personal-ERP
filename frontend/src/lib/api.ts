import axios, {
  type AxiosError,
  type AxiosInstance,
  type AxiosRequestConfig,
  type InternalAxiosRequestConfig,
} from 'axios';

import { env } from '@/lib/env';

/**
 * The HTTP client, and the token lifecycle around it.
 *
 * **Where the access token lives: in memory only.** Not `localStorage`, not
 * `sessionStorage`, not a readable cookie. Any XSS on the page can read those,
 * and a stolen token is valid until it expires. A module-scoped variable dies
 * with the tab, which is the point.
 *
 * That raises the obvious question - how does a page reload stay signed in? The
 * refresh token, which the server sets as an `HttpOnly; Secure; SameSite=Strict`
 * cookie that JavaScript cannot read at all. On boot the app calls
 * `/auth/refresh` once; the browser attaches the cookie, and a fresh access
 * token comes back. So the long-lived credential is never reachable from JS, and
 * the short-lived one never outlives the tab.
 *
 * **Refresh is single-flight.** When a token expires, every in-flight request
 * 401s at once. Naively each would trigger its own refresh - and because the
 * server *rotates* refresh tokens and treats reuse as a breach, the second
 * refresh would present an already-rotated token and get the whole session
 * revoked. So the first 401 starts a refresh, the rest await that same promise,
 * and all of them retry afterwards.
 */

// ---------------------------------------------------------------------------
// In-memory token store
// ---------------------------------------------------------------------------
let accessToken: string | null = null;
let onSessionExpired: (() => void) | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

export function getAccessToken(): string | null {
  return accessToken;
}

/** Register the callback that tears down client state when the session dies. */
export function setSessionExpiredHandler(handler: () => void): void {
  onSessionExpired = handler;
}

// ---------------------------------------------------------------------------
// Error shape
// ---------------------------------------------------------------------------
/** The backend's error envelope (see `app/core/exceptions.py`). */
export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details?: Record<string, unknown>;
    request_id?: string;
  };
}

/**
 * A normalised API failure.
 *
 * Every call site gets the same shape - machine-readable `code`, a displayable
 * `message`, and `fieldErrors` ready to hand to react-hook-form - instead of
 * each one having to unwrap `error.response.data.error.details.fields`.
 */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown>;
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options: {
      code?: string;
      status?: number;
      details?: Record<string, unknown>;
      requestId?: string;
    } = {},
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code ?? 'unknown_error';
    this.status = options.status ?? 0;
    this.details = options.details ?? {};
    this.requestId = options.requestId;
  }

  /** Per-field messages from a 422, keyed by field name. */
  get fieldErrors(): Record<string, string> {
    const fields = this.details['fields'];
    if (fields && typeof fields === 'object') {
      return fields as Record<string, string>;
    }
    // The password policy returns a list of reasons rather than a field map.
    const password = this.details['password'];
    if (Array.isArray(password)) {
      return { password: password.join('. ') };
    }
    return {};
  }

  get isValidation(): boolean {
    return this.status === 422;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isNotFound(): boolean {
    return this.status === 404;
  }

  /** True for conditions a retry might resolve - offline, timeout, 5xx. */
  get isRetryable(): boolean {
    return this.status === 0 || this.status >= 500;
  }
}

function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error;

  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError<ApiErrorBody>;
    const body = axiosError.response?.data;

    if (body?.error) {
      return new ApiError(body.error.message, {
        code: body.error.code,
        status: axiosError.response?.status ?? 0,
        details: body.error.details ?? {},
        ...(body.error.request_id !== undefined ? { requestId: body.error.request_id } : {}),
      });
    }

    // No envelope: the request never reached the app (network down, CORS
    // rejection, proxy error). Say so plainly rather than showing "undefined".
    if (!axiosError.response) {
      return new ApiError(
        axiosError.code === 'ECONNABORTED'
          ? 'The request timed out. Check your connection and try again.'
          : 'Could not reach the server. Check your connection and try again.',
        { code: 'network_error', status: 0 },
      );
    }

    return new ApiError(axiosError.message, {
      code: 'http_error',
      status: axiosError.response.status,
    });
  }

  return new ApiError(error instanceof Error ? error.message : 'Something went wrong');
}

// ---------------------------------------------------------------------------
// Instance
// ---------------------------------------------------------------------------
export const http: AxiosInstance = axios.create({
  baseURL: `${env.apiBaseUrl}${env.apiPrefix}`,
  timeout: 30_000,
  // Required for the HttpOnly refresh cookie to be sent cross-origin. Paired
  // with an explicit CORS allow-list server-side - a wildcard origin is
  // forbidden by browsers alongside credentials.
  withCredentials: true,
  headers: { 'Content-Type': 'application/json' },
});

http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// ---------------------------------------------------------------------------
// Single-flight refresh
// ---------------------------------------------------------------------------
/** Marks a request that has already been retried, so a loop is impossible. */
interface RetryableConfig extends InternalAxiosRequestConfig {
  _retried?: boolean;
}

let refreshPromise: Promise<string> | null = null;

/** Endpoints that must never trigger a refresh-and-retry. */
const NO_REFRESH_PATHS = [
  '/auth/login',
  '/auth/refresh',
  '/auth/register',
  '/auth/logout',
  '/auth/otp/verify',
  '/auth/magic-link/verify',
];

async function refreshAccessToken(): Promise<string> {
  // A bare axios call, not `http`: going through the instance would re-enter
  // this interceptor and attach the dead access token.
  const response = await axios.post<{ access_token: string }>(
    `${env.apiBaseUrl}${env.apiPrefix}/auth/refresh`,
    {},
    { withCredentials: true, timeout: 15_000 },
  );

  const token = response.data.access_token;
  setAccessToken(token);
  return token;
}

http.interceptors.response.use(
  (response) => response,
  async (error: unknown) => {
    if (!axios.isAxiosError(error) || !error.config) {
      return Promise.reject(toApiError(error));
    }

    const config = error.config as RetryableConfig;
    const status = error.response?.status;
    const url = config.url ?? '';

    const shouldAttemptRefresh =
      status === 401 && !config._retried && !NO_REFRESH_PATHS.some((path) => url.includes(path));

    if (!shouldAttemptRefresh) {
      return Promise.reject(toApiError(error));
    }

    config._retried = true;

    try {
      // Concurrent 401s share one refresh - see the module docstring on why
      // parallel refreshes would get the session revoked.
      refreshPromise ??= refreshAccessToken().finally(() => {
        refreshPromise = null;
      });

      const token = await refreshPromise;
      config.headers.Authorization = `Bearer ${token}`;
      return http.request(config);
    } catch {
      // The refresh token is gone, expired, or was revoked. This is a real
      // sign-out, not a transient failure.
      setAccessToken(null);
      onSessionExpired?.();
      return Promise.reject(toApiError(error));
    }
  },
);

// ---------------------------------------------------------------------------
// Typed helpers
// ---------------------------------------------------------------------------
export const api = {
  async get<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await http.get<T>(url, config);
    return data;
  },
  async post<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await http.post<T>(url, body, config);
    return data;
  },
  async patch<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await http.patch<T>(url, body, config);
    return data;
  },
  async put<T>(url: string, body?: unknown, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await http.put<T>(url, body, config);
    return data;
  },
  async delete<T>(url: string, config?: AxiosRequestConfig): Promise<T> {
    const { data } = await http.delete<T>(url, config);
    return data;
  },
};

/**
 * Restore a session on app boot.
 *
 * Exchanges the HttpOnly refresh cookie for an access token. Returns `false`
 * when there is no valid cookie, which simply means "not signed in" - the
 * normal first-visit path, not an error.
 */
export async function bootstrapSession(): Promise<boolean> {
  try {
    await refreshAccessToken();
    return true;
  } catch {
    setAccessToken(null);
    return false;
  }
}
