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

from pydantic import (
    BeforeValidator,
    Field,
    PostgresDsn,
    RedisDsn,
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

    # ---- PostgreSQL ---------------------------------------------------------
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "personalerp"
    postgres_password: str = "personalerp"
    postgres_db: str = "personalerp"
    database_url: PostgresDsn | None = None
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
    redis_url: RedisDsn | None = None

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
    rate_limit_enabled: bool = True
    rate_limit_default: str = "200/minute"
    rate_limit_auth: str = "10/minute"

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
    #: Where uploaded documents are stored **when the local backend is in use**.
    #:
    #: Never the database, under either backend. Scanned invoices are megabytes of
    #: opaque bytes: putting them in Postgres bloats every backup and every
    #: replication stream with data no query ever reads. A directory is also what
    #: makes `rsync`-ing the whole install to a new box a viable backup story for a
    #: self-hosted deployment.
    #:
    #: Ignored when object storage is configured - see :data:`document_storage`.
    upload_dir: Path = BACKEND_DIR / "var" / "uploads"

    #: Hard ceiling on one upload. A 600 dpi colour scan of an A4 invoice is
    #: ~8 MB, so 15 MB accepts real documents and refuses everything else - the
    #: limit is enforced while streaming, so an oversized body is never buffered.
    max_upload_bytes: int = Field(default=15 * 1024 * 1024, ge=64 * 1024)

    # ---- Object storage (MinIO / S3-compatible) -----------------------------
    #: Where document blobs go when object storage is configured.
    #:
    #: S3-compatible rather than tied to one vendor: the same code addresses MinIO in
    #: development, MinIO on the operator's own box, or real S3 - which matters for a
    #: product whose premise is that you host it yourself.
    #:
    #: Objects are **private**. A bucket that allows anonymous reads would expose every
    #: invoice - a supplier's GSTIN, an amount, sometimes a bank account - to anyone who
    #: guessed a URL. Reads go through the credentialled client, never a public link.
    minio_endpoint: str = ""
    minio_access_key: str = ""
    minio_secret_key: SecretStr = SecretStr("")
    minio_bucket: str = "personalerp-documents"

    #: TLS to the object store. False for a local MinIO on plain HTTP, true for anything
    #: reachable over a network - the credentials and the documents both cross it.
    minio_secure: bool = False

    @computed_field  # type: ignore[prop-decorator]
    @property
    def document_storage(self) -> Literal["object", "local"]:
        """Which backend holds document blobs.

        Derived from whether object storage is configured rather than set by a separate
        variable. A separate switch is a way for the credentials and the backend to
        disagree - configured but unused, or selected but unusable - and neither failure
        announces itself until someone uploads a file.
        """
        configured = (
            self.minio_endpoint
            and self.minio_access_key
            and self.minio_secret_key.get_secret_value()
        )
        return "object" if configured else "local"

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
    def docs_url(self) -> str | None:
        """OpenAPI docs are never exposed in production."""
        return None if self.environment.is_production else "/docs"

    # -------------------------------------------------------------------------
    # Guardrails
    # -------------------------------------------------------------------------
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
