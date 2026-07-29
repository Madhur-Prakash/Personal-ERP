# Development

## Setup

Requires Docker, [uv](https://docs.astral.sh/uv/), and Node 24.

```bash
make setup     # .env, dependencies, services, migrations
make up        # everything in Docker
```

Or run the app on the host with only the data services in containers, which gives
faster reloads and a working debugger:

```bash
make services       # PostgreSQL, Redis, Mailpit
make dev-api        # terminal 1
make dev-web        # terminal 2
```

When running on the host, point `.env` at `localhost`:

```env
POSTGRES_HOST=localhost
REDIS_HOST=localhost
SMTP_HOST=localhost
SMTP_PORT=1025
SMTP_TLS=false
```

`make help` lists every task.

---

## Email in development

**Use Mailpit - http://localhost:8025.** `make up` points the backend's SMTP at
it, so every email is captured with working links and no real provider is needed.

There is also a no-SMTP mode: with `SMTP_HOST` empty the mailer logs the message
body instead of sending it. **But logifyx's masking redacts `token=...` from the
logged URL**, so the link cannot be used from the log:

```
http://localhost:5173/verify-email?****
```

That redaction is correct - a one-time credential should not sit in a log file -
so treat the log path as a way to confirm *that* an email was generated, and
Mailpit as the way to actually click it. Set `LOG_MASK=false` if you genuinely
need the raw value locally.

---

## Backend conventions

### Module layout

```
modules/<name>/
  models.py        SQLAlchemy tables
  schemas.py       Pydantic contracts
  repository.py    Data access - the only layer touching the session
  service.py       Business rules - raises domain exceptions, never HTTP ones
  router.py        HTTP - thin; parse, delegate, shape
```

Dependencies point inward. Violating that is the one thing to catch in review.

### Rules that are not negotiable

**Never call `commit()` in a service.** The request-scoped transaction in
`get_db` owns that boundary. Use `flush()` to get a primary key or to surface a
constraint violation early.

**Never read `os.environ`.** Import `get_settings()`. One file holds every knob,
which is what makes configuration testable and discoverable.

**Never use `logging.getLogger` or `print`.** Use
`app.core.logging.get_logger(__name__)`. All logging goes through logifyx, which is
where redaction and request context come from.

**Register new models in `db/registry.py`, in the same commit.** Alembic
autogenerate only sees imported models; forgetting this produces an empty
migration and silently omits the table.

**Separate request and response schemas.** A response schema reused as a request
schema is how `is_superuser` becomes mass-assignable.

**Eager-load relationships you will serialise.** Async SQLAlchemy raises
`MissingGreenlet` on a lazy load outside the greenlet context. Use
`selectinload`, or assign the related object at construction:

```python
# Wrong: `.role` is not loaded, and reading it in the response schema raises.
Invitation(role_id=role.id, ...)

# Right: the relationship is populated with no extra query.
Invitation(role=role, ...)
```

This is a real bug we hit and fixed - see the comment in
`organizations/service.py`.

### Adding a permission

1. Add it to the `Permission` enum in `rbac/permissions.py`.
2. Add it to a `PermissionGroup`. A test asserts every permission belongs to
   exactly one group, so a forgotten entry fails CI.
3. Grant it to the relevant `SYSTEM_ROLE_PERMISSIONS` entries.
4. Enforce it: `Depends(require_permission(Permission.YOUR_THING))`.

Because permissions live in code, one that is missing from the catalogue cannot be
granted through the UI at all - which is the point.

---

## Frontend conventions

### Structure

```
src/
  components/ui/       Primitives - no data fetching
  components/layout/   Shell, palette, theme toggle
  features/<name>/     api.ts + page components, colocated
  lib/                 HTTP client, env validation, formatting
  routes/              Router tree
  types/api.ts         Mirrors of the backend contracts
```

### Rules

**Server state goes in TanStack Query. Client state goes in React state.** There
is no global store; nothing in Stage 1 needs one.

**Never store a token in `localStorage`.** The HTTP client holds the access token
in memory; the refresh token is an HttpOnly cookie. Both are deliberate.

**Never hard-code an API path in a component.** Add it to the feature's `api.ts`,
so a route rename touches one file and a typo is a compile error.

**Use semantic colour tokens.** `bg-surface`, not `bg-zinc-900`. Dark mode is one
set of variable overrides, and literal colours break it.

**A navigation control must be a link, not a button.** Use `buttonClasses()` on a
`<Link>`. A `<Link>` inside a `<button>` is invalid HTML, and a `<button>` that
navigates loses middle-click and "open in new tab".

**Mutations never retry.** Configured globally. A retried POST can duplicate an
invoice.

### Type-aware linting is on

`no-floating-promises` and `no-misused-promises` catch the class of bug TypeScript
alone misses. `void promise` is the explicit opt-out:

```tsx
onClick={() => void save()}
```

---

## Testing

```bash
make test              # backend, needs PostgreSQL + Redis
make test-cov          # with coverage
cd backend && uv run pytest tests/test_auth_api.py -q
cd backend && uv run pytest -k "two_factor" -v
```

### How isolation works

Each test runs in a transaction that is always rolled back, with
`join_transaction_mode="create_savepoint"` so the application's own `commit()`
calls become savepoint releases. Production transaction boundaries run for real;
the outer rollback erases everything.

Redis gets database index 15, flushed around every test. Auth state lives there,
so leakage would make tests order-dependent.

Argon2 is dialled to its minimum in tests. At production parameters, hashing
dominates the runtime of an auth-heavy suite.

### What to test

The suite is weighted toward places where a bug is expensive:

- token rotation and reuse detection
- permission expansion, including wildcards and unknown grants
- cross-tenant isolation - *attempt* the bad thing and assert it is refused
- owner-lockout prevention
- secret redaction in the audit trail
- account-enumeration resistance, including timing

Use `example.com` for test emails. `email-validator` rejects special-use TLDs like
`.test` and `.local` - correct behaviour for production, and it means those
domains cannot be used in fixtures.

---

## Before opening a pull request

```bash
make check      # lint + typecheck + test, both sides
make db-check   # no migration drift
```

CI additionally verifies migrations are reversible and builds both images.

---

## Debugging

**A request, end to end.** Every response carries `X-Request-ID`. Filter the log
by it:

```bash
tail -f logs/personalerp.log | jq 'select(.request_id == "<id>")'
```

Audit rows store the same id, so a business event pivots to its log lines.

**SQL.** Set `DB_ECHO=true`. Off by default because it is deafening.

**Inspect state.**

```bash
make psql
make redis-cli
docker exec personalerp-redis redis-cli -n 0 KEYS 'personalerp:*'
```

**A user seems stuck signed out.** Check their token epoch - anything that bumps
it invalidates outstanding tokens:

```bash
docker exec personalerp-redis redis-cli GET "personalerp:auth:epoch:<user_id>"
```

---

## Gotchas we hit building this

Recorded because each cost real time:

- **`model_validate(obj, update={...})` does not exist.** Pydantic has no `update`
  parameter. Use `with_computed()` in `core/schemas.py`, which validates then
  overlays.
- **`INET` columns return `IPv4Address`, not `str`.** Use the `IpAddress` type from
  `core/schemas.py` at the serialisation boundary.
- **A model method named like a schema field breaks validation.** `from_attributes`
  reads the bound method, not its result. `Invitation.is_expired` is a property for
  exactly this reason.
- **A `lazy="raise"` relationship colliding with a schema field name** trips the
  N+1 guard on every response. `AuditLogRead.from_row` builds explicitly instead.
- **pydantic-settings JSON-decodes list fields before validators run.** `NoDecode`
  is required for comma-separated env vars.
- **TanStack Router requires `search` on `<Link>`** unless `validateSearch` returns
  *optional* properties. `{ redirect?: string }`, not
  `{ redirect: string | undefined }`.
- **Type-aware ESLint rules must be scoped to `**/*.ts{,x}`.** Spreading them
  globally makes ESLint try to type-check its own config file and fail to load.
- **logifyx's formatters drop `extra={...}` silently.** Both the console and JSON
  formatters build output from a fixed set of record attributes, so structured
  fields vanished with no error. `StructuredLogger` in `core/logging.py` folds
  them into the message text so they actually appear - see that class for the
  trade-off.
- **Vite's object-form `manualChunks` matches exact specifiers only.** It will not
  capture `react/jsx-runtime`, producing an empty chunk while React stays in the
  main bundle. Use the function form.
