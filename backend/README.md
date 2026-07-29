# Personal ERP - Backend

FastAPI + PostgreSQL + Redis. Python 3.13, managed with [uv](https://docs.astral.sh/uv/).

All logging goes through [logifyx](https://pypi.org/project/logifyx/) - see
[`app/core/logging.py`](app/core/logging.py). Nothing in this codebase calls
`logging.getLogger` or `print` directly.

## Layout

```
app/
  core/          Cross-cutting concerns - config, logging, security, errors, middleware
  db/            Declarative base, mixins, session/engine, model registry
  modules/       One vertical slice per bounded context
    <module>/
      models.py        SQLAlchemy tables
      schemas.py       Pydantic request/response contracts
      repository.py    Data access - the only layer that touches the session
      service.py       Business rules - transport-agnostic, raises domain errors
      router.py        HTTP surface - thin, delegates to the service
  api/v1/        Router aggregation and versioning
migrations/      Alembic
tests/           pytest
```

The dependency rule points inward: `router → service → repository → models`. A
service never imports a router; a repository never raises HTTP errors. That is
what keeps modules independently testable and replaceable.

## Commands

```bash
uv sync                              # install (creates .venv)
uv run uvicorn app.main:app --reload # dev server
uv run alembic upgrade head          # apply migrations
uv run alembic revision --autogenerate -m "message"
uv run pytest                        # tests
uv run pytest --cov                  # with coverage
uv run ruff check . && uv run ruff format .
uv run mypy app
```

Requires PostgreSQL and Redis. `docker compose up postgres redis` from the repo
root is the easiest way to get both.

## Configuration

Every setting lives in [`app/core/config.py`](app/core/config.py) and is read
from the repo-root `.env` (copy `.env.example`). Application code must not read
`os.environ` - import `get_settings()` instead.

`LOG_*` variables belong to logifyx and are documented in `.env.example`.

Booting with `ENVIRONMENT=production` runs a set of guardrail assertions
(real `SECRET_KEY`, no wildcard CORS, `ENCRYPTION_KEY` present, non-default
database password) and refuses to start if any fail.
