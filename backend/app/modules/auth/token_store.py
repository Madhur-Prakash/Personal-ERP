"""Redis-backed store for short-lived auth artefacts.

Everything here is ephemeral and reconstructible: one-time tokens, OTP codes,
failed-login counters, 2FA challenges, revocation markers. Redis is the right
home because each one carries a natural TTL, and expiry-as-a-feature means no
cleanup job and no table of dead rows.

Only token *digests* are used as keys, never the tokens themselves. A dump of
Redis therefore leaks nothing replayable — the same reasoning as hashing refresh
tokens in PostgreSQL.

Consumption is atomic (``GETDEL``). A one-time token that could be read and then
deleted in two steps is a race: two concurrent requests both read it, both
succeed, and "one-time" becomes "twice".
"""

from __future__ import annotations

import datetime as dt
import json
import uuid
from typing import Any, Final

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import RedisKey, get_redis
from app.core.security import generate_otp, generate_token, hash_token

log = get_logger(__name__)

#: Cap on OTP verification attempts before the code is destroyed. Without it, a
#: 6-digit code is brute-forceable in ~500k requests.
MAX_OTP_ATTEMPTS: Final = 5


class OneTimeTokenStore:
    """Issue and atomically consume single-use tokens."""

    def __init__(self, key_builder: Any, ttl: dt.timedelta) -> None:
        self._key = key_builder
        self._ttl = ttl

    async def issue(self, payload: dict[str, Any]) -> str:
        """Mint a token and store its payload under the token's digest.

        Returns the *plaintext* token — the only time it exists in the clear.
        """
        token = generate_token()
        await get_redis().set(
            self._key(hash_token(token)),
            json.dumps(payload),
            ex=int(self._ttl.total_seconds()),
        )
        return token

    async def consume(self, token: str) -> dict[str, Any] | None:
        """Atomically fetch and delete. ``None`` if unknown, expired, or spent."""
        raw = await get_redis().getdel(self._key(hash_token(token)))
        if raw is None:
            return None
        try:
            payload: dict[str, Any] = json.loads(raw)
            return payload
        except json.JSONDecodeError:
            log.error("corrupt token payload in redis")
            return None

    async def peek(self, token: str) -> dict[str, Any] | None:
        """Read without consuming. For pre-flight UI checks ("is this link still
        valid?") where consuming would break the subsequent real submission."""
        raw = await get_redis().get(self._key(hash_token(token)))
        if raw is None:
            return None
        try:
            payload: dict[str, Any] = json.loads(raw)
            return payload
        except json.JSONDecodeError:
            return None

    async def revoke(self, token: str) -> bool:
        return bool(await get_redis().delete(self._key(hash_token(token))))


def email_verification_store() -> OneTimeTokenStore:
    return OneTimeTokenStore(
        RedisKey.email_verification,
        dt.timedelta(hours=settings.email_verification_ttl_hours),
    )


def password_reset_store() -> OneTimeTokenStore:
    return OneTimeTokenStore(
        RedisKey.password_reset,
        dt.timedelta(minutes=settings.password_reset_ttl_minutes),
    )


def magic_link_store() -> OneTimeTokenStore:
    return OneTimeTokenStore(
        RedisKey.magic_link,
        dt.timedelta(minutes=settings.magic_link_ttl_minutes),
    )


# =============================================================================
# OTP codes
# =============================================================================
class OtpStore:
    """Email OTP codes, keyed by address rather than by an opaque token.

    A user types a code without any accompanying identifier, so the address is
    the only available lookup key. Requesting a new code overwrites the old one,
    which keeps "the code from my most recent email" true — the behaviour users
    expect.
    """

    async def issue(self, email: str) -> str:
        code = generate_otp()
        redis = get_redis()
        ttl = int(dt.timedelta(minutes=settings.otp_ttl_minutes).total_seconds())

        pipe = redis.pipeline()
        # Store the digest, not the code: an OTP is low-entropy enough that a
        # Redis dump would otherwise hand over live codes.
        pipe.set(RedisKey.otp(email), hash_token(code), ex=ttl)
        pipe.delete(RedisKey.otp_attempts(email))  # fresh code, fresh budget
        await pipe.execute()
        return code

    async def verify(self, email: str, code: str) -> bool:
        """Verify a code, enforcing an attempt budget.

        ``MAX_OTP_ATTEMPTS`` wrong guesses are permitted; the failure that
        exhausts the budget destroys the code immediately. Deferring destruction
        to the *next* request would leave a spent code sitting in Redis, still
        redeemable, whenever an attacker simply stops guessing.

        A correct code is always accepted while budget remains, so a user who
        mistyped four times can still succeed on the fifth.
        """
        redis = get_redis()

        attempts = await redis.incr(RedisKey.otp_attempts(email))
        if attempts == 1:
            await redis.expire(
                RedisKey.otp_attempts(email),
                int(dt.timedelta(minutes=settings.otp_ttl_minutes).total_seconds()),
            )

        if attempts > MAX_OTP_ATTEMPTS:
            # Budget was already spent by an earlier request.
            await redis.delete(RedisKey.otp(email))
            return False

        stored = await redis.get(RedisKey.otp(email))
        if stored is None or stored != hash_token(code.strip()):
            if attempts >= MAX_OTP_ATTEMPTS:
                await redis.delete(RedisKey.otp(email))
                log.warning(
                    "otp attempt budget exhausted — code destroyed",
                    extra={"email": email, "attempts": attempts},
                )
            return False

        pipe = redis.pipeline()
        pipe.delete(RedisKey.otp(email))
        pipe.delete(RedisKey.otp_attempts(email))
        await pipe.execute()
        return True


# =============================================================================
# Brute-force protection
# =============================================================================
class LoginThrottle:
    """Per-identifier failed-login counter with a lockout.

    Keyed on the email rather than the IP: an attacker rotates IPs trivially, and
    IP-based locking punishes everyone behind one NAT. Rate limiting by IP is a
    separate layer, handled in middleware.
    """

    async def is_locked(self, identifier: str) -> int:
        """Remaining lockout in seconds, or ``0`` if not locked."""
        ttl = await get_redis().ttl(RedisKey.login_lockout(identifier))
        return max(0, ttl)

    async def record_failure(self, identifier: str) -> tuple[int, int]:
        """Count a failure, locking out at the threshold.

        Returns ``(attempts, lockout_seconds)`` where ``lockout_seconds`` is
        non-zero only on the attempt that triggers the lock.
        """
        redis = get_redis()
        window = int(dt.timedelta(minutes=settings.login_lockout_minutes).total_seconds())

        attempts = await redis.incr(RedisKey.login_attempts(identifier))
        if attempts == 1:
            await redis.expire(RedisKey.login_attempts(identifier), window)

        if attempts >= settings.max_login_attempts:
            await redis.set(RedisKey.login_lockout(identifier), "1", ex=window)
            await redis.delete(RedisKey.login_attempts(identifier))
            log.warning(
                "account locked after repeated failures",
                extra={"identifier": identifier, "attempts": attempts},
            )
            return attempts, window

        return attempts, 0

    async def reset(self, identifier: str) -> None:
        """Clear counters after a successful login."""
        pipe = get_redis().pipeline()
        pipe.delete(RedisKey.login_attempts(identifier))
        pipe.delete(RedisKey.login_lockout(identifier))
        await pipe.execute()

    async def remaining_attempts(self, identifier: str) -> int:
        used = await get_redis().get(RedisKey.login_attempts(identifier))
        return max(0, settings.max_login_attempts - int(used or 0))


# =============================================================================
# Two-factor challenges
# =============================================================================
class TwoFactorChallengeStore:
    """Holds the interstitial state between "password OK" and "code OK".

    The challenge id is what the client echoes back with the TOTP code. It exists
    so the second step needs no re-transmission of the password, and so the
    partial authentication expires on its own if abandoned.
    """

    #: Short by design: this is an interstitial, not a session.
    TTL = dt.timedelta(minutes=5)

    async def create(self, user_id: uuid.UUID, context: dict[str, Any] | None = None) -> str:
        challenge_id = str(uuid.uuid4())
        await get_redis().set(
            RedisKey.totp_challenge(challenge_id),
            json.dumps({"user_id": str(user_id), **(context or {})}),
            ex=int(self.TTL.total_seconds()),
        )
        return challenge_id

    async def resolve(self, challenge_id: str) -> dict[str, Any] | None:
        """Read without consuming, so a mistyped code can be retried."""
        raw = await get_redis().get(RedisKey.totp_challenge(challenge_id))
        if raw is None:
            return None
        try:
            payload: dict[str, Any] = json.loads(raw)
            return payload
        except json.JSONDecodeError:
            return None

    async def discard(self, challenge_id: str) -> None:
        await get_redis().delete(RedisKey.totp_challenge(challenge_id))

    async def burn_code(self, user_id: uuid.UUID, code: str, ttl_seconds: int) -> bool:
        """Mark a TOTP code spent. ``False`` means it was already used.

        ``SET NX`` makes claim-and-check a single atomic operation; checking then
        setting would let two concurrent requests both win.
        """
        claimed = await get_redis().set(
            RedisKey.totp_replay(str(user_id), hash_token(code)),
            "1",
            ex=ttl_seconds,
            nx=True,
        )
        return bool(claimed)


# =============================================================================
# Access-token invalidation
# =============================================================================
class TokenEpochStore:
    """Per-user counter that invalidates outstanding access tokens.

    Access tokens are stateless JWTs, so they cannot be individually revoked
    without a database lookup per request — which would defeat the point. Instead
    each token carries the user's epoch, and bumping the epoch makes every
    already-issued token stale immediately.

    Used for: password change, "sign out everywhere", role changes, and account
    deactivation.
    """

    #: Outlives the longest possible access token; nothing older can still exist.
    TTL = dt.timedelta(days=1)

    async def current(self, user_id: uuid.UUID | str) -> int:
        raw = await get_redis().get(RedisKey.user_token_epoch(str(user_id)))
        return int(raw or 0)

    async def bump(self, user_id: uuid.UUID | str) -> int:
        redis = get_redis()
        key = RedisKey.user_token_epoch(str(user_id))
        epoch = await redis.incr(key)
        await redis.expire(key, int(self.TTL.total_seconds()))
        log.info("token epoch bumped", extra={"user_id": str(user_id), "epoch": epoch})
        return int(epoch)


class SessionRevocationStore:
    """Marks individual sessions as revoked for the access-token layer.

    The epoch counter is the right tool for revoking *all* of a user's tokens,
    but too blunt for "sign out this one device" — bumping the epoch would log
    the user out everywhere. This store handles the single-session case.

    Entries only need to outlive the longest-lived access token: once the JWT
    expires it is rejected on its own, and the marker becomes redundant. The
    session row in PostgreSQL remains the durable record.
    """

    def _ttl_seconds(self) -> int:
        # One extra minute of slack for clock skew between app and Redis hosts.
        return (settings.access_token_ttl_minutes + 1) * 60

    async def revoke(self, session_id: uuid.UUID | str) -> None:
        await get_redis().set(
            RedisKey.revoked_session(str(session_id)), "1", ex=self._ttl_seconds()
        )

    async def revoke_many(self, session_ids: list[uuid.UUID | str]) -> None:
        if not session_ids:
            return
        pipe = get_redis().pipeline()
        for session_id in session_ids:
            pipe.set(RedisKey.revoked_session(str(session_id)), "1", ex=self._ttl_seconds())
        await pipe.execute()

    async def is_revoked(self, session_id: uuid.UUID | str) -> bool:
        return bool(await get_redis().exists(RedisKey.revoked_session(str(session_id))))


# Module-level singletons — all are stateless wrappers over the shared pool.
otp_store = OtpStore()
revoked_sessions = SessionRevocationStore()
login_throttle = LoginThrottle()
two_factor_challenges = TwoFactorChallengeStore()
token_epochs = TokenEpochStore()
