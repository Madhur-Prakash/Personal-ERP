# =============================================================================
# Personal ERP — task runner
#
#   make help          list every target
#   make setup         first-time setup
#   make up            start the development stack
#   make check         everything CI checks, locally
# =============================================================================

.DEFAULT_GOAL := help
# Every recipe runs in one shell with strict flags, so a failing line aborts the
# target instead of the next line running against a broken state.
.SHELLFLAGS := -eu -o pipefail -c
SHELL := bash

COMPOSE      := docker compose
COMPOSE_PROD := docker compose -f docker-compose.prod.yml
BACKEND      := cd backend &&
FRONTEND     := cd frontend &&

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# -----------------------------------------------------------------------------
# Setup
# -----------------------------------------------------------------------------
.PHONY: setup
setup: ## First-time setup: env file, dependencies, database
	@test -f .env || { cp .env.example .env; echo "Created .env — review it before continuing."; }
	$(MAKE) install
	$(COMPOSE) up -d postgres redis mailpit
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
	@echo "  Mailpit    http://localhost:8025"

.PHONY: down
down: ## Stop the development stack
	$(COMPOSE) down

.PHONY: clean
clean: ## Stop and DELETE all volumes (destroys local data)
	$(COMPOSE) down -v

.PHONY: services
services: ## Start only PostgreSQL, Redis, and Mailpit
	$(COMPOSE) up -d postgres redis mailpit

.PHONY: dev-api
dev-api: ## Run the API on the host with reload
	$(BACKEND) uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

.PHONY: dev-web
dev-web: ## Run the Vite dev server on the host
	$(FRONTEND) npm run dev

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
lint: ## Lint both sides
	$(BACKEND) uv run ruff check .
	$(FRONTEND) npm run lint

.PHONY: format
format: ## Format both sides
	$(BACKEND) uv run ruff format . && uv run ruff check --fix .
	$(FRONTEND) npm run format

.PHONY: typecheck
typecheck: ## Type check both sides
	$(BACKEND) uv run mypy app
	$(FRONTEND) npx tsc -b

.PHONY: test
test: ## Run backend tests (needs PostgreSQL and Redis)
	$(BACKEND) uv run pytest -q

.PHONY: test-cov
test-cov: ## Run backend tests with a coverage report
	$(BACKEND) uv run pytest --cov --cov-report=term-missing --cov-report=html

.PHONY: build
build: ## Build the frontend for production
	$(FRONTEND) npm run build

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
