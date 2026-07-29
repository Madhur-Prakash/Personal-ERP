"""Shared Pydantic base classes for API contracts.

Naming: the API speaks ``snake_case`` end to end. Auto-aliasing to ``camelCase``
is the usual reflex for a TypeScript client, but it means every field exists
under two names — one in the database and Python, another in the JSON and the
frontend — and every debugging session pays for the translation. One name
everywhere is worth more than matching JavaScript convention, and the generated
TS types are handed to the frontend anyway.

Schemas are split by direction. A response schema that doubles as a request
schema is how ``is_superuser`` ends up mass-assignable.
"""

from __future__ import annotations

import datetime as dt
import uuid
from ipaddress import IPv4Address, IPv6Address
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StringConstraints,
)

# ---------------------------------------------------------------------------
# Reusable constrained field types
# ---------------------------------------------------------------------------
#: Trimmed non-empty short text.
ShortStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

#: A human name.
NameStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]

#: URL-safe identifier: lowercase alphanumerics and single hyphens.
SlugStr = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        to_lower=True,
        min_length=2,
        max_length=100,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]

#: Raw password. Never validated for strength here — that is
#: :mod:`app.modules.auth.password_policy`, which produces actionable messages
#: rather than a regex mismatch.
PasswordStr = Annotated[str, StringConstraints(min_length=1, max_length=128)]

#: Email. Normalised to lowercase so uniqueness is case-insensitive.
Email = Annotated[EmailStr, StringConstraints(strip_whitespace=True, to_lower=True)]


def _stringify_ip(value: object) -> object:
    """Coerce an ``ipaddress`` object to its string form.

    PostgreSQL ``INET`` columns come back from asyncpg as
    :class:`ipaddress.IPv4Address` / :class:`~ipaddress.IPv6Address`, not ``str``.
    ``INET`` is still the right column type — it validates on write, indexes
    properly, and supports subnet containment queries later — so the conversion
    belongs here at the serialisation boundary rather than by weakening the
    column to ``VARCHAR``.
    """
    if isinstance(value, IPv4Address | IPv6Address):
        return str(value)
    return value


#: An IP address read from an ``INET`` column, rendered as a plain string.
IpAddress = Annotated[str, BeforeValidator(_stringify_ip)]


class BaseSchema(BaseModel):
    """Base for request bodies and internal DTOs."""

    model_config = ConfigDict(
        # Reject unknown fields: a silently ignored typo'd field is a bug the
        # client never learns about.
        extra="forbid",
        str_strip_whitespace=True,
        validate_assignment=True,
        use_enum_values=True,
    )


class ResponseSchema(BaseModel):
    """Base for response bodies. Reads attributes off ORM objects."""

    model_config = ConfigDict(
        from_attributes=True,
        # Enum members serialise to their value, so JSON stays stable even if a
        # member is renamed in Python.
        use_enum_values=True,
    )


class TimestampedSchema(ResponseSchema):
    """Mixin for entities exposing their audit timestamps."""

    created_at: dt.datetime
    updated_at: dt.datetime


class IdentifiedSchema(ResponseSchema):
    id: uuid.UUID


# ---------------------------------------------------------------------------
# Generic envelopes
# ---------------------------------------------------------------------------
class MessageResponse(ResponseSchema):
    """A human-readable acknowledgement.

    Used by endpoints whose only meaningful output is "done" — and, importantly,
    by the ones that must stay deliberately vague (password reset, magic link) to
    avoid confirming whether an account exists.
    """

    message: str
    detail: str | None = None


class HealthStatus(ResponseSchema):
    status: str
    version: str
    environment: str
    checks: dict[str, Any] = Field(default_factory=dict)


def with_computed[SchemaT: BaseModel](schema: type[SchemaT], obj: Any, **computed: Any) -> SchemaT:
    """Validate an ORM object into ``schema``, then overlay computed fields.

    Response schemas routinely need a value the ORM row cannot supply — a
    ``member_count`` from a separate aggregate, an ``is_current`` flag that
    depends on the caller's session. ``model_validate`` accepts no such overlay
    (it has no ``update`` parameter), so the two steps are combined here rather
    than open-coded at a dozen call sites.

    The overlaid values bypass validation, which is safe *because they are
    computed server-side* — never taken from request data. Anything arriving from
    a client must go through a request schema instead.
    """
    return schema.model_validate(obj).model_copy(update=computed)
