# =============================================================================
# Personal ERP — backend image
#
# Multi-stage, with `development` and `production` targets sharing one dependency
# layer. Compose selects the target; CI builds `production`.
# =============================================================================

# ---- Base: interpreter + uv, no application code ----------------------------
FROM python:3.13-slim-bookworm AS base

# uv is copied from its official distroless image rather than pip-installed:
# a pinned binary, no build toolchain, and no chance of it perturbing the
# application's own dependency resolution.
COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    # Copy packages into the venv instead of hardlinking: the cache mount and
    # the venv are on different filesystems, where hardlinks fail.
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    PATH="/app/.venv/bin:$PATH"

# curl is for the container healthcheck; libpq5 is asyncpg's runtime library.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libpq5 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# ---- Dependencies -----------------------------------------------------------
# Manifests only, before the source: dependencies change far less often than
# code, so this layer stays cached across almost every rebuild.
FROM base AS deps

COPY pyproject.toml uv.lock ./

# `--frozen` fails if uv.lock is out of date with pyproject.toml, so a
# forgotten lockfile update breaks the build instead of silently installing
# different versions than were tested.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ---- Development ------------------------------------------------------------
FROM deps AS development

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY . .

EXPOSE 8000

# `--reload` watches the bind-mounted source. `--proxy-headers` with a trusted
# host list is what makes `request.client.host` the real client IP behind Nginx
# rather than the proxy's — IP-based lockout depends on it.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--reload", "--reload-dir", "app", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]

# ---- Production -------------------------------------------------------------
FROM base AS production

# Runs unprivileged. A container process that does not need root should not have
# it — this is the cheapest possible mitigation for a container escape.
RUN groupadd --gid 1001 personalerp \
    && useradd --uid 1001 --gid personalerp --create-home --shell /bin/bash personalerp

COPY --from=deps --chown=personalerp:personalerp /app/.venv /app/.venv

COPY --chown=personalerp:personalerp app ./app
COPY --chown=personalerp:personalerp migrations ./migrations
COPY --chown=personalerp:personalerp alembic.ini pyproject.toml README.md ./

# logifyx writes here; it must be writable by the unprivileged user.
RUN mkdir -p /app/logs && chown -R personalerp:personalerp /app/logs

USER personalerp

EXPOSE 8000

# Hits the liveness probe, which deliberately touches no dependencies — a
# database blip must not cause the orchestrator to kill healthy containers.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health/live || exit 1

# No `--reload` and no `--workers`: horizontal scaling is by container replica,
# which keeps every instance stateless and independently restartable. Set
# WEB_CONCURRENCY only if running a single container on a large host.
CMD ["uvicorn", "app.main:app", \
     "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*", \
     "--no-server-header", \
     "--timeout-keep-alive", "65"]
