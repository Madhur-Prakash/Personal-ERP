"""Application entry point and composition root.

This is the only module that knows how all the pieces fit together. Everything
else depends inward on abstractions, which is what lets modules be tested and
replaced independently.

Run with::

    uv run uvicorn app.main:app --reload
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging, flush_logs, get_logger
from app.core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from app.core.redis import close_redis, get_redis
from app.db.session import dispose_engine
from app.modules.health.router import router as health_router

# logifyx must be registered as the global logger class before any module
# acquires a logger, so this is the first thing that happens in the process.
configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup and shutdown.

    Redis is touched at startup deliberately: a connection failure should surface
    here, in the logs, at boot - not as the first user's failed login. The
    database is not probed, because migrations may legitimately be running
    against it while the app starts; ``/health/ready`` covers that.
    """
    log.info(
        "starting %s v%s",
        settings.app_name,
        settings.app_version,
        extra={
            "environment": str(settings.environment),
            "debug": settings.debug,
            "docs": settings.docs_url,
            # Where uploaded documents go, named at startup because it is derived from
            # whether credentials happen to be configured - and settings are read once per
            # process, so an `.env` edited after the server started has no effect until it
            # restarts. Without this line the only symptom is files quietly landing
            # somewhere other than where the operator just configured, which is a long way
            # to travel for "it needed a restart".
            "documents": settings.document_storage,
            "document_target": (
                f"{settings.minio_endpoint}/{settings.minio_bucket}"
                if settings.document_storage == "object"
                else str(settings.upload_dir)
            ),
        },
    )

    try:
        await get_redis().ping()
        log.info("redis reachable")
    except Exception as exc:
        # Not fatal: rate limiting fails open, and auth degrades rather than
        # breaking. Better to serve with a warning than refuse to boot.
        log.error("redis unreachable at startup", extra={"error": str(exc)})

    yield

    log.info("shutting down")
    await close_redis()
    await dispose_engine()
    # Drain queued remote/Kafka log records before the process exits.
    flush_logs(timeout=3.0)
    log.info("shutdown complete")


def create_app() -> FastAPI:
    """Build the application.

    A factory rather than a module-level singleton so tests can construct an
    isolated instance with overridden settings.
    """
    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description=(
            "A self-hosted ERP for small businesses.\n\n"
            "Authenticate at `/api/v1/auth/login`, then send "
            "`Authorization: Bearer <access_token>`. Refresh tokens are delivered "
            "as an HttpOnly cookie and rotated on every use."
        ),
        docs_url=settings.docs_url,
        redoc_url="/redoc" if not settings.environment.is_production else None,
        openapi_url="/openapi.json" if not settings.environment.is_production else None,
        lifespan=lifespan,
        # Trailing-slash redirects turn a POST into a GET and silently drop the
        # body; better to 404 and make the client fix its URL.
        redirect_slashes=False,
    )

    _register_middleware(app)
    register_exception_handlers(app)

    # Unversioned: orchestrators should not have to track an API version.
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_v1_prefix)

    log.info(
        "application configured",
        extra={"routes": len(app.routes), "api_prefix": settings.api_v1_prefix},
    )
    return app


def _register_middleware(app: FastAPI) -> None:
    """Install middleware.

    Starlette applies middleware in reverse registration order, so the *last*
    registered runs *first* on an incoming request. Reading the calls below
    bottom-up gives the actual request path:

        TrustedHost -> RequestContext -> RateLimit -> CORS -> GZip
            -> SecurityHeaders -> route handler

    Which is what we want: reject bad hosts before doing any work, assign a
    request id early so everything downstream can be correlated, then rate-limit
    before touching the database.
    """
    app.add_middleware(SecurityHeadersMiddleware)

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        # Required for the refresh cookie to be sent cross-origin, and the reason
        # a wildcard origin is rejected by config validation: browsers forbid
        # `*` together with credentials.
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        expose_headers=[
            "X-Request-ID",
            "X-RateLimit-Limit",
            "X-RateLimit-Remaining",
            "X-RateLimit-Reset",
            "Retry-After",
        ],
        max_age=3600,
    )

    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)

    # Blocks Host-header injection, which otherwise poisons absolute URLs in
    # emails. Disabled locally, where the host varies (localhost, 127.0.0.1,
    # a LAN IP for mobile testing).
    if settings.environment.is_production:
        app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)


app = create_app()
