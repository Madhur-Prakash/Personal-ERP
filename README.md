# Personal ERP

**A self-hosted ERP for small businesses. Simple to run, yours to keep.**

Small businesses get offered two bad options: cloud SaaS that rents you your own
books and raises the price once you depend on it, or legacy desktop software that
lives on one machine and dies with its hard drive. Personal ERP is the third
option - you run it on your own server, your data stays in your own PostgreSQL,
and there is no vendor between you and your accounts.

The design constraint is **restraint**. This is deliberately not an
enterprise-scale platform: no Kubernetes, no message-broker cluster, no service
mesh. It is a single `docker compose up` that one person can operate without a
DevOps team. Everything is modular, so when a business genuinely outgrows a
component - more workers, a read replica, a separate object store - that piece can
be scaled or swapped without rewriting the rest. Scale when the business demands
it, not on day one.

Built in stages. **Stages 1 to 5 and 8 are complete** - foundation, accounting,
sales, purchasing and inventory, document intelligence, and analytics; see
[Delivery status](#delivery-status).

---

## What exists today

| Area | Status |
| --- | --- |
| Monorepo, Docker Compose (dev + prod) | Done |
| FastAPI backend, PostgreSQL 17, Redis 7 | Done |
| React 19 + TypeScript + Vite frontend | Done |
| Flutter desktop client - Windows, macOS, Linux; the same screens against the same API, staying signed in across restarts | Done |
| Authentication - password, email verification, magic link (signs in the desktop app too, not just the browser), email OTP, password reset by emailed code, TOTP 2FA with recovery codes | Done |
| Sessions - refresh-token rotation with reuse detection, device history, remote revocation | Done |
| Multi-tenancy - organizations, members, invitations | Done |
| RBAC - 42 permissions, 5 seeded roles, custom roles, per-member overrides | Done |
| Immutable audit trail with field-level diffs | Done |
| **Billing** - record money in and out with just a date, an amount, and a note. No customer or supplier needed; posts real double-entry, so the dashboard and every report update immediately | Done |
| Accounts & cards - a screen of their own on web and desktop: add bank accounts with their bank, holder and account number (**encrypted; no card PAN is stored at all**), register credit and debit cards from the card number, choose the account on any payment, and transfer between your own accounts | Done |
| Double-entry accounting - chart of accounts, journals, period locks, trial balance, P&L, balance sheet, cash flow | Done |
| Sales - customers, leads, quotations, orders, invoices with GST, payment allocation, receivables ageing | Done |
| Purchasing & inventory - suppliers, POs, goods receipt, weighted-average valuation, bills, input GST, payables ageing | Done |
| Document intelligence - invoice upload, field extraction with per-field confidence, GSTIN supplier matching, duplicate-invoice warnings, confirm-into-bill | Done |
| Analytics - real dashboard figures with like-for-like period comparison, twelve-month trend, rankings, control-account reconciliation | Done |
| Design system, light/dark/system theming, command palette | Done |
| Alembic migrations (reversible, drift-checked) | Done |
| 177 API operations across 136 paths | Done |
| 714 backend tests against real PostgreSQL + Redis | Done |
| CI/CD, Nginx, TLS, backups, zero-downtime deploy | Done |

There is **no OAuth**. Sign-in is email/password plus the passwordless options
above, by design.

---

## Quick start

Requires Docker, and - for running outside containers -
[uv](https://docs.astral.sh/uv/) and Node 24.

```bash
git clone https://github.com/Madhur-Prakash/Personal-ERP && cd Personal-ERP
make setup          # creates .env, installs deps, starts services, migrates
make up             # starts the whole stack
```

| Service | URL |
| --- | --- |
| Frontend | http://localhost:5173 |
| Desktop client | `make desktop` - a native window, not a URL |
| API | http://localhost:8000 |
| API docs | http://localhost:8000/docs |

Register at http://localhost:5173/register. Email is sent through the Gmail API
and nothing else, so how you get the verification link depends on whether
`GMAIL_CREDENTIALS_B64` is set - see
[Email in development](docs/development.md#email-in-development).

> With no credentials configured, emails are written to the log instead of sent.
> logifyx masks `token=...` out of the logged URL, so set `LOG_MASK=false` to make
> the link usable locally.

`make help` lists every task.

### The simple path: just record money

Most small businesses do not need invoices, customers, or suppliers. They need to note
what came in and what went out. **Billing** is that screen, and it is first in the
navigation:

- Three buttons - *Money in*, *Money out*, and *Transfer*.
- Type an amount and a note. The date defaults to today, the category and the cash
  account default to sensible choices, and the form stays open so a week of receipts
  can be entered in a row.
- Nothing else is required. No customer, no supplier, no invoice.
- Choose where it landed or came from: a cash box, any bank account, or a card. Add a
  bank account or register a card without leaving the screen, and move money between two
  of your own accounts with *Transfer*.

**A bill with nobody's name on it is an expense, not a payable** - and that is the
correct treatment, not a shortcut. A payable exists because you owe a specific party;
once the money has left your hand there is nothing owed and nobody to owe it to. So
money out is *debit expense, credit cash*, money in is *debit cash, credit income*, and
the accounting equation holds without inventing a party.

Because each entry is a real ledger posting, it shows up in the trial balance, the P&L,
the cash flow statement, the dashboard, and the analytics trend without anything else
being configured. There is no billing table - a parallel store of "the user's simple
view" would be a cache that can disagree with the ledger.

To correct a mistake, **reverse** the entry. There is no delete and no edit: a posted
entry is immutable here, so the honest undo is an opposite entry that nets it to zero,
which is also what an auditor expects to find. The original stays on the record.

#### Accounts and cards

**Accounts** is its own entry in the sidebar, on both the website and the desktop app: every
bank account, cash box and card in one list, with every detail editable in place - which
bank, whose name, the account number. The same panel also sits at the foot of Billing, so a
card can be added without leaving the screen you were recording on.

Two decisions there are worth stating outright, because both are easy to get wrong and
expensive to get wrong:

**No card number is ever stored.** Adding a card asks for its number, checks the Luhn
digit, works out the scheme and the last four digits, and throws the rest away. There is
no column for a PAN and no field to return one in - a test queries
`information_schema.columns` to keep it that way. Storing one would put this entire
database inside PCI DSS scope, and the last four digits are what a card receipt and a
bank statement both print anyway.

**A bank account number is stored in full, encrypted** - the opposite call, for a reason.
You have to quote an account number to be paid, print it on an invoice, and match it to a
statement, so throwing it away would stop the software doing its job; and unlike a card
number it carries no scheme obligations. It is encrypted at rest with the same key material
as a 2FA secret, only the last four digits are shown in lists, and one route behind
`account:read` returns the whole thing. Alongside it you can record which bank the account
is at, whose name it is in, and the name on a card.

**A credit card is a liability, not a place you have money.** Registering one creates an
account under Current Liabilities, so spending on it increases what you owe rather than
reducing what you hold. It is offered when recording a payment - you genuinely can pay
with it - but it never joins a cash balance. A *debit* card is the opposite case: it gets
no account of its own, because it is a way of using a bank account you already have, and
a second account would double-count the same money.

**A transfer is not income or an expense.** Moving your own money between accounts -
including paying off a card - has no category, because there is nothing earned or spent
to file it against, and it stays out of the money-in and money-out totals. Counting it
would show income that never arrived from anywhere.

Customers, GST invoices, suppliers, and scanned-document capture all still exist for
when they are genuinely needed. Nothing forces you through them.

### Optional: reading scanned invoices

Document upload works without this - the file is stored and can be attached to a
bill entered by hand. What the extra adds is *reading* it.

```bash
cd backend && uv sync --extra ocr
```

Digital PDFs work immediately: `pypdf` reads their text layer, which is exact and
needs nothing else installed. **Images additionally need the Tesseract binary**,
which is a system package `pip` cannot install:

| Platform | Install |
| --- | --- |
| Windows | [UB-Mannheim installer](https://github.com/UB-Mannheim/tesseract/wiki) |
| Debian/Ubuntu | `apt install tesseract-ocr` |
| macOS | `brew install tesseract` |
| Docker | already in the image - `backend/Dockerfile` installs it |

The Windows installer does not add itself to `PATH`, so set `TESSERACT_CMD` in
`.env` if the app cannot find it. That path is a *host* path: both compose files
override it with `/usr/bin/tesseract` for the container, since `env_file` would
otherwise hand a Windows path to a Linux image.

`OCR_LANGUAGES` names Tesseract language packs, and each one has to be installed
next to the binary - `eng+hin` needs `tesseract-ocr-hin` added to the `apt-get`
line in `backend/Dockerfile`, or recognition fails instead of degrading. `GET /api/v1/documents/capabilities` reports what
the server can actually read, and the Documents screen says so plainly rather than
offering an upload button that fails.

The heavyweight engines are deliberately not used: PaddleOCR pulls PaddlePaddle
(~500 MB) and EasyOCR pulls torch (~2 GB), which contradicts "one person can run
this on a small VPS". Tesseract is ~30 MB and reads a GST invoice well.

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
non-mutating form - it reports rather than rewrites). Narrowing to `app tests`
locally is faster and covers everything you actually edit.

[`ruff`](https://docs.astral.sh/ruff/) is linter and formatter in one - well under
a second across the whole backend. Beyond style it enforces two things that matter here: `T20` bans
`print()`, so logging cannot bypass logifyx and lose its credential masking; and
`ASYNC` catches blocking calls inside `async def`, which stall the whole event
loop rather than one request.

[`mypy`](https://mypy-lang.org/) runs in `strict` mode. Its real job in this
codebase is making `None` impossible to ignore - `User.password_hash` is nullable
(magic-link and invited users have no password), and mypy is what forces every
call site to handle that before reaching Argon2.

### Tests

```bash
uv run pytest                   # 714 tests, needs postgres + redis
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
make desktop                           # desktop client → a native window
```

### Frontend equivalents

```bash
npm run lint          # eslint . --max-warnings 0    (ruff's counterpart)
npm run typecheck     # tsc -b --noEmit              (mypy's counterpart)
npm run format        # prettier --write             (ruff format's counterpart)
npm run build         # tsc -b && vite build
```

`npm run lint:fix` and `npm run format:check` are also defined - the latter is the
non-mutating form, which is what CI uses.

> **On Windows, run the raw commands above from PowerShell, not Git Bash.** Git
> Bash's MSYS layer rewrites environment values that look like Unix paths when it
> spawns a native Windows process, so `API_V1_PREFIX=/api/v1` reaches Python as
> `C:/Program Files/Git/api/v1` and the app dies at import with "A path prefix must
> start with '/'". Not a bug in the app, but it makes every backend command fail
> confusingly.
>
> **`make` targets are safe from either shell.** The [Makefile](Makefile) needs a
> POSIX shell for its recipes, so it resolves Git Bash explicitly and sets
> `MSYS2_ENV_CONV_EXCL=*` to switch that translation off. `make test` and
> `make check` work from PowerShell, cmd, and Git Bash alike.

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
│   └── tests/               pytest - 714 tests
├── frontend/                React 19 · TypeScript · Vite · Tailwind v4
│   └── src/
│       ├── components/      Design-system primitives and layout
│       ├── features/        auth, dashboard, organizations, settings, theme
│       ├── lib/             HTTP client, env validation, formatting
│       └── routes/          TanStack Router tree
├── app_frontend/            Flutter desktop client · Windows · macOS · Linux
│   └── lib/
│       ├── theme/           The web app's oklch tokens, converted at runtime
│       ├── widgets/         The same design system, rendered natively
│       ├── features/        One directory per screen, mirroring frontend/src/features
│       └── core/            Env, HTTP client with a cookie jar, exact-decimal money
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
  repository.py    Data access - the only layer touching the session
  service.py       Business rules - transport-agnostic
  router.py        HTTP surface - thin
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
two parties hold it, and we cannot tell which is legitimate - so the whole
session lineage is revoked and the event is audited as critical.
([`auth/service.py`](backend/app/modules/auth/service.py))

**Permissions ride in the access token; a Redis epoch counter overrides it.**
Embedding permissions means authorization costs no database query. Staleness is
bounded by the 15-minute token TTL, and anything that must apply immediately -
role change, suspension, password change, sign-out-everywhere - bumps the user's
epoch, invalidating every outstanding token at once.
([`auth/dependencies.py`](backend/app/modules/auth/dependencies.py))

**The active organization comes from the signed token, never from the URL.**
There is no organization id in any API path for a client to tamper with, which
makes cross-tenant access structurally impossible rather than merely checked.
([`organizations/router.py`](backend/app/modules/organizations/router.py))

**Permissions are code; roles are data.** A permission is a capability the
software implements, so it lives in an enum - the enum *is* the contract, it is
greppable, and it cannot drift from a table. Roles are per-organization rows
composing those slugs. ([`rbac/permissions.py`](backend/app/modules/rbac/permissions.py))

**No account enumeration.** Password reset, magic link, and OTP all respond
identically whether or not the account exists, and login burns an Argon2 cycle on
a miss so timing cannot distinguish the two either.

**Password policy: 6 characters minimum, with at least one uppercase letter, one
lowercase letter, and one special character.** Because composition rules of this
shape reliably produce `Password@1` - the first thing any cracking dictionary
tries - a blocklist backstop also rejects weak roots however they are dressed up
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

**Backend** - FastAPI, Python 3.13, uv, SQLAlchemy 2 (async), Alembic,
PostgreSQL 17, Redis 7, Pydantic v2, Argon2id, PyJWT, pyotp, httpx, logifyx.

**Frontend** - React 19, TypeScript, Vite 7, Tailwind CSS v4, TanStack
Router + Query + Table, React Hook Form, Zod, Recharts, cmdk, Sonner, Lucide,
Motion.

**Desktop** - Flutter 3.44, Dart 3.12, Material 3, Riverpod, go_router, Dio with a
persisted cookie jar, fl_chart, Lucide. Same API, same design tokens; see
[app_frontend/README.md](app_frontend/README.md) for the four places a native window
honestly differs from a browser.

**Infrastructure** - Docker, Nginx, Let's Encrypt, GitHub Actions.

---

## Verified state

Everything below was run against real infrastructure, not mocks:

```
backend    714 tests passing (PostgreSQL 17 + Redis 7)
backend    ruff: all checks passed
backend    alembic: applies, reverses, and reports zero drift
frontend   tsc -b: 0 errors
frontend   eslint: 0 problems (type-aware rules enabled)
frontend   vite build: succeeds, 0 vulnerabilities in the dependency tree
desktop    flutter analyze: 0 issues
desktop    42 tests passing, including a live session round-trip against the API
desktop    Windows release binary builds, starts, and restores its session
           across three consecutive relaunches with no token reuse detected
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

**[docs/](docs/README.md)** is the index: reading paths by what you are trying to do, and
a map of how the nine documents relate. Every page carries a nav bar to every other, so
any of the links below is a fine place to start.

| Document | Contents |
| --- | --- |
| [docs/spec.md](docs/spec.md) | The requirements: product goals, modules, delivery model, non-negotiables |
| [docs/architecture.md](docs/architecture.md) | Layering, request lifecycle, module structure, diagrams |
| [docs/database.md](docs/database.md) | Schema, ER diagram, indexes, migration workflow |
| [docs/accounting.md](docs/accounting.md) | Double-entry invariants, exact money, reversals, numbering, fiscal calendar |
| [docs/api.md](docs/api.md) | Auth flows, error contract, pagination, and the platform + documents endpoints; `/docs` is authoritative for the rest |
| [docs/security.md](docs/security.md) | Threat model and every control, with rationale |
| [docs/security-audit.md](docs/security-audit.md) | Nine findings against the running code, each with its fix and how to verify it |
| [docs/development.md](docs/development.md) | Local workflow, conventions, testing, adding a module |
| [docs/deployment.md](docs/deployment.md) | VPS setup, TLS, backups, zero-downtime deploys |

---

## Delivery status

The delivery model is **parallel build-out**: modules are developed concurrently
rather than gated on the previous one signing off. The quality bar is unchanged -
strict mypy, real tests against real PostgreSQL and Redis, and a documented
rationale per module - but a module ships as soon as *it* is green, not when its
predecessor is.

The one thing that stays sequenced is the **dependency graph**, because it is
arithmetic rather than process: sales and inventory post into the ledger, so the
ledger's posting contract has to exist before anything can call it. That contract
is [`PostingService.post_simple`](backend/app/modules/accounting/service.py) and
it is stable, so everything downstream of it can now proceed in parallel.

Modules not yet built appear in the navigation as visibly disabled entries rather
than links to nothing.

- [x] **Stage 1 - Foundation.** Monorepo, Docker, auth, users/organizations,
      RBAC, audit, CI/CD, design system, dashboard, deployment.
- [x] **Stage 2 - Accounting core.** Chart of accounts, journals, ledgers,
      double-entry bookkeeping, trial balance, P&L, balance sheet, cash flow.
      Posted entries are immutable and corrected only by reversal; periods lock;
      entry numbering is gap-free under concurrency. Frontend screens built.
- [x] **Stage 3 - Customers & sales.** CRM, leads, quotations, sales orders,
      invoices, payments. Invoices post real double-entry to the ledger, GST splits
      CGST/SGST vs IGST by place of supply, payments allocate many-to-many across
      invoices. Frontend screens built. *PDF generation is not yet built.*
- [x] **Stage 4 - Purchases & inventory.** Suppliers, purchase orders, goods
      receipt, warehouses, stock movements, barcodes. Weighted-average valuation
      that reconciles exactly to the Inventory account, goods receipt accruing
      Goods Received Not Invoiced, bills claiming input GST, COGS on sale.
      Frontend screens built.
- [x] **Stage 5 - OCR & document intelligence.** Upload a supplier invoice; the
      GSTIN, invoice number, date, and amounts are read out of it with per-field
      confidence, the supplier is matched by GSTIN, and likely duplicate invoices
      are flagged. **OCR never posts to the ledger** - it pre-fills a form, and
      confirming goes through the same `BillService` as a hand-entered bill.
      A digital PDF is read from its text layer (exact); images go to Tesseract.
      Requires `uv sync --extra ocr` plus the Tesseract binary; without them the
      app runs normally and reports document reading as unavailable.
- [ ] **Stage 6 - AI assistant.** Conversational interface, RAG over business
      data, natural-language queries, forecasting.
- [ ] **Stage 7 - Automation platform.** Visual workflow builder, triggers,
      scheduled jobs, approval flows, messaging integrations.
- [x] **Stage 8 - Analytics & reporting.** A real dashboard: revenue, expenses,
      profit, cash, receivables, payables, and stock, each with a like-for-like
      period comparison, plus a twelve-month trend and customer/product rankings.
      Every figure is computed by the same `ReportingService` that renders the P&L,
      so a tile cannot disagree with the statement behind it. Also ships
      **control-account reconciliation** - receivables, payables, and stock derived
      twice, from the ledger and from the documents, and compared. *Custom report
      builder and scheduled exports are not yet built.*
- [ ] **Stage 9 - Enterprise.** Advanced multi-tenancy, API keys, webhooks, SSO,
      compliance, passkeys.
- [ ] **Stage 10 - Production hardening.** Security review, monitoring, load
      testing, performance tuning.

### A note on the dashboard

Earlier revisions of this README warned that the dashboard's revenue, expense, and
profit figures were illustrative placeholders labelled "Sample". **They are not any
more** - as of Stage 8 every figure is derived from posted ledger entries, and the
fabricated series has been deleted rather than left behind a flag.

Two rules the dashboard now follows, both about not overclaiming:

- **A month-to-date figure is compared against the same number of days**, not
  against the whole previous month. On the 3rd of the month the naive comparison
  reports revenue "down 90%", and a dashboard that does that is misleading for most
  of every month.
- **A percentage change with no basis is not shown as a number.** Going from ₹0 to
  ₹50,000 is not "+100%" - it is undefined, so the tile says "no prior data".

If the ledger ever disagrees with the documents behind it, the dashboard leads with
that rather than quietly rendering figures derived from a broken ledger.

---

## Licence

Proprietary. All rights reserved.
