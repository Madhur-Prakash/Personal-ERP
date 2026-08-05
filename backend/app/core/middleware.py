"""HTTP middleware.

Order is significant. Starlette runs middleware outermost-first on the way in and
innermost-first on the way out, so registration order in :mod:`app.main` is
reversed relative to execution. The stack is arranged so that:

* request-id assignment happens first, giving every later layer (including the
  rate limiter's rejections) something to correlate on;
* rate limiting runs before any handler work, so a flood costs a Redis
  ``INCR`` rather than a database query;
* security headers are applied last on the way out, so they are present on *every*
  response - including errors produced deeper in the stack.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Final

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp

from app.core.config import settings
from app.core.logging import clear_log_context, get_logger, set_log_context

log = get_logger(__name__)

REQUEST_ID_HEADER: Final = "X-Request-ID"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assign a request id and log every request with its outcome.

    An inbound ``X-Request-ID`` is honoured so a trace can be followed across a
    reverse proxy or a calling service; otherwise one is generated. It is echoed
    back on the response, and appears in the error envelope, so a user reporting a
    failure can quote an id that finds the exact log lines.

    This replaces uvicorn's access log (silenced in :mod:`app.core.logging`),
    which knows nothing about the authenticated user or the request id.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        set_log_context(request_id=request_id)

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # The exception handlers build the response; this only records timing
            # and re-raises so they can do their job.
            duration_ms = (time.perf_counter() - started) * 1000
            log.exception(
                "request failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            raise
        finally:
            # ContextVars are per-task, but the worker task is reused, so stale
            # identifiers would otherwise bleed into the next request on it.
            clear_log_context()

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers["Server-Timing"] = f"app;dur={duration_ms:.1f}"

        # Health probes fire every few seconds; logging them buries real traffic.
        if not request.url.path.startswith("/health"):
            log.info(
                "request completed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "duration_ms": round(duration_ms, 2),
                    "client_ip": request.client.host if request.client else None,
                },
            )

        return response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Attach defence-in-depth response headers.

    These are cheap and each closes a specific class of attack:

    * ``X-Content-Type-Options: nosniff`` - stops a browser from reinterpreting a
      JSON response as HTML and executing it.
    * ``X-Frame-Options: DENY`` - no framing, so clickjacking has nothing to load.
    * ``Referrer-Policy`` - keeps tokens in URLs (magic links) out of the
      ``Referer`` header sent to third parties.
    * ``Content-Security-Policy`` - the API returns only JSON, so a policy of
      "load nothing, frame nothing" is both correct and maximally strict.
    * ``Strict-Transport-Security`` - production only; sending it over plain HTTP
      in development would pin localhost to HTTPS in the developer's browser and
      break every other local project on that port.
    """

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)

        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"

        # Interactive docs need to load their own JS/CSS, so exempt those paths.
        #
        # A route that already set its own policy keeps it. The document-download
        # endpoint returns bytes a stranger uploaded and adds `sandbox`, which the
        # blanket policy below does not carry - overwriting it here would silently
        # remove a deliberate hardening measure, which is exactly the kind of
        # regression a middleware that clobbers headers causes.
        if (
            not request.url.path.startswith(("/docs", "/redoc", "/openapi.json"))
            and "Content-Security-Policy" not in response.headers
        ):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
            )

        if settings.environment.is_production:
            response.headers["Strict-Transport-Security"] = (
                "max-age=63072000; includeSubDomains; preload"
            )

        return response


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Fixed-window rate limiting backed by Redis.

    A fixed window (rather than a sliding log or token bucket) is one ``INCR``
    plus one ``EXPIRE`` per request, which keeps the limiter cheap enough to sit
    in front of everything. Its known weakness is burst tolerance at a window
    boundary - up to twice the limit across two adjacent windows. Acceptable here:
    this is abuse protection, not billing, and auth endpoints get a much tighter
    budget where that matters.

    Auth endpoints are limited separately and far more aggressively, because they
    are where credential stuffing and enumeration attempts land.

    **Fails open.** If Redis is unavailable the request proceeds. Fail-closed
    would convert a cache outage into a total outage, which is a worse trade for a
    protective layer.
    """

    #: Never rate-limited - orchestrator probes must not be throttled.
    EXEMPT_PATHS: Final = ("/health",)

    #: Tighter budget: credential-guessing and enumeration surfaces.
    AUTH_PATH_MARKERS: Final = (
        "/auth/login",
        "/auth/register",
        "/auth/forgot-password",
        "/auth/reset-password",
        "/auth/magic-link",
        "/auth/otp",
        "/auth/resend-verification",
        "/auth/2fa",
    )

    #: Paths that :data:`AUTH_PATH_MARKERS` matches by prefix but must not take the
    #: tighter budget.
    #:
    #: The device sign-in poll is called every couple of seconds *by design*, so the
    #: credential-guessing budget would fail it within seconds of the screen opening.
    #: It is not a guessing surface: the handle is 256 bits, the record expires on its
    #: own, and it is destroyed on first success. It takes the default budget, which a
    #: 2-second cadence sits comfortably inside.
    AUTH_PATH_EXCEPTIONS: Final = ("/auth/magic-link/device/poll",)

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)
        self._default_limit, self._default_window = _parse_rate(settings.rate_limit_default)
        self._auth_limit, self._auth_window = _parse_rate(settings.rate_limit_auth)

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if not settings.rate_limit_enabled or request.url.path.startswith(self.EXEMPT_PATHS):
            return await call_next(request)

        is_auth_path = any(
            marker in request.url.path for marker in self.AUTH_PATH_MARKERS
        ) and not request.url.path.endswith(self.AUTH_PATH_EXCEPTIONS)
        limit = self._auth_limit if is_auth_path else self._default_limit
        window = self._auth_window if is_auth_path else self._default_window
        scope = "auth" if is_auth_path else "default"

        identifier = request.client.host if request.client else "unknown"

        try:
            count, reset_in = await self._hit(scope, identifier, window)
        except Exception as exc:
            log.error("rate limiter unavailable - allowing request", extra={"error": str(exc)})
            return await call_next(request)

        if count > limit:
            log.warning(
                "rate limit exceeded",
                extra={
                    "client_ip": identifier,
                    "path": request.url.path,
                    "scope": scope,
                    "count": count,
                    "limit": limit,
                },
            )
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limit_exceeded",
                        "message": "Too many requests. Slow down.",
                        "details": {"retry_after_seconds": reset_in},
                        "request_id": getattr(request.state, "request_id", None),
                    }
                },
                headers={
                    "Retry-After": str(reset_in),
                    "X-RateLimit-Limit": str(limit),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                },
            )

        response = await call_next(request)
        response.headers["X-RateLimit-Limit"] = str(limit)
        response.headers["X-RateLimit-Remaining"] = str(max(0, limit - count))
        response.headers["X-RateLimit-Reset"] = str(reset_in)
        return response

    async def _hit(self, scope: str, identifier: str, window: int) -> tuple[int, int]:
        """Increment the counter for the current window.

        The window number is derived from the clock, so the key rolls over on its
        own and the TTL cleans up the old one.
        """
        from app.core.redis import RedisKey, get_redis

        redis = get_redis()
        window_index = int(time.time()) // window
        key = RedisKey.rate_limit(scope, identifier, window_index)

        pipe = redis.pipeline()
        pipe.incr(key)
        pipe.expire(key, window)
        pipe.ttl(key)
        count, _expired, ttl = await pipe.execute()

        return int(count), max(1, int(ttl))


def _parse_rate(spec: str) -> tuple[int, int]:
    """Parse ``"200/minute"`` into ``(200, 60)``.

    Falls back to a permissive default on a malformed value rather than raising:
    a typo in configuration should not prevent the app from booting.
    """
    units = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
    try:
        count, unit = spec.split("/", 1)
        return int(count), units[unit.strip().lower().rstrip("s")]
    except (ValueError, KeyError):
        log.error("malformed rate limit spec - using 200/minute", extra={"spec": spec})
        return 200, 60
