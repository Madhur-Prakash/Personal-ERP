"""Model registry — imports every ORM class exactly once.

Two things depend on this module existing:

1. **Alembic autogenerate.** ``Base.metadata`` only knows about tables whose
   classes have been imported. Anything missing here is silently omitted from
   migrations — the single most common cause of "the migration is empty".
2. **Mapper configuration.** Relationships are declared with string targets
   (``"OrganizationMember"``) to avoid circular imports between modules. They
   resolve on first use, which fails unless every class is registered.

Adding a model? Import it here in the same commit.
"""

from __future__ import annotations

from app.db.base import Base
from app.modules.audit.models import AuditAction, AuditLog, AuditSeverity
from app.modules.auth.models import LoginMethod, SessionRevocationReason, UserSession
from app.modules.organizations.models import (
    Invitation,
    InvitationStatus,
    MemberStatus,
    Organization,
    OrganizationMember,
    OrganizationPlan,
)
from app.modules.rbac.models import Role
from app.modules.users.models import User

__all__ = [
    "AuditAction",
    "AuditLog",
    "AuditSeverity",
    "Base",
    "Invitation",
    "InvitationStatus",
    "LoginMethod",
    "MemberStatus",
    "Organization",
    "OrganizationMember",
    "OrganizationPlan",
    "Role",
    "SessionRevocationReason",
    "User",
    "UserSession",
]
