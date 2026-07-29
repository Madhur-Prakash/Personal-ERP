"""The audit trail — an append-only record of who did what.

Deliberately **immutable**: no ``updated_at``, no soft delete, no update path in
the repository. An audit log that can be edited is not evidence. Stage 9 adds a
database-level trigger denying ``UPDATE``/``DELETE`` to the application role;
until then the constraint is enforced by the absence of any code that mutates it.

Actor and organization are both nullable so the table can record the full range
of real events: a user acting inside an org (both set), a platform-level signup
before any org exists (org null), and a scheduled job (actor null).
"""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
    text,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.dialects.postgresql import INET, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.modules.organizations.models import Organization
    from app.modules.users.models import User


class AuditAction(StrEnum):
    """Catalogued actions.

    A closed vocabulary rather than free-text strings, so the trail stays
    filterable and a typo cannot create a category nobody will ever search for.
    """

    # --- Authentication ---
    USER_REGISTERED = "user.registered"
    USER_LOGGED_IN = "user.logged_in"
    USER_LOGIN_FAILED = "user.login_failed"
    USER_LOGGED_OUT = "user.logged_out"
    USER_EMAIL_VERIFIED = "user.email_verified"
    USER_PASSWORD_CHANGED = "user.password_changed"
    USER_PASSWORD_RESET_REQUESTED = "user.password_reset_requested"
    USER_PASSWORD_RESET_COMPLETED = "user.password_reset_completed"
    USER_MAGIC_LINK_REQUESTED = "user.magic_link_requested"
    USER_OTP_REQUESTED = "user.otp_requested"
    USER_LOCKED_OUT = "user.locked_out"

    # --- Two-factor ---
    TWO_FACTOR_ENABLED = "two_factor.enabled"
    TWO_FACTOR_DISABLED = "two_factor.disabled"
    TWO_FACTOR_CHALLENGE_FAILED = "two_factor.challenge_failed"
    TWO_FACTOR_RECOVERY_CODE_USED = "two_factor.recovery_code_used"
    TWO_FACTOR_RECOVERY_CODES_REGENERATED = "two_factor.recovery_codes_regenerated"

    # --- Sessions ---
    SESSION_REVOKED = "session.revoked"
    SESSION_ALL_REVOKED = "session.all_revoked"
    SESSION_REUSE_DETECTED = "session.reuse_detected"

    # --- Profile ---
    USER_PROFILE_UPDATED = "user.profile_updated"

    # --- Organization ---
    ORG_CREATED = "organization.created"
    ORG_UPDATED = "organization.updated"
    ORG_DELETED = "organization.deleted"
    ORG_SWITCHED = "organization.switched"

    # --- Membership ---
    MEMBER_INVITED = "member.invited"
    MEMBER_INVITE_RESENT = "member.invite_resent"
    MEMBER_INVITE_REVOKED = "member.invite_revoked"
    MEMBER_JOINED = "member.joined"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_SUSPENDED = "member.suspended"
    MEMBER_REACTIVATED = "member.reactivated"
    MEMBER_REMOVED = "member.removed"

    # --- Roles ---
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"

    # --- Settings ---
    SETTINGS_UPDATED = "settings.updated"


class AuditSeverity(StrEnum):
    """Triage hint. ``WARNING``/``CRITICAL`` are what a security dashboard
    surfaces first (failed logins, lockouts, token reuse)."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AuditLog(Base, UUIDPrimaryKeyMixin):
    """One immutable event.

    Note the absence of :class:`~app.db.base.TimestampMixin`: an ``updated_at``
    column on an audit row would imply it can change.
    """

    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )

    # --- What ---
    action: Mapped[AuditAction] = mapped_column(
        SAEnum(AuditAction, native_enum=False, length=60, validate_strings=True),
        nullable=False,
        index=True,
    )
    severity: Mapped[AuditSeverity] = mapped_column(
        SAEnum(AuditSeverity, native_enum=False, length=20, validate_strings=True),
        nullable=False,
        default=AuditSeverity.INFO,
    )
    #: Short human-readable summary, e.g. "Invited priya@acme.com as Accountant".
    summary: Mapped[str | None] = mapped_column(String(500))

    # --- Who ---
    #: Null for system/scheduled actions. ``SET NULL`` on user deletion so the
    #: event survives the actor — the whole point of an audit trail.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("app_user.id", ondelete="SET NULL"), index=True
    )
    #: Denormalised copy, retained after the user row is gone.
    actor_email: Mapped[str | None] = mapped_column(String(320))
    actor_label: Mapped[str | None] = mapped_column(String(200))

    # --- Where ---
    #: Null for platform-level events that precede any organization.
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("organization.id", ondelete="CASCADE"), index=True
    )

    # --- On what ---
    resource_type: Mapped[str | None] = mapped_column(String(60), index=True)
    #: Plain string, not a UUID column: some resources are keyed by slug or
    #: composite identifier, and this field must never constrain what can be
    #: audited.
    resource_id: Mapped[str | None] = mapped_column(String(100), index=True)

    # --- Context ---
    ip_address: Mapped[str | None] = mapped_column(INET)
    user_agent: Mapped[str | None] = mapped_column(String(500))
    #: Correlates the event with the request in the logifyx log stream.
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)

    #: Field-level diff, ``{"field": {"before": ..., "after": ...}}``.
    #: Written by the service layer, which is responsible for excluding secrets.
    changes: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    #: Anything else worth keeping that is not a field diff.
    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )

    # --- Relationships (read-only; audit rows never cascade writes) ---
    actor: Mapped[User | None] = relationship(lazy="raise")
    organization: Mapped[Organization | None] = relationship(lazy="raise")

    __table_args__ = (
        # The audit viewer's default query: one org, newest first.
        Index("ix_audit_log_org_created", "organization_id", "created_at"),
        # "What did this person do?"
        Index("ix_audit_log_actor_created", "actor_user_id", "created_at"),
        # "What happened to this record?"
        Index("ix_audit_log_resource", "resource_type", "resource_id", "created_at"),
    )
