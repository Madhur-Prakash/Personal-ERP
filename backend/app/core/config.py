"""Application configuration.

Single source of truth for every tunable in the backend. Values resolve in this
order (highest priority first):

    1. Real process environment variables
    2. The ``.env`` file at the repository root
    3. The defaults declared below

Nothing else in the codebase may read ``os.environ`` directly - import
:func:`get_settings` instead. That keeps configuration testable (override the
cache) and makes every knob discoverable in one file.
"""

from __future__ import annotations

import secrets
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal, Self
from urllib.parse import urlsplit

from pydantic import (
    BeforeValidator,
    Field,
    SecretStr,
    computed_field,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/app/core/config.py -> backend/app/core -> backend/app -> backend -> <root>
BACKEND_DIR = Path(__file__).resolve().parents[2]
ROOT_DIR = BACKEND_DIR.parent


class Environment(StrEnum):
    """Deployment environment. Drives safety checks and defaults."""

    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"
    TEST = "test"

    @property
    def is_production(self) -> bool:
        return self is Environment.PRODUCTION

    @property
    def is_local(self) -> bool:
        return self in (Environment.DEVELOPMENT, Environment.TEST)


def _split_csv(value: object) -> object:
    """Accept ``a,b,c`` as well as a real JSON list for list-typed settings.

    Docker Compose and shell exports can only supply strings, so every list
    setting has to tolerate the comma-separated form.
    """
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("["):  # already JSON - parse it as such
            import json

            parsed = json.loads(stripped)
            return [str(item).strip() for item in parsed]
        return [item.strip() for item in stripped.split(",") if item.strip()]
    return value


#: A list setting that accepts ``a,b,c`` from the environment.
#:
#: ``NoDecode`` is essential: without it pydantic-settings tries ``json.loads``
#: on the raw value *inside the env/dotenv source*, before any validator runs,
#: and a bare ``a,b,c`` raises SettingsError. NoDecode hands the string through
#: untouched so ``_split_csv`` can do the work.
CsvList = Annotated[list[str], NoDecode, BeforeValidator(_split_csv)]


def _blank_to_none(value: object) -> object:
    """Treat an empty or whitespace-only value as "not set".

    Needed because a ``.env`` entry cannot be *removed* by the process environment, only
    overridden - and there is no string that means "ignore the file's value". Without
    this, ``DATABASE_URL=`` is a validation error rather than a way to fall back to the
    composed ``POSTGRES_*`` parts, which is exactly what the test suite needs in order to
    guarantee it is not pointed at the developer's real database.

    It also fixes the plain case: an operator who comments out the value but leaves the
    key gets the documented fallback instead of a crash at boot.
    """
    if isinstance(value, str) and not value.strip():
        return None
    return value


#: A URL-shaped override where blank means "fall back to the composed parts".
OptionalDsn = Annotated[str | None, BeforeValidator(_blank_to_none)]

#: Period names accepted in a rate-limit spec, in seconds.
_RATE_PERIODS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def _rate_per_second(spec: str) -> float | None:
    """Requests per second described by ``"<count>/<period>"``, or ``None`` if malformed.

    A deliberate four-line duplicate of :func:`app.core.ratelimit.parse_budget`, which is
    the real parser and the one the limiter uses. Importing it here is a cycle - this
    module is what every other module imports for configuration, including the logging
    setup that ``ratelimit`` acquires a logger from - and the alternative, deferring the
    whole check to startup, would put it somewhere nobody reads.

    Returns a rate rather than a count so that ``600/hour`` and ``10/minute`` compare
    equal, which is the comparison the caller actually wants.
    """
    try:
        count, period = spec.split("/", 1)
        return int(count) / _RATE_PERIODS[period.strip().lower().rstrip("s")]
    except (ValueError, KeyError, ZeroDivisionError):
        return None


class Settings(BaseSettings):
    """Typed, validated application settings."""

    model_config = SettingsConfigDict(
        env_file=(ROOT_DIR / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # the shared .env also holds VITE_*/LOG_* keys
    )

    # ---- Runtime ------------------------------------------------------------
    environment: Environment = Environment.DEVELOPMENT
    debug: bool = True
    app_name: str = "Personal ERP"
    app_version: str = "0.1.0"

    # ---- HTTP ---------------------------------------------------------------
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    api_v1_prefix: str = "/api/v1"
    cors_origins: CsvList = Field(default_factory=lambda: ["http://localhost:5173"])
    allowed_hosts: CsvList = Field(default_factory=lambda: ["localhost", "127.0.0.1"])

    # ---- Edge gateway -------------------------------------------------------
    #: Shared secret the edge proxy stamps on every request it forwards.
    #:
    #: This is what makes "only our own frontend reaches the API" enforceable rather
    #: than aspirational. A browser bundle and a desktop binary are both public code -
    #: anything they can send, an attacker can replay from `curl`, so no header the
    #: *client* holds can authenticate the client. The proxy is different: it runs on
    #: the operator's own machine, and a value it injects server-side is never visible
    #: to a user, a page, or a decompiler.
    #:
    #: So the rule the backend enforces is "this request came through our edge", which
    #: is exactly the property that is actually checkable. Combined with a deployment
    #: where the API publishes no host port (see ``docker-compose.prod.yml``), reaching
    #: the backend at all requires both network access to the internal bridge *and* the
    #: secret.
    #:
    #: Unset means the check is skipped, which is right for local development and for
    #: the test suite. Production refuses to start without it unless
    #: :attr:`allow_direct_backend_access` is explicitly set - see
    #: :meth:`_enforce_production_safety`.
    gateway_secret: SecretStr | None = None

    #: Header carrying :attr:`gateway_secret`. Renameable so it can be made
    #: unremarkable in logs and traces; the default is descriptive on purpose.
    gateway_header: str = "X-Gateway-Key"

    #: Deliberately serve a production deployment with no gateway secret.
    #:
    #: The escape hatch for a topology where the API genuinely is the public edge - a
    #: single Render/Fly service with no proxy of your own in front. Costs the
    #: "only through our edge" guarantee; everything else (auth, rate limits, headers,
    #: host and origin checks) still applies.
    allow_direct_backend_access: bool = False

    #: Enforce ``Origin``/``Referer`` on state-changing requests.
    #:
    #: Defence in depth behind ``SameSite=Strict`` and the bearer token: a browser
    #: cannot forge these two headers, so a cross-site POST from an attacker's page is
    #: rejected before it reaches a handler. Non-browser callers send neither header and
    #: are unaffected - this closes the browser-driven CSRF path, not scripted access.
    enforce_origin: bool = True

    #: Trust ``X-Forwarded-For``/``X-Forwarded-Proto`` when resolving the client.
    #:
    #: True is correct behind any reverse proxy (nginx, Render, Fly, a load balancer).
    #: It is safe here because :func:`app.core.net.client_ip` counts hops from the
    #: *right* - the end nearest our own proxy - rather than taking the left-most
    #: value a client can write freely.
    trust_proxy_headers: bool = True

    #: How many proxies sit between the internet and this process.
    #:
    #: Each one appends the address it saw to ``X-Forwarded-For``, so the real client is
    #: the Nth entry from the right. One for a single nginx or a single PaaS router; two
    #: for a CDN in front of nginx. Too high hands the client control of its own
    #: apparent IP, so this is a value to get right rather than pad.
    trusted_proxy_hops: int = Field(default=1, ge=1, le=8)

    #: Hard ceiling on a request body that is not a file upload.
    #:
    #: Enforced from ``Content-Length`` before the body is read, so a 2 GB JSON payload
    #: costs a rejection rather than memory. File uploads are exempt and bounded by
    #: :attr:`max_upload_bytes` instead, which is enforced while streaming.
    max_request_bytes: int = Field(default=1024 * 1024, ge=16 * 1024)

    #: HSTS ``max-age``, in seconds. Two years, the preload-list minimum.
    hsts_max_age: int = Field(default=63_072_000, ge=0)

    #: Add ``preload`` to the HSTS header.
    #:
    #: Off by default: submitting a domain to the preload list is effectively permanent,
    #: and it commits every subdomain to HTTPS forever. Turn it on deliberately, once
    #: TLS is known to work everywhere.
    hsts_preload: bool = False

    # ---- PostgreSQL ---------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "personalerp"
    postgres_password: str = "personalerp"
    postgres_db: str = "personalerp"

    #: Full DSN override. When set, every ``POSTGRES_*`` part above is ignored.
    #:
    #: Typed as a validated string rather than ``PostgresDsn`` so that a blank value
    #: means "not set" - see :func:`_blank_to_none`. The scheme is still checked, in
    #: :meth:`_validate_dsn_overrides`, so a typo is caught at boot rather than becoming
    #: a connection error on the first query.
    database_url: OptionalDsn = None
    db_pool_size: int = Field(default=10, ge=1)
    db_max_overflow: int = Field(default=20, ge=0)
    db_pool_recycle: int = Field(default=1800, ge=60)
    db_echo: bool = False

    #: Run ``alembic upgrade head`` at startup, before serving anything.
    #:
    #: For a deployment where there is nowhere else to put a release step - a single
    #: Render service, a bare `docker run` - this is what makes a fresh database usable
    #: without a manual migrate. It is idempotent: an up-to-date database does nothing,
    #: an empty one gets every migration.
    #:
    #: Off by default because it is wrong for anything that deploys in stages. Two
    #: instances rolling out together would both run DDL (serialised by an advisory
    #: lock, so one waits rather than fails), and a migration that takes minutes holds
    #: up the boot of every replica. See :mod:`app.db.migrate`.
    run_migrations_on_startup: bool = False

    # ---- Redis --------------------------------------------------------------
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None

    #: Full Redis URL override. When set, every ``REDIS_*`` part above is ignored -
    #: including ``REDIS_DB``, which is how the test suite isolates itself. See
    #: :meth:`_enforce_test_safety`.
    redis_url: OptionalDsn = None

    # ---- Security -----------------------------------------------------------
    secret_key: str = Field(default_factory=lambda: secrets.token_urlsafe(64))
    jwt_algorithm: Literal["HS256", "HS384", "HS512"] = "HS256"
    access_token_ttl_minutes: int = Field(default=15, ge=1, le=1440)
    refresh_token_ttl_days: int = Field(default=30, ge=1, le=365)
    argon2_time_cost: int = Field(default=3, ge=1)
    argon2_memory_cost: int = Field(default=65536, ge=8192)
    argon2_parallelism: int = Field(default=4, ge=1)
    encryption_key: str | None = None

    # ---- Auth policy --------------------------------------------------------
    email_verification_ttl_hours: int = Field(default=24, ge=1)
    password_reset_ttl_minutes: int = Field(default=30, ge=1)
    magic_link_ttl_minutes: int = Field(default=15, ge=1)
    otp_ttl_minutes: int = Field(default=10, ge=1)
    otp_length: int = Field(default=6, ge=4, le=10)
    max_login_attempts: int = Field(default=5, ge=1)
    login_lockout_minutes: int = Field(default=15, ge=1)
    invite_ttl_days: int = Field(default=7, ge=1)

    # ---- Rate limiting ------------------------------------------------------
    #: Budgets are written ``"<count>/<period>"`` (``second``, ``minute``, ``hour``,
    #: ``day``). Each is a token bucket: the bucket holds ``count`` tokens and refills
    #: at ``count`` per ``period``, so a client may burst up to the full budget and then
    #: settles into the sustained rate. See :mod:`app.core.ratelimit` for why a bucket
    #: rather than a fixed window.
    rate_limit_enabled: bool = True

    #: Anything not matched by a more specific tier.
    rate_limit_default: str = "15/minute"

    #: Credential and enumeration surfaces: login, register, 2FA, token exchange.
    rate_limit_auth: str = "10/minute"

    #: The subset of auth endpoints that *send mail* or mint a one-time secret -
    #: password reset, magic link, OTP. Tighter than the rest of auth because abuse
    #: here spends someone else's inbox and the sending domain's reputation, and no
    #: legitimate user needs a fourth reset email inside a minute.
    rate_limit_auth_strict: str = "3/minute"

    #: Reads: list, get, search.
    #:
    #: Note this is the budget a *dashboard* spends: opening one screen fires a dozen
    #: requests, so the sustained rate here is roughly "screens per minute times ten".
    #: The bucket refills continuously, so a burst on page load is absorbed; sustained
    #: navigation faster than the refill rate is what gets throttled.
    rate_limit_read: str = "25/minute"

    #: Writes: POST/PATCH/PUT/DELETE outside auth. Each one costs a transaction and
    #: usually an audit row, so the budget is an order of magnitude below reads.
    rate_limit_write: str = "15/minute"

    #: Document uploads. Every one runs OCR inline, which is seconds of CPU - this is
    #: the most expensive thing an authenticated user can ask for.
    rate_limit_upload: str = "5/minute"

    #: Report exports (xlsx/pdf/csv). Each renders a full statement in memory.
    rate_limit_export: str = "5/minute"

    #: Per-IP ceiling applied *in addition to* the tier above, whoever is calling.
    #:
    #: The tiers key on the authenticated user where there is one, which is the fair
    #: unit for a shared office IP. This one bounds a single source regardless, so a
    #: stolen token cannot be fanned out and an unauthenticated flood cannot walk
    #: across cheap endpoints to stay under every individual tier.
    #:
    #: **It interacts with the tiers, and the interaction is easy to miss.** Both buckets
    #: must have room, so setting this *below* the largest tier makes that tier
    #: unreachable and this the only limit that actually binds - and because two users
    #: behind one office NAT share this bucket while having their own tier buckets, the
    #: symptom is intermittent 429s that correlate with how many colleagues are online
    #: rather than with anything the user did. :meth:`_warn_on_rate_limit_shape` says so
    #: at boot rather than leaving it to be discovered.
    rate_limit_ip: str = "20/minute"

    # ---- Email (Gmail API) --------------------------------------------------
    #: Base64 of a pickled ``Credentials`` for the Gmail account that sends mail.
    #:
    #: The only mail credential there is. There is no SMTP transport: Google
    #: refuses plain passwords, and app passwords depend on a setting any
    #: Workspace admin can turn off, so a refresh token scoped to ``gmail.send``
    #: is the supported path. Base64 because a pickle is raw bytes and has no
    #: representation in a `.env` value at all.
    #:
    #: Produce it with ``uv run python scripts/mint_gmail_token.py``; nothing else
    #: generates a value this accepts.
    #:
    #: Unset - the default - means mail is written to the log instead of sent,
    #: which is what lets the test suite and a fresh checkout run with no
    #: credentials. See :mod:`app.modules.notifications.email` for the format, the
    #: scope the token must carry, and why unpickling this value is only safe while
    #: it comes from configuration the operator controls.
    #: **The value belongs in `.env`, never here.** This file is tracked; `.env` is
    #: not. A refresh token and client secret committed to source are readable by
    #: anyone who can read the repository, and rewriting history does not un-leak
    #: them - only rotating the credential does.
    gmail_credentials_b64: str | None = None

    #: The mailbox to send from.
    #:
    #: Gmail will not send as an arbitrary address: this must be the authorised
    #: account itself or one of its verified "send mail as" aliases, otherwise the
    #: API rewrites the header or refuses outright. Left unset, the ``From`` header
    #: is omitted and Gmail fills in the authorised mailbox - correct, but without
    #: a display name.
    gmail_sender: str | None = None

    #: The display name on outgoing mail, used when :attr:`gmail_sender` is set.
    email_from_name: str = "Personal ERP"

    # ---- Frontend -----------------------------------------------------------
    frontend_url: str = "http://localhost:5173"

    # ---- Documents & OCR ----------------------------------------------------
    #: Hard ceiling on one upload. A 600 dpi colour scan of an A4 invoice is
    #: ~8 MB, so 15 MB accepts real documents and refuses everything else - the
    #: limit is enforced while streaming, so an oversized body is never buffered.
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=64 * 1024)

    # ---- Object storage: optional, off unless configured ---------------------
    #: S3-compatible object storage for document blobs. **Leave these blank.**
    #:
    #: Blank is the default and the supported configuration: documents are compressed and
    #: stored in PostgreSQL, in the same transaction as the row describing them, and covered
    #: by the same ``pg_dump``. See :mod:`app.modules.ocr.storage` for the reasoning and for
    #: the point at which it stops being the right answer.
    #:
    #: Filling all three in switches the backend to a bucket, for an install whose blobs have
    #: outgrown the database. Two out of three is a half-finished configuration and reads as
    #: "not configured" - see :attr:`document_storage`.
    #:
    #: Something has to be listening at that endpoint. In development that is the MinIO behind
    #: the ``objectstore`` compose profile (``make up-objectstore``), which a plain
    #: ``docker compose up`` deliberately does not start.
    #:
    #: The switch also makes document durability the operator's problem rather than the
    #: database's: the single consistent ``pg_dump`` stops covering them, and a restore can
    #: pair a ledger entry with a blob from a different moment.
    #:
    #: S3-compatible rather than tied to one vendor: the same code addresses MinIO on the
    #: operator's own box or real S3, which matters for a product whose premise is that you
    #: host it yourself.
    #:
    #: Objects are **private**. A bucket that allows anonymous reads would expose every
    #: invoice - a supplier's GSTIN, an amount, sometimes a bank account - to anyone who
    #: guessed a URL. Reads go through the credentialled client, never a public link.
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "personalerp-documents"

    #: TLS to the object store. False only for a store on the loopback interface; true for
    #: anything reachable over a network - the credentials and the documents both cross it.
    minio_secure: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def document_storage(self) -> Literal["object", "database"]:
        """Which backend holds document blobs. ``"database"`` unless a bucket is configured.

        Derived from whether object-storage credentials are present rather than set by a
        separate variable. A separate switch is a way for the credentials and the backend to
        disagree - configured but unused, or selected but unusable - and neither failure
        announces itself until someone uploads a file.

        All three of endpoint, access key and secret are required to switch. Two out of three
        is a half-finished configuration, and the safe reading of it is "not configured": the
        alternative is a deployment that boots happily and fails on its first upload.
        """
        configured = (
            self.minio_endpoint
            and self.minio_access_key
            and self.minio_secret_key.get_secret_value()
        )
        return "object" if configured else "database"

    ocr_enabled: bool = True

    #: Absolute path to the Tesseract binary. Blank means "find it on PATH".
    #: Needed because the Windows installer does not add itself to PATH, so the
    #: engine is unreachable on machines where it is plainly installed.
    tesseract_cmd: str = ""

    #: Tesseract language packs, ``+``-separated (e.g. ``eng+hin``). Each one must
    #: be installed alongside the binary; naming a missing pack makes recognition
    #: fail outright rather than degrade.
    ocr_languages: str = "eng"

    #: Wall-clock ceiling on one recognition pass. Tesseract on a large noisy
    #: image can run for minutes, and a request that never returns is worse than
    #: one that fails with an explanation.
    ocr_timeout_seconds: int = Field(default=30, ge=1, le=300)

    # -------------------------------------------------------------------------
    # Derived values
    # -------------------------------------------------------------------------
    @computed_field  # type: ignore[prop-decorator]
    @property
    def sqlalchemy_dsn(self) -> str:
        """asyncpg DSN. Explicit ``DATABASE_URL`` wins over the composed parts."""
        if self.database_url is not None:
            dsn = str(self.database_url)
            # Normalise whatever scheme was supplied to the async driver.
            for prefix in ("postgresql+psycopg://", "postgresql://", "postgres://"):
                if dsn.startswith(prefix):
                    return "postgresql+asyncpg://" + dsn.removeprefix(prefix)
            return dsn
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_name(self) -> str:
        """The database the app will actually connect to.

        Parsed from whichever source won, because "which database is this?" is otherwise
        two different questions depending on how the DSN was configured - and the answer
        is what :meth:`_enforce_test_safety` checks before anything is allowed to drop a
        table.
        """
        path = urlsplit(self.sqlalchemy_dsn).path.lstrip("/")
        return path.split("?", 1)[0] or self.postgres_db

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_dsn(self) -> str:
        if self.redis_url is not None:
            return str(self.redis_url)
        auth = f":{self.redis_password}@" if self.redis_password else ""
        return f"redis://{auth}{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def emails_enabled(self) -> bool:
        """When false, mail is logged instead of sent (the dev default)."""
        return bool(self.gmail_credentials_b64)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def docs_enabled(self) -> bool:
        """Whether the interactive docs and the OpenAPI schema are served at all.

        False in production, with no setting to override it. The schema is a complete
        map of every route, parameter, and error shape in the system - the single most
        useful document an attacker can be handed, and one nobody needs at runtime on a
        live deployment. Generate it in CI (``python -m app.openapi``-style scripts, or
        the staging deployment) where it costs nothing.

        :mod:`app.core.middleware` enforces this a second time at the HTTP layer, so a
        route re-added by hand cannot quietly reopen it.
        """
        return not self.environment.is_production

    @computed_field  # type: ignore[prop-decorator]
    @property
    def docs_url(self) -> str | None:
        """OpenAPI docs are never exposed in production."""
        return "/docs" if self.docs_enabled else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redoc_url(self) -> str | None:
        return "/redoc" if self.docs_enabled else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def openapi_url(self) -> str | None:
        return "/openapi.json" if self.docs_enabled else None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def gateway_enforced(self) -> bool:
        """Whether requests must arrive carrying :attr:`gateway_secret`.

        Derived from whether a secret exists rather than from a separate switch: a
        switch is a way for the two to disagree, and the failure mode of "enforcement
        on, no secret configured" is a service that rejects every request.
        """
        return self.gateway_secret is not None and bool(self.gateway_secret.get_secret_value())

    # -------------------------------------------------------------------------
    # Guardrails
    # -------------------------------------------------------------------------
    @model_validator(mode="after")
    def _validate_dsn_overrides(self) -> Self:
        """Reject a malformed ``DATABASE_URL`` or ``REDIS_URL`` at boot.

        These are plain strings so that blank can mean "not set" (see
        :func:`_blank_to_none`), which means the scheme check pydantic's ``PostgresDsn``
        used to perform has to happen here instead. A typo'd scheme is otherwise a
        connection error on the first query rather than a message at startup.
        """
        if self.database_url is not None and not self.database_url.startswith(
            ("postgresql://", "postgres://", "postgresql+asyncpg://", "postgresql+psycopg://")
        ):
            raise ValueError(
                "DATABASE_URL must start with postgresql://, postgres://, "
                "postgresql+asyncpg:// or postgresql+psycopg://"
            )
        if self.redis_url is not None and not self.redis_url.startswith(
            ("redis://", "rediss://", "unix://")
        ):
            raise ValueError("REDIS_URL must start with redis://, rediss:// or unix://")
        return self

    @property
    def rate_limit_tiers_eclipsed_by_ip(self) -> dict[str, str]:
        """Tier budgets that :attr:`rate_limit_ip` has made unreachable.

        Both buckets must have room for a request to pass, so a per-IP ceiling set below a
        tier means that tier never binds and the per-IP number is the only real limit.
        That is a legitimate choice - a deployment may want one hard per-source figure -
        but it produces a system whose behaviour does not match what a reader of the
        configuration would describe, and the symptom is intermittent 429s that track how
        many colleagues are online rather than anything the user did.

        A property rather than a validator that logs, because :mod:`app.core.logging`
        imports this module to configure itself - so nothing here can acquire a logger
        while the settings object is still being built. :mod:`app.main` reports it at
        startup instead, where logging is up and an operator will actually see it.

        Not a ``computed_field``: this is a diagnostic, and it has no business appearing in
        a serialised dump of the configuration.

        Compared as rates rather than counts so ``600/hour`` and ``10/minute`` are
        equivalent, which is the comparison that matters.
        """
        ip_rate = _rate_per_second(self.rate_limit_ip)
        if ip_rate is None:  # malformed; the limiter's own fallback reports it
            return {}

        tiers = {
            "RATE_LIMIT_DEFAULT": self.rate_limit_default,
            "RATE_LIMIT_AUTH": self.rate_limit_auth,
            "RATE_LIMIT_AUTH_STRICT": self.rate_limit_auth_strict,
            "RATE_LIMIT_READ": self.rate_limit_read,
            "RATE_LIMIT_WRITE": self.rate_limit_write,
            "RATE_LIMIT_UPLOAD": self.rate_limit_upload,
            "RATE_LIMIT_EXPORT": self.rate_limit_export,
        }
        return {
            name: spec
            for name, spec in tiers.items()
            if (rate := _rate_per_second(spec)) is not None and rate > ip_rate
        }

    @model_validator(mode="after")
    def _enforce_test_safety(self) -> Self:
        """Refuse to run the test suite against a database that is not a test database.

        This exists because of a real, live near-miss rather than a hypothetical.

        ``tests/conftest.py`` isolates itself by setting ``POSTGRES_DB=personalerp_test``
        and ``REDIS_DB=15``. Both are silently ignored when ``DATABASE_URL`` or
        ``REDIS_URL`` is set, because a full URL wins over the composed parts - and a
        developer whose ``.env`` carries a managed-database URL for a deployment has both.
        The suite then runs ``Base.metadata.drop_all`` and ``redis.flushdb()`` against
        whatever that URL points at.

        The failure is silent, total, and indistinguishable from a normal test run right
        up to the moment the tables are gone. So a name check at boot is worth the two
        lines: a database whose name does not end in ``_test`` is not a database this
        process may be pointed at while ``ENVIRONMENT=test``.
        """
        if self.environment is not Environment.TEST:
            return self

        if not self.database_name.endswith("_test"):
            raise ValueError(
                f"Refusing to run tests against database '{self.database_name}': the test "
                "suite drops every table, so the name must end in '_test'.\n"
                "  DATABASE_URL overrides POSTGRES_DB, so unset it (DATABASE_URL= in the "
                "environment) to fall back to the composed POSTGRES_* parts."
            )
        if self.redis_url is not None:
            raise ValueError(
                "Refusing to run tests with REDIS_URL set: it overrides REDIS_DB, which is "
                "how the suite isolates itself, and the suite calls FLUSHDB.\n"
                "  Unset it (REDIS_URL= in the environment) to fall back to REDIS_HOST/"
                "REDIS_DB."
            )
        return self

    @model_validator(mode="after")
    def _enforce_production_safety(self) -> Self:
        """Fail fast on insecure production configuration.

        Crashing at boot is strictly better than silently serving traffic with a
        placeholder signing key or wildcard CORS.
        """
        if not self.environment.is_production:
            return self

        problems: list[str] = []

        if len(self.secret_key) < 32 or "dev-only" in self.secret_key:
            problems.append("SECRET_KEY must be a real 32+ character secret")
        if self.debug:
            problems.append("DEBUG must be false")
        if "*" in self.cors_origins:
            problems.append("CORS_ORIGINS must list explicit origins, not '*'")
        if not self.encryption_key:
            problems.append("ENCRYPTION_KEY is required (2FA secrets are encrypted at rest)")
        # Only meaningful when the DSN is composed from the parts. With an
        # explicit DATABASE_URL the password lives in that URL and this field is
        # never read, so checking it would reject a perfectly good deployment.
        if self.database_url is None and self.postgres_password in (
            "personalerp",
            "postgres",
            "change-me-in-production",
        ):
            problems.append("POSTGRES_PASSWORD is still the default")
        if "*" in self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must list explicit hosts, not '*'")
        if not self.allowed_hosts:
            problems.append("ALLOWED_HOSTS must not be empty")
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must not be empty")

        # A credentialled session over plain HTTP is a session anyone on the path can
        # read. The refresh cookie is set `Secure` outside local development, so an
        # http:// origin here does not merely weaken the deployment - it produces a
        # frontend that cannot stay signed in, and a confusing bug report instead of a
        # clear boot failure.
        insecure_origins = [
            origin for origin in self.cors_origins if not origin.startswith("https://")
        ]
        if insecure_origins:
            problems.append(f"CORS_ORIGINS must all be https:// - got {insecure_origins}")
        if not self.frontend_url.startswith("https://"):
            problems.append("FRONTEND_URL must be https:// (it is emailed to users)")

        # The whole point of the exercise: in production the API is reachable only
        # through an edge that knows the secret. Refusing to boot without one is what
        # stops that guarantee from being lost to a forgotten environment variable,
        # since nothing about the running service would look wrong.
        if not self.gateway_enforced and not self.allow_direct_backend_access:
            problems.append(
                "GATEWAY_SECRET is required so only the edge proxy can reach the API. "
                'Generate one with `python -c "import secrets; '
                'print(secrets.token_urlsafe(48))"` and set the same value on the proxy. '
                "Set ALLOW_DIRECT_BACKEND_ACCESS=true only if this service *is* the "
                "public edge and you accept that anyone may call it directly."
            )
        if self.gateway_enforced and len(self.gateway_secret.get_secret_value()) < 32:  # type: ignore[union-attr]
            problems.append("GATEWAY_SECRET must be at least 32 characters")

        if not self.rate_limit_enabled:
            problems.append("RATE_LIMIT_ENABLED must be true")
        if not self.enforce_origin:
            problems.append("ENFORCE_ORIGIN must be true")

        if problems:
            joined = "\n  - ".join(problems)
            raise ValueError(f"Refusing to start in production:\n  - {joined}")
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide settings singleton.

    Cached so ``.env`` is read once. Tests override by calling
    ``get_settings.cache_clear()`` after patching the environment.
    """
    return Settings()


settings = get_settings()
