# Personal ERP

**A self-hosted ERP for small businesses. Simple to run, yours to keep.**

Small businesses get offered two bad options: cloud SaaS that rents you your own
books and raises the price once you depend on it, or legacy desktop software that
lives on one machine and dies with its hard drive. Personal ERP is the third
option — you run it on your own server, your data stays in your own PostgreSQL,
and there is no vendor between you and your accounts.

The design constraint is **restraint**. This is deliberately not an
enterprise-scale platform: no Kubernetes, no message-broker cluster, no service
mesh. It is a single `docker compose up` that one person can operate without a
DevOps team. Everything is modular, so when a business genuinely outgrows a
component — more workers, a read replica, a separate object store — that piece can
be scaled or swapped without rewriting the rest. Scale when the business demands
it, not on day one.

Built in stages. **Stage 1 — Foundation — is complete**; see
[Delivery status](#delivery-status).

---

## What exists today

| Area | Status |
| --- | --- |
| Monorepo, Docker Compose (dev + prod) | Done |
| FastAPI backend, PostgreSQL 17, Redis 7 | Done |
| React 19 + TypeScript + Vite frontend | Done |
| Authentication — password, email verification, magic link, email OTP, password reset, TOTP 2FA with recovery codes | Done |
| Sessions — refresh-token rotation with reuse detection, device history, remote revocation | Done |
| Multi-tenancy — organizations, members, invitations | Done |
| RBAC — 36 permissions, 5 seeded roles, custom roles, per-member overrides | Done |
| Immutable audit trail with field-level diffs | Done |
| Design system, light/dark/system theming, command palette | Done |
| Alembic migrations (reversible, drift-checked) | Done |
| 199 backend tests against real PostgreSQL + Redis | Done |
| CI/CD, Nginx, TLS, backups, zero-downtime deploy | Done |

There is **no OAuth**. Sign-in is email/password plus the passwordless options
above, by design.

---

## Quick start

Requires Docker, and — for running outside containers —
[uv](https://docs.astral.sh/uv/) and Node 24.

```bash
git clone <repo> && cd personalerp
make setup          # creates .env, installs deps, starts services, migrates
make up             # starts the whole stack
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |
| Mailpit (all outbound email) | http://localhost:8025 |

Register at http://localhost:5173/register, then open **Mailpit at
http://localhost:8025** to click the verification link. `make up` wires the
backend's SMTP at Mailpit, so no real mail provider is needed.

> If you run the backend without SMTP configured at all, emails are written to
> the log instead of sent — but logifyx's masking redacts the token from the URL,
> so the link is not usable from there. Mailpit is the path that works.

`make help` lists every task.

---

## Everyday commands

All backend commands run from `backend/`, frontend commands from `frontend/`.

### Quality gates

All three are blocking in CI, so run them before pushing.

```bash
uv run ruff check app tests     # find problems
uv run ruff format .            # fix formatting
uv run mypy app                 # typecheck
```

CI runs `ruff check .` over the whole project and `ruff format --check .` (the
non-mutating form — it reports rather than rewrites). Narrowing to `app tests`
locally is faster and covers everything you actually edit.

[`ruff`](https://docs.astral.sh/ruff/) is linter and formatter in one (~180 ms for
66 files). Beyond style it enforces two things that matter here: `T20` bans
`print()`, so logging cannot bypass logifyx and lose its credential masking; and
`ASYNC` catches blocking calls inside `async def`, which stall the whole event
loop rather than one request.

[`mypy`](https://mypy-lang.org/) runs in `strict` mode. Its real job in this
codebase is making `None` impossible to ignore — `User.password_hash` is nullable
(magic-link and invited users have no password), and mypy is what forces every
call site to handle that before reaching Argon2.

### Tests

```bash
uv run pytest                   # 210 tests, needs postgres + redis
uv run pytest -q -k auth        # just the auth suite
uv run pytest --cov             # with coverage
```

### Migrations

```bash
uv run alembic upgrade head                        # apply
uv run alembic revision --autogenerate -m "msg"    # generate
uv run alembic downgrade -1                        # roll back one
```

### Dev servers

```bash
uv run uvicorn app.main:app --reload   # backend  → :8000
npm run dev                            # frontend → :5173
```

### Frontend equivalents

```bash
npm run lint          # eslint . --max-warnings 0    (ruff's counterpart)
npm run typecheck     # tsc -b --noEmit              (mypy's counterpart)
npm run format        # prettier --write             (ruff format's counterpart)
npm run build         # tsc -b && vite build
```

`npm run lint:fix` and `npm run format:check` are also defined — the latter is the
non-mutating form, which is what CI uses.

> **On Windows, run these from PowerShell, not Git Bash.** Git Bash's MSYS layer
> rewrites environment values that look like Unix paths, so `API_V1_PREFIX=/api/v1`
> arrives as `C:/Program Files/Git/api/v1` and the app refuses to start. Not a bug
> in the app — but it makes every backend command fail confusingly.

---

## Layout

```
.
├── backend/                 FastAPI · Python 3.13 · uv
│   ├── app/
│   │   ├── core/            Config, logging, security, errors, middleware
│   │   ├── db/              Declarative base, mixins, session, model registry
│   │   ├── modules/         One vertical slice per bounded context
│   │   └── api/v1/          Router aggregation
│   ├── migrations/          Alembic
│   └── tests/               pytest — 199 tests
├── frontend/                React 19 · TypeScript · Vite · Tailwind v4
│   └── src/
│       ├── components/      Design-system primitives and layout
│       ├── features/        auth, dashboard, organizations, settings, theme
│       ├── lib/             HTTP client, env validation, formatting
│       └── routes/          TanStack Router tree
├── infra/
│   ├── nginx/               Edge reverse proxy, TLS, rate limiting
│   └── scripts/             Backup and restore
├── docs/                    Architecture, API, security, deployment
└── .github/workflows/       CI and deploy
```

Each backend module is a vertical slice:

```
modules/<name>/
  models.py        SQLAlchemy tables
  schemas.py       Pydantic request/response contracts
  repository.py    Data access — the only layer touching the session
  service.py       Business rules — transport-agnostic
  router.py        HTTP surface — thin
```

Dependencies point inward: `router → service → repository → models`. A service
never imports a router; a repository never raises HTTP errors. That is what makes
modules independently testable and replaceable.

---

## Design decisions worth knowing

These are the choices that shape everything built on top. Each is explained where
it lives, in the code.

**Access tokens live in memory; refresh tokens live in an HttpOnly cookie.**
`localStorage` is readable by any XSS on the page, and a stolen token is valid
until it expires. The short-lived access token dies with the tab; the long-lived
refresh token is never reachable from JavaScript at all.

**Refresh tokens rotate, and reuse is treated as a breach.** Every refresh mints
a new token and revokes the old one. Presenting an already-rotated token means
two parties hold it, and we cannot tell which is legitimate — so the whole
session lineage is revoked and the event is audited as critical.
([`auth/service.py`](backend/app/modules/auth/service.py))

**Permissions ride in the access token; a Redis epoch counter overrides it.**
Embedding permissions means authorization costs no database query. Staleness is
bounded by the 15-minute token TTL, and anything that must apply immediately —
role change, suspension, password change, sign-out-everywhere — bumps the user's
epoch, invalidating every outstanding token at once.
([`auth/dependencies.py`](backend/app/modules/auth/dependencies.py))

**The active organization comes from the signed token, never from the URL.**
There is no organization id in any API path for a client to tamper with, which
makes cross-tenant access structurally impossible rather than merely checked.
([`organizations/router.py`](backend/app/modules/organizations/router.py))

**Permissions are code; roles are data.** A permission is a capability the
software implements, so it lives in an enum — the enum *is* the contract, it is
greppable, and it cannot drift from a table. Roles are per-organization rows
composing those slugs. ([`rbac/permissions.py`](backend/app/modules/rbac/permissions.py))

**No account enumeration.** Password reset, magic link, and OTP all respond
identically whether or not the account exists, and login burns an Argon2 cycle on
a miss so timing cannot distinguish the two either.

**Password policy: 6 characters minimum, with at least one uppercase letter, one
lowercase letter, and one special character.** Because composition rules of this
shape reliably produce `Password@1` — the first thing any cracking dictionary
tries — a blocklist backstop also rejects weak roots however they are dressed up
(`P@ssw0rd` and `Passw0rd!` both normalise to `password`).
([`auth/password_policy.py`](backend/app/modules/auth/password_policy.py))

**UUIDv7 primary keys.** Time-ordered, so inserts append to the right edge of the
index instead of scattering, and cursor pagination is a primary-key seek with no
composite cursor. ([`db/base.py`](backend/app/db/base.py))

**The audit trail is append-only.** No `updated_at`, no soft delete, no update
path in the repository. An audit log that can be edited is not evidence.

**All backend logging goes through [logifyx](https://pypi.org/project/logifyx/).**
One entry point, with automatic redaction of passwords and tokens, request-scoped
context injection, and JSON output in production.
([`core/logging.py`](backend/app/core/logging.py))

---

## The stack

**Backend** — FastAPI, Python 3.13, uv, SQLAlchemy 2 (async), Alembic,
PostgreSQL 17, Redis 7, Pydantic v2, Argon2id, PyJWT, pyotp, aiosmtplib, logifyx.

**Frontend** — React 19, TypeScript, Vite 7, Tailwind CSS v4, TanStack
Router + Query + Table, React Hook Form, Zod, Recharts, cmdk, Sonner, Lucide,
Motion.

**Infrastructure** — Docker, Nginx, Let's Encrypt, GitHub Actions.

---

## Verified state

Everything below was run against real infrastructure, not mocks:

```
backend    199 tests passing (PostgreSQL 17 + Redis 7)
backend    ruff: all checks passed
backend    alembic: applies, reverses, and reports zero drift
frontend   tsc -b: 0 errors
frontend   eslint: 0 problems (type-aware rules enabled)
frontend   vite build: succeeds, 0 vulnerabilities in the dependency tree
compose    dev and prod files validate
docker     both production images build, run non-root, and pass health checks
live       full auth journey exercised against the production image:
           register -> verify -> login -> refresh rotation -> reuse detection
           -> lineage revocation -> critical audit row
```

Coverage focuses on the parts where a bug is expensive: token rotation and reuse
detection, permission expansion, cross-tenant isolation, owner-lockout
prevention, and secret redaction in the audit trail.

---

## Documentation

| Document | Contents |
| --- | --- |
| [docs/architecture.md](docs/architecture.md) | Layering, request lifecycle, module structure, diagrams |
| [docs/security.md](docs/security.md) | Threat model and every control, with rationale |
| [docs/database.md](docs/database.md) | Schema, ER diagram, indexes, migration workflow |
| [docs/api.md](docs/api.md) | All 47 endpoints, error contract, auth flows |
| [docs/deployment.md](docs/deployment.md) | VPS setup, TLS, backups, zero-downtime deploys |
| [docs/development.md](docs/development.md) | Local workflow, conventions, testing, adding a module |

---

## Delivery status

Built in stages; each is completed, tested, and documented before the next
begins. Later-stage modules appear in the navigation as visibly disabled entries
rather than links to nothing.

- [x] **Stage 1 — Foundation.** Monorepo, Docker, auth, users/organizations,
      RBAC, audit, CI/CD, design system, dashboard, deployment.
- [ ] **Stage 2 — Accounting core.** Chart of accounts, journals, ledgers,
      double-entry bookkeeping, trial balance, P&L, balance sheet, cash flow.
- [ ] **Stage 3 — Customers & sales.** CRM, leads, quotations, sales orders,
      invoices, payments, PDF generation.
- [ ] **Stage 4 — Purchases & inventory.** Suppliers, purchase orders, goods
      receipt, warehouses, stock movements, barcodes.
- [ ] **Stage 5 — OCR & document intelligence.** Invoice and receipt extraction,
      confidence scoring, manual review.
- [ ] **Stage 6 — AI assistant.** Conversational interface, RAG over business
      data, natural-language queries, forecasting.
- [ ] **Stage 7 — Automation platform.** Visual workflow builder, triggers,
      scheduled jobs, approval flows, messaging integrations.
- [ ] **Stage 8 — Analytics & reporting.** Interactive dashboards, custom
      reports, scheduled exports, KPI tracking.
- [ ] **Stage 9 — Enterprise.** Advanced multi-tenancy, API keys, webhooks, SSO,
      compliance, passkeys.
- [ ] **Stage 10 — Production hardening.** Security review, monitoring, load
      testing, performance tuning.

### A note on the dashboard

The revenue, expense, and profit figures on the dashboard are **labelled "Sample"
in the interface** and are illustrative placeholders. There is no ledger until
Stage 2, so there is nothing real to aggregate. They exist so the chart and tile
design can be evaluated, and they are marked because an unlabelled fake number in
an accounting product is the most damaging thing that page could do. Member
counts, the organization list, and the activity feed are live.

---

## Licence

Proprietary. All rights reserved.
