"""Health and readiness probes.

Three endpoints, because orchestrators ask three different questions:

* ``/health/live`` - "is the process up?" Never touches a dependency. If this
  checked PostgreSQL, a brief database blip would make Docker/Kubernetes kill and
  restart every healthy app container, turning a recoverable outage into a
  cascading one.
* ``/health/ready`` - "can it serve traffic?" Checks dependencies and returns 503
  when they are down, so the load balancer stops routing to this instance without
  restarting it.
* ``/health`` - a human-readable summary for dashboards.

None of them require authentication, and none leak version or configuration
detail beyond what is already public.
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Response, status

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import check_redis_health
from app.core.schemas import HealthStatus
from app.db.session import check_database_health
from app.core.limiter import limiter

log = get_logger(__name__)

router = APIRouter(prefix="/health", tags=["Health"])

@limiter.limit("3/minute")
@router.get("/live", summary="Liveness probe", status_code=status.HTTP_200_OK)
async def liveness() -> dict[str, str]:
    """Is the process alive? No dependency checks - see the module docstring."""
    return {"status": "alive"}

@limiter.limit("3/minute")
@router.get("/ready", summary="Readiness probe")
async def readiness(response: Response) -> dict[str, object]:
    """Can this instance serve traffic?

    PostgreSQL and Redis are probed concurrently: sequential checks would make
    the probe's latency the sum of both timeouts, risking a spurious timeout of
    the probe itself.
    """
    database_ok, redis_ok = await asyncio.gather(
        check_database_health(),
        check_redis_health(),
    )

    ready = database_ok and redis_ok
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        log.error(
            "readiness probe failed",
            extra={"database": database_ok, "redis": redis_ok},
        )

    return {
        "status": "ready" if ready else "not_ready",
        "checks": {
            "database": "up" if database_ok else "down",
            "redis": "up" if redis_ok else "down",
        },
    }


@router.get("", response_model=HealthStatus, summary="Service status summary")
async def health(response: Response) -> HealthStatus:
    """Human-readable status for dashboards and smoke tests."""
    database_ok, redis_ok = await asyncio.gather(
        check_database_health(),
        check_redis_health(),
    )

    healthy = database_ok and redis_ok
    if not healthy:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE

    return HealthStatus(
        status="healthy" if healthy else "degraded",
        version=settings.app_version,
        environment=str(settings.environment),
        checks={
            "database": "up" if database_ok else "down",
            "redis": "up" if redis_ok else "down",
            "email": "configured" if settings.emails_enabled else "log-only",
        },
    )
