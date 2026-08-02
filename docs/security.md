# Security

Every control below exists for a stated reason. Where a common alternative was
rejected, the reason is given - a control whose rationale nobody remembers is a
control that gets removed in the next refactor.

---

## Threat model

What this system is actually defending against, in rough order of likelihood:

| Threat | Primary control |
| --- | --- |
| Credential stuffing from a breach elsewhere | Argon2id, per-account lockout, edge + app rate limiting, 2FA |
| Account enumeration to build a target list | Identical responses *and timing* for existing/absent accounts |
| XSS stealing a session | Access token in memory only; refresh token HttpOnly; strict CSP |
| Stolen refresh token used indefinitely | Rotation with reuse detection; lineage revocation |
| CSRF against state-changing endpoints | `SameSite=Strict` cookie; bearer token required |
| Cross-tenant data access | Organization identity from the signed token, never from a URL |
| Privilege escalation via mass assignment | Separate request/response schemas; `extra="forbid"` |
| Insider action denied later | Append-only audit trail with actor, IP, request id, and diff |
| Leaked database dump | Passwords hashed, tokens digested, 2FA secrets encrypted |
| A tenant locking itself out | Owner cannot be removed, suspended, or demoted |

Explicitly **out of scope for Stage 1**: DDoS beyond basic rate limiting, insider
threat at the infrastructure level, and supply-chain attestation. Those belong to
Stage 10.

---

## Authentication

### Password storage - Argon2id

Parameters are configurable and recorded in the hash itself.

Argon2id is memory-hard, so GPU and ASIC cracking gains far less against it than
against bcrypt or PBKDF2. It won the Password Hashing Competition and is the
current OWASP recommendation.

Because the parameters live in the stored hash, raising the cost later re-hashes
users transparently on their next successful login (`password_needs_rehash`)
rather than locking anyone out.

### Password policy - composition rules, with a blocklist backstop

Enforced rules ([`auth/password_policy.py`](../backend/app/modules/auth/password_policy.py)):

| Rule | Value |
| --- | --- |
| Minimum length | 6 |
| Maximum length | 128 |
| Uppercase letter | required |
| Lowercase letter | required |
| Special character | required (`string.punctuation`) |
| Digit | **not** required (`REQUIRE_DIGIT` flips it on) |

Two rules apply beyond that composition set, and both are deliberate:

**A blocklist backstop.** Composition requirements are satisfied by precisely the
passwords cracking dictionaries enumerate first - `Password@1` clears every rule
above at ten characters. So the password is reduced to its letters-only root and
checked against a weak-root list. Three normalisations are compared, because none
subsumes the others:

| Input | Normalisation that catches it | Root |
| --- | --- | --- |
| `Password@1` | strip non-letters | `password` |
| `P@ssw0rd` | reverse leetspeak | `password` |
| `Passw0rd!` | trim edge padding, *then* reverse leetspeak | `password` |

Applying leetspeak unconditionally is not sufficient: it rewrites trailing padding
into letters, so `Password@1` would become `passwordai` and miss.

**No personal information.** The user's own name and email local part are
rejected, since targeted guessing starts there.

**Known limitation - caseless scripts.** Requiring both letter cases means a
password written wholly in Devanagari, Arabic, Chinese, Japanese, Hebrew, or Thai
cannot satisfy the policy, since `str.isupper()`/`str.islower()` are both false
for every character in those scripts. Affected users must mix in Latin
characters. This is an inherent consequence of mandating both cases, not a bug;
a test in `tests/test_password_policy.py` pins the behaviour so it stays visible
rather than being discovered by a locked-out user.

Whitespace is not accepted as the special character - a space the user cannot see
is not usable variety, and a pasted password with stray spaces fails at login in a
way nobody can diagnose.

The enforced policy is served from `GET /auth/password-policy`, so the client's
hints can never contradict what the server accepts. The frontend consumes it
through one shared module
([`features/auth/passwordPolicy.ts`](../frontend/src/features/auth/passwordPolicy.ts))
rather than restating the rules per form.

### Account enumeration

Password reset, magic link, OTP request, and resend-verification all return the
same message whether or not the account exists.

Login goes further: on a missing account it calls `dummy_password_verify()`,
burning an equivalent Argon2 cycle. Without that, "no such user" returns in
microseconds while a real user costs ~50 ms - a trivially measurable oracle. A
test asserts the two timings stay within the same order of magnitude.

Registration is the deliberate exception: it *does* return 409 on a duplicate
email. Pretending to succeed would leave the user waiting for a verification
email that never arrives, with no path to recovery. Rate limiting is the
appropriate control there instead.

### Brute-force protection

Two independent layers:

- **Per-account lockout** (Redis) - 5 failures locks the account for 15 minutes.
  Keyed on email, not IP: an attacker rotates IPs trivially, and IP-based locking
  punishes everyone behind one NAT.
- **Per-IP rate limiting** - at the edge (Nginx, 2 r/s on auth paths) and in the
  application. Fixed-window in the app, because one `INCR` plus one `EXPIRE` keeps
  it cheap enough to sit in front of everything.

2FA failures count toward the same account lockout budget. Without that, the
second factor is brute-forceable at leisure once the password is known.

The application limiter **fails open** if Redis is unavailable. Fail-closed would
turn a cache outage into a total outage - a worse trade for a protective layer.

### Two-factor authentication - TOTP

Standard parameters (6 digits, 30-second step, SHA-1) because that is what every
authenticator app actually implements. Deviating is cryptographically defensible
and practically useless: most apps ignore the algorithm parameter in the
provisioning URI and compute SHA-1 regardless, producing codes that never
validate.

Two distinct replay defences:

- **A one-step window** tolerates ±30 s of clock skew. Wider windows multiply the
  guessing surface.
- **Single-use enforcement.** Because a code stays valid for up to 90 seconds, an
  attacker who observes one can replay it. Every accepted code is burned in Redis
  via `SET NX` - atomic, so two concurrent requests cannot both win.

Enrolment requires proving a valid code before 2FA takes effect. A secret is
written during setup but `totp_enabled_at` stays null until confirmed, so a
mis-scanned QR cannot lock anyone out.

Secrets are **Fernet-encrypted at rest** (AES-128-CBC + HMAC). A leaked database
must not hand over working second factors. Recovery codes are stored as Argon2
hashes and shown exactly once.

---

## Session management

### Token split

|  | Access token | Refresh token |
| --- | --- | --- |
| Format | JWT (HS256) | 256-bit opaque random |
| Lifetime | 15 minutes | 7 days, or 30 with "remember me" |
| Storage (client) | Memory only | HttpOnly, Secure, SameSite=Strict cookie |
| Storage (server) | Stateless | SHA-256 digest in PostgreSQL |
| Revocation | Redis epoch / session marker | Row update |

**Why the access token is not in `localStorage`:** any XSS on the page can read
it, and a stolen token is valid until it expires. A module-scoped variable dies
with the tab.

**How a page reload stays signed in:** the HttpOnly refresh cookie, which
JavaScript cannot read at all. On boot the app calls `/auth/refresh` once and gets
a fresh access token. The long-lived credential is never reachable from JS; the
short-lived one never outlives the tab.

**Why refresh digests, not Argon2:** these are 256-bit random values, not human
passwords. There is no dictionary to attack, so a slow KDF buys nothing and would
add latency to every refresh.

### Rotation with reuse detection

Every refresh mints a new token and revokes the old one, recording
`rotated_to_id`.

The stolen-token problem is that an attacker who copies a refresh token can
refresh forever, and the server cannot tell them from the real user. Rotation does
not prevent that - it makes it **detectable**. The first party to refresh
invalidates the other's copy, so a second use of an already-rotated token is
reliable evidence that two parties hold it.

Response: revoke the entire session lineage, bump the user's token epoch, and
audit it as `critical`. Both parties must re-authenticate.

### Revoking a stateless token

Two mechanisms, because they answer different questions:

- **Epoch counter** (`personalerp:auth:epoch:<user_id>`) - every token carries the
  user's epoch; incrementing it invalidates all of them at once. Used for password
  change, sign-out-everywhere, role change, suspension, and removal.
- **Per-session marker** (`personalerp:auth:revoked-sid:<session_id>`) - revokes one
  device without signing the user out everywhere.

Both are checked in a single pipelined Redis round trip. Entries only need to
outlive the longest access token, after which the JWT expires on its own.

Rotation deliberately does **not** set a revoked-session marker. Rotation is not a
security event, and marking it would 401 any request already in flight with the
previous token.

---

## Authorization

### Permissions in code, roles in data

A permission is a capability the software implements, so it lives in an enum. If
`invoice:approve` existed as a row but no endpoint checked it, the row would be a
lie; if an endpoint checked a permission absent from the table, authorization
would silently fail. The enum cannot drift from the code, it is greppable, and it
type-checks.

Roles are per-organization rows holding a JSONB array of grant slugs. Wildcards
(`invoice:*`, `*:*`) are expanded eagerly at token-issue time, so the hot path is
a set-membership test with no pattern matching.

Unknown grants are **dropped** during expansion, not preserved. A permission
removed from the catalogue in a later release must stop granting access.

### Staleness

Permissions in the token means authorization costs no database query, bounded by
the 15-minute TTL. Anything that must apply immediately bumps the epoch:

- role changed → epoch bump → next request re-mints with new permissions
- member suspended or removed → epoch bump → access ends within milliseconds
- a role's permissions edited → epoch bump for every holder

`GET /auth/permissions` resolves live from the database, for a client that needs
current truth rather than what was true at issue time.

### Tenant isolation

The active organization comes from the signed token. No API path contains an
organization id, so there is nothing for a client to tamper with - cross-tenant
access is structurally impossible rather than merely checked.

Defence in depth on top of that: `RoleRepository.get_scoped` puts the tenant
filter *in the query* rather than checking after the fetch, so a cross-tenant id
returns no row instead of relying on a caller's `if`.

### Lockout prevention

An organization must not be able to destroy its own administrability:

- the owner cannot be removed, suspended, demoted, or leave;
- exactly one owner per organization, enforced by a **partial unique index**, not
  only application code;
- a role still held by members cannot be deleted (`RESTRICT` foreign key plus a
  check that returns an actionable message);
- built-in roles cannot be deleted or renamed, though their permissions are
  editable;
- the Owner role cannot have `*:*` removed.

---

## Input handling

- **Separate request and response schemas.** A response schema reused as a request
  schema is how `is_superuser` becomes mass-assignable.
- **`extra="forbid"`** on every request schema. An unknown field is a 422, not a
  silent ignore - a client's typo should be reported, not swallowed.
- **`exclude_unset`** on partial updates, so "field omitted" is distinguishable
  from "field set to null". Without it, a client sending only `theme` would blank
  the user's phone number.
- **Allow-listed sort fields.** `sort_by` arrives from a query string;
  interpolating it into `ORDER BY` is an injection vector, so it is resolved
  against columns the repository opts into.
- **Parameterised queries throughout** via SQLAlchemy. No string-built SQL.
- **Open-redirect guard.** `redirect_path` on a magic link must be relative and
  must not begin with `//`.

---

## Secrets and logging

**logifyx redacts by default.** Passwords, tokens, and secrets are masked in every
log line, which is what makes it safe to log request metadata at all.

The audit trail has an independent redaction backstop
(`audit/service.py::redact`) covering `password`, `token`, `totp_secret`,
`recovery_codes`, `api_key`, and more - recursively. A test drives a real password
change end to end and asserts neither the old nor the new password appears
anywhere in the trail.

Production configuration is validated at boot. The app **refuses to start** if
`SECRET_KEY` is a placeholder, `DEBUG` is true, CORS is `*`, `ENCRYPTION_KEY` is
missing, or the database password is still a default. Crashing at boot is strictly
better than silently serving traffic with a placeholder signing key.

### Card numbers - staying out of PCI DSS scope

**No Primary Account Number is stored anywhere.** Cards are on file so a payment can say
which one it went on, and what is kept is the scheme and the last four digits - the two
things a card receipt and a bank statement already print.

This is deliberate scope avoidance, not a shortcut. Persisting a PAN would pull this
entire database, its backups, its replicas, and every host that touches them into PCI DSS
scope, in exchange for a convenience the product does not need: nothing here charges a
card, so the full number has no use after the moment it is typed.

How that is held in place:

- `billing/cards.py` is the only module that ever handles a full number. It imports
  nothing from the rest of the app, every function takes a number and returns something
  that is not one, and `inspect_card_number` returns exactly the two facts that get
  persisted. The PAN exists as a local variable for the length of one call.
- The `payment_card` table has **no column** it could go in. A test asserts that against
  `information_schema.columns` rather than trusting the model, so adding one fails the
  build. `CardRead` has no field to return one in either.
- **A rejected number is never echoed back.** The request schema rejects letters by
  pattern rather than by quoting the value, and the 422 handler forwards messages, never
  inputs. A test posts a malformed number and asserts the digits do not appear in the
  response.
- Both clients clear the field as soon as the request succeeds, and neither sets an
  autofill hint on it - the one "helpful" platform default that would undo the whole
  arrangement by inviting the browser or OS to store the number instead.

The Luhn check is duplicated client-side, which is safe because Luhn is a fixed algorithm
that cannot drift. The issuer-range table that identifies the scheme is **not** duplicated
- it lives only on the server.

---

## Transport and headers

TLS 1.2/1.3 only, HSTS with a two-year max-age and preload, OCSP stapling,
session tickets disabled (they weaken forward secrecy).

Response headers: `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
`Referrer-Policy: strict-origin-when-cross-origin`,
`Cross-Origin-Opener-Policy: same-origin`, and a `Permissions-Policy` denying
geolocation, microphone, and camera.

CSP on API responses is `default-src 'none'; frame-ancestors 'none'; base-uri
'none'; form-action 'none'` - the API returns only JSON, so "load nothing, frame
nothing" is both correct and maximally strict.

`Referrer-Policy` specifically protects magic-link and reset tokens, which appear
in URLs and would otherwise leak to third parties through the `Referer` header.

HSTS is production-only. Sending it over plain HTTP in development would pin
`localhost` to HTTPS in the developer's browser and break every other local
project on that port.

---

## OWASP Top 10 (2021)

| Risk | Controls |
| --- | --- |
| A01 Broken access control | Token-derived tenancy, permission enum, scoped queries, owner protections, deny-over-grant overrides |
| A02 Cryptographic failures | Argon2id, Fernet at rest, TLS 1.2+, HSTS, hashed tokens |
| A03 Injection | Parameterised ORM queries, allow-listed sorts, Pydantic validation, Jinja autoescape |
| A04 Insecure design | Staged delivery, threat model, lockout prevention, reversible migrations |
| A05 Misconfiguration | Boot-time production validation, no docs in production, non-root containers, internal-only data network |
| A06 Vulnerable components | Pinned lockfiles, `--frozen` installs in CI, zero npm advisories |
| A07 Auth failures | 2FA, lockout, rotation with reuse detection, no enumeration, session revocation |
| A08 Integrity failures | Append-only audit, SHA-pinned image tags, migration drift check in CI |
| A09 Logging failures | logifyx everywhere with redaction, audit trail, request-id correlation |
| A10 SSRF | No user-supplied URLs are fetched server-side in Stage 1 |

---

## Deferred to later stages

Stated plainly rather than left implied:

- **Passkeys / WebAuthn** - Stage 9.
- **SSO / SAML** - Stage 9.
- **Have I Been Pwned range check** - Stage 10. The local blocklist covers the
  worst offenders with no network dependency; the k-anonymity API is the proper
  version.
- **Database-level audit immutability** - Stage 9. A trigger denying
  `UPDATE`/`DELETE` to the application role. Today it is enforced by the absence
  of any code that mutates the table.
- **Secrets manager** - Stage 10. Currently environment variables.
- **API keys and webhook signing** - Stage 9.
- **Automated dependency scanning in CI** - Stage 10.
