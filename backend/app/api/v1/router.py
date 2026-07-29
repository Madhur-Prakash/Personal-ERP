"""v1 API router aggregation.

Every module's router is mounted here, and nowhere else. One file answers "what
does this API expose?", and versioning is a matter of adding a ``v2`` package
rather than editing routes in place — existing clients keep working while a new
contract is introduced alongside.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.modules.audit.router import router as audit_router
from app.modules.auth.router import router as auth_router
from app.modules.organizations.router import (
    invitations_router,
)
from app.modules.organizations.router import (
    router as organizations_router,
)
from app.modules.rbac.router import router as roles_router
from app.modules.users.router import router as users_router

api_router = APIRouter()

# Ordered as a reader would explore the API: authenticate, then act.
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(organizations_router)
api_router.include_router(invitations_router)
api_router.include_router(roles_router)
api_router.include_router(audit_router)

__all__ = ["api_router"]
