# =============================================================================
# Personal ERP - task runner
#
#   make help          list every target
#   make setup         first-time setup
#   make up            start the development stack
#   make check         everything CI checks, locally
# =============================================================================

.DEFAULT_GOAL := help

# -----------------------------------------------------------------------------
# Shell
# -----------------------------------------------------------------------------
# Every recipe runs in one shell with strict flags, so a failing line aborts the
# target instead of the next line running against a broken state.
.SHELLFLAGS := -eu -o pipefail -c
SHELL := bash

# On Windows, `SHELL := bash` is silently ignored. Native GNU Make cannot find a
# bare `bash` (Git Bash is not on PATH - only `git` is), falls back to `cmd.exe`,
# and every recipe dies with "'grep' is not recognized as an internal or external
# command". So the shell is resolved explicitly here.
#
# **Not via `where bash`.** On a machine with WSL that returns
# `C:\Windows\System32\bash.exe`, and recipes would then run inside the WSL
# filesystem namespace - wrong working directory, and `uv`/`npm`/`docker` either
# missing or pointing at a different install. Silently running in the wrong place
# is far worse than failing loudly.
#
# Git Bash ships beside `git`, which *is* on PATH, so it is derived from there.
# `PROGRA~1` is the 8.3 short name for `Program Files`: make splits its SHELL
# value on spaces, so the long form resolves to `C:/Program` and fails.
ifeq ($(OS),Windows_NT)
  GIT_BASH := C:/PROGRA~1/Git/bin/bash.exe
  ifeq ($(wildcard $(GIT_BASH)),)
    $(error Git Bash not found at $(GIT_BASH). Install Git for Windows, \
      or override it: make SHELL=/path/to/bash <target>)
  endif
  SHELL := $(GIT_BASH)

  # Stop MSYS from rewriting environment values that look like Unix paths when it
  # spawns a native Windows process.
  #
  # Without this, `API_V1_PREFIX=/api/v1` reaches Python as
  # `C:/Program Files/Git/api/v1`, and the app dies at import with
  # "A path prefix must start with '/'". The translation is correct for real paths
  # and wrong for everything else - and every value this project puts in the
  # environment is a config string, not a path the MSYS layer should touch.
  #
  # `PATH` is special-cased by MSYS and still translated, so recipes continue to
  # find `uv`, `npm`, and `docker` normally. Verified, not assumed.
  export MSYS2_ENV_CONV_EXCL := *

  # The same translation applies to command-line *arguments*, and that bites the desktop
  # client specifically: `flutter build --dart-define=API_V1_PREFIX=/api/v1` reaches the
  # compiler as `C:/Program Files/Git/api/v1`, and the value is then baked into the binary.
  # The app's own environment validation catches it and refuses to start - which is the
  # validation working, but only after a two-minute build. Switched off here so the target
  # is correct from either shell.
  export MSYS2_ARG_CONV_EXCL := *
endif

COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml
BACKEND      := cd backend &&
FRONTEND     := cd frontend &&
DESKTOP      := cd app_frontend &&

# Where the desktop client points.
#
# The web app reads `VITE_API_BASE_URL` from `.env` at build time; Flutter has no such
# mechanism, so the equivalent is `--dart-define` and it has to be passed on every `run`
# and `build`. Overridable for a real deployment:
#
#   make desktop API_BASE_URL=https://erp.example.com
#
# `127.0.0.1` rather than `localhost`, matching the default compiled into the client:
# `docker compose` may publish the port on IPv4 only, and a name that resolves to `::1`
# first then fails with "connection refused" against a server that is running.
API_BASE_URL   ?= http://127.0.0.1:8000
API_V1_PREFIX  ?= /api/v1

# `=` rather than `:=` on purpose. An immediately-expanded assignment would capture these
# two variables before the defaults above are set - and because the values then arrive
# empty, the build succeeds and produces a binary that refuses to start. Recursive
# expansion resolves them at use, which also lets an override on the command line win.
DESKTOP_ENV   = --dart-define=API_BASE_URL=$(API_BASE_URL)                 --dart-define=API_V1_PREFIX=$(API_V1_PREFIX)

# The desktop target to run. Defaults to whichever this machine is.
ifeq ($(OS),Windows_NT)
  DESKTOP_DEVICE ?= windows
else
  UNAME_S := $(shell uname -s)
  ifeq ($(UNAME_S),Darwin)
    DESKTOP_DEVICE ?= macos
  else
    DESKTOP_DEVICE ?= linux
  endif
endif

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
.PHONY: setup
setup: ## First-time setup: env file, dependencies, database
	@test -f .env || { cp .env.sample .env; echo "Created .env - review it before continuing."; }
	$(MAKE) install
	$(COMPOSE) up -d postgres redis
	@echo "Waiting for PostgreSQL..."
	@until $(COMPOSE) exec -T postgres pg_isready -q; do sleep 1; done
	$(MAKE) migrate
	@echo ""
	@echo "Setup complete. Run 'make dev' to start."

.PHONY: install
install: ## Install backend and frontend dependencies
	$(BACKEND) uv sync
	$(FRONTEND) npm ci

# -----------------------------------------------------------------------------
# Development
# -----------------------------------------------------------------------------
.PHONY: up
up: ## Start the full development stack in Docker
	$(COMPOSE) up -d
	@echo ""
	@echo "  Frontend   http://localhost:5173"
	@echo "  API        http://localhost:8000"
	@echo "  API docs   http://localhost:8000/docs"

.PHONY: down
down: ## Stop the development stack
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop and DELETE all volumes (destroys local data)
	$(COMPOSE) down -v

.PHONY: services
services: ## Start only PostgreSQL and Redis
	$(COMPOSE) up -d postgres redis

.PHONY: dev-api
dev-api: ## Run the API on the host with reload
	$(BACKEND) uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-web
dev-web: ## Run the Vite dev server on the host
	$(FRONTEND) npm run dev

.PHONY: desktop
desktop: ## Run the Flutter desktop client on the host
	$(DESKTOP) flutter run -d $(DESKTOP_DEVICE) $(DESKTOP_ENV)

.PHONY: logs
logs: ## Tail all container logs
	$(COMPOSE) logs -f

.PHONY: logs-api
logs-api: ## Tail the API logs
	$(COMPOSE) logs -f backend

.PHONY: shell
shell: ## Open a Python shell with the app importable
	$(BACKEND) uv run python

.PHONY: psql
psql: ## Open psql against the development database
	$(COMPOSE) exec postgres psql -U personalerp -d personalerp

.PHONY: redis-cli
redis-cli: ## Open redis-cli against the development Redis
	$(COMPOSE) exec redis redis-cli

# -----------------------------------------------------------------------------
# Database
# -----------------------------------------------------------------------------
.PHONY: migrate
migrate: ## Apply all migrations
	$(BACKEND) uv run alembic upgrade head

.PHONY: migration
migration: ## Generate a migration: make migration m="add invoice table"
	@test -n "$(m)" || { echo 'Usage: make migration m="description"'; exit 1; }
	$(BACKEND) uv run alembic revision --autogenerate -m "$(m)"

.PHONY: rollback
rollback: ## Roll back the most recent migration
	$(BACKEND) uv run alembic downgrade -1

.PHONY: db-check
db-check: ## Verify the models and migrations agree (no drift)
	$(BACKEND) uv run alembic check
# `alembic check` alone is not enough: autogenerate does not compare CHECK expressions, so
# adding a value to a StrEnum is invisible to it. It reported no pending operations while
# audit_log.action was missing 49 of 95 values - and because every write records an audit row
# inside its own transaction, uploads, invoices and stock adjustments all failed with a 409
# against a schema the tests could not exercise. They build their schema from the models.
	$(BACKEND) uv run python scripts/check_schema_drift.py

.PHONY: db-history
db-history: ## Show the migration history
	$(BACKEND) uv run alembic history --verbose

.PHONY: db-reset
db-reset: ## Drop and rebuild the database from migrations
	$(BACKEND) uv run alembic downgrade base && uv run alembic upgrade head

# -----------------------------------------------------------------------------
# Quality
# -----------------------------------------------------------------------------
.PHONY: check
check: lint typecheck test ## Run every check CI runs

.PHONY: lint
lint: ## Lint every surface
	$(BACKEND) uv run ruff check .
	$(FRONTEND) npm run lint
	$(DESKTOP) dart format --output=none --set-exit-if-changed lib test

.PHONY: format
format: ## Format every surface
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .
	$(FRONTEND) npm run format
	$(DESKTOP) dart format lib test

.PHONY: typecheck
typecheck: ## Type check every surface
	$(BACKEND) uv run mypy app
	$(FRONTEND) npx tsc -b
	$(DESKTOP) flutter analyze

.PHONY: test
test: ## Run backend tests (needs PostgreSQL and Redis) and desktop tests
	$(BACKEND) uv run pytest -q
	$(DESKTOP) flutter test

.PHONY: test-cov
test-cov: ## Run backend tests with a coverage report
	$(BACKEND) uv run pytest --cov --cov-report=term-missing --cov-report=html

.PHONY: build
build: ## Build the web frontend for production
	$(FRONTEND) npm run build

.PHONY: build-desktop
build-desktop: ## Build a release desktop binary for this platform
	$(DESKTOP) flutter build $(DESKTOP_DEVICE) --release $(DESKTOP_ENV)

# -----------------------------------------------------------------------------
# Production
# -----------------------------------------------------------------------------
.PHONY: prod-up
prod-up: ## Start the production stack
	$(COMPOSE_PROD) up -d --build

.PHONY: prod-down
prod-down: ## Stop the production stack
	$(COMPOSE_PROD) down

.PHONY: prod-logs
prod-logs: ## Tail production logs
	$(COMPOSE_PROD) logs -f --tail=100

.PHONY: prod-migrate
prod-migrate: ## Apply migrations in production
	$(COMPOSE_PROD) run --rm migrate

.PHONY: prod-config
prod-config: ## Validate the production compose file
	$(COMPOSE_PROD) config --quiet && echo "docker-compose.prod.yml is valid"

.PHONY: backup
backup: ## Back up the production database
	./infra/scripts/backup.sh

.PHONY: restore
restore: ## Restore from a backup: make restore f=path/to.dump
	@test -n "$(f)" || { echo 'Usage: make restore f=infra/backups/personalerp-....dump'; exit 1; }
	./infra/scripts/restore.sh "$(f)"
