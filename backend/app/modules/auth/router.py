"""Authentication endpoints.

Routers stay thin: parse, delegate to the service, shape the response. No
business logic here, so the same rules apply identically to any future transport.

The one thing this layer genuinely owns is **cookie handling for the refresh
token**, because that is an HTTP concern the service must not know about.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Cookie, Request, Response, status

from app.core.config import settings
from app.core.exceptions import InvalidTokenError
from app.core.logging import get_logger
from app.core.schemas import MessageResponse
from app.modules.auth.dependencies import (
    REFRESH_COOKIE_NAME,
    ActiveOrganizationId,
    AuthServiceDep,
    CurrentSession,
    CurrentUser,
    RequestCtx,
)
from app.modules.auth.password_policy import describe_policy
from app.modules.auth.schemas import (
    AuthenticatedUser,
    ChangePasswordRequest,
    ForgotPasswordRequest,
    LoginRequest,
    LogoutRequest,
    MagicLinkRequest,
    MagicLinkVerifyRequest,
    OtpRequestBody,
    OtpVerifyRequest,
    PasswordPolicyResponse,
    RecoveryCodesResponse,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    ResendVerificationRequest,
    ResetPasswordRequest,
    SessionRead,
    TokenResponse,
    TwoFactorChallengeResponse,
    TwoFactorDisableRequest,
    TwoFactorEnableRequest,
    TwoFactorEnableResponse,
    TwoFactorLoginRequest,
    TwoFactorSetupResponse,
    VerifyEmailRequest,
)
from app.modules.auth.service import AuthResult, TwoFactorPending

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["Authentication"])


# =============================================================================
# Refresh cookie
# =============================================================================
def _set_refresh_cookie(response: Response, result: AuthResult) -> None:
    """Attach the refresh token as a hardened cookie.

    Each flag earns its place:

    * ``httponly`` - unreachable from JavaScript, so XSS cannot exfiltrate a
      long-lived credential. This is the single most important one.
    * ``secure`` - HTTPS only. Relaxed in local development, where there is no
      TLS and the cookie would otherwise never be set.
    * ``samesite="strict"`` - the browser withholds the cookie on cross-site
      requests, which is what makes CSRF against the refresh endpoint infeasible.
    * ``path`` - scoped to the auth routes, so it is not attached to every API
      call that has no use for it.
    """
    # Measured from now, not from the access token's expiry - the two have
    # entirely different lifetimes.
    max_age = int((result.refresh_expires_at - dt.datetime.now(dt.UTC)).total_seconds())

    response.set_cookie(
        key=REFRESH_COOKIE_NAME,
        value=result.refresh_token,
        max_age=max(max_age, 0),
        httponly=True,
        secure=not settings.environment.is_local,
        samesite="strict",
        path=f"{settings.api_v1_prefix}/auth",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key=REFRESH_COOKIE_NAME,
        path=f"{settings.api_v1_prefix}/auth",
        httponly=True,
        secure=not settings.environment.is_local,
        samesite="strict",
    )


# =============================================================================
# Registration & verification
# =============================================================================
@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create an account",
)
async def register(
    data: RegisterRequest,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> RegisterResponse:
    user, organization_id = await service.register(data, ctx)
    return RegisterResponse(
        user_id=user.id,
        email=user.email,
        email_verification_required=not user.is_email_verified,
        organization_id=organization_id,
        message=(
            "Account created. Check your email to verify your address."
            if not user.is_email_verified
            else "Account created."
        ),
    )


@router.post("/verify-email", response_model=MessageResponse, summary="Verify an email address")
async def verify_email(
    data: VerifyEmailRequest,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> MessageResponse:
    await service.verify_email(data.token, ctx)
    return MessageResponse(message="Email verified. You can now sign in.")


@router.post(
    "/resend-verification",
    response_model=MessageResponse,
    summary="Resend the verification email",
)
async def resend_verification(
    data: ResendVerificationRequest,
    service: AuthServiceDep,
) -> MessageResponse:
    return MessageResponse(message=await service.resend_verification(data.email))


# =============================================================================
# Sign in
# =============================================================================
@router.post(
    "/login",
    response_model=TokenResponse | TwoFactorChallengeResponse,
    summary="Sign in with email and password",
    responses={
        401: {"description": "Invalid credentials, or a 2FA code is required"},
        403: {"description": "Email not verified, or account disabled"},
        423: {"description": "Account temporarily locked after repeated failures"},
    },
)
async def login(
    data: LoginRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TokenResponse | TwoFactorChallengeResponse:
    """Authenticate with a password.

    Returns either a token pair or - when 2FA is enabled - a challenge to be
    completed at ``/auth/login/2fa``.
    """
    result = await service.login(data.email, data.password, ctx, remember_me=data.remember_me)

    if isinstance(result, TwoFactorPending):
        return TwoFactorChallengeResponse(challenge_id=result.challenge_id)

    _set_refresh_cookie(response, result)
    return result.tokens


@router.post(
    "/login/2fa",
    response_model=TokenResponse,
    summary="Complete sign-in with a two-factor code",
)
async def login_two_factor(
    data: TwoFactorLoginRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TokenResponse:
    """Accepts either a TOTP code or an unused recovery code."""
    result = await service.complete_two_factor(data.challenge_id, data.code, ctx)
    _set_refresh_cookie(response, result)
    return result.tokens


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Exchange a refresh token for a new access token",
)
async def refresh(
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
    refresh_cookie: Annotated[str | None, Cookie(alias=REFRESH_COOKIE_NAME)] = None,
    body: Annotated[RefreshRequest | None, Body()] = None,
) -> TokenResponse:
    """Rotate the refresh token and mint a fresh access token.

    Prefers the cookie; falls back to the request body for non-browser clients
    that have no cookie jar.
    """
    token = refresh_cookie or (body.refresh_token if body else None)
    if not token:
        raise InvalidTokenError("No refresh token supplied")

    result = await service.refresh(token, ctx)
    _set_refresh_cookie(response, result)
    return result.tokens


@router.post("/logout", response_model=MessageResponse, summary="Sign out")
async def logout(
    response: Response,
    user: CurrentUser,
    session: CurrentSession,
    service: AuthServiceDep,
    ctx: RequestCtx,
    data: Annotated[LogoutRequest, Body()] = LogoutRequest(),
) -> MessageResponse:
    count = await service.logout(user, session.id, ctx, all_devices=data.all_devices)
    _clear_refresh_cookie(response)

    return MessageResponse(
        message=f"Signed out of {count} devices." if data.all_devices else "Signed out."
    )


# =============================================================================
# Passwordless
# =============================================================================
@router.post(
    "/magic-link",
    response_model=MessageResponse,
    summary="Request a passwordless sign-in link",
)
async def request_magic_link(
    data: MagicLinkRequest,
    service: AuthServiceDep,
) -> MessageResponse:
    message = await service.request_magic_link(data.email, data.redirect_path)
    return MessageResponse(message=message)


@router.post(
    "/magic-link/verify",
    response_model=TokenResponse,
    summary="Sign in with a magic link token",
)
async def verify_magic_link(
    data: MagicLinkVerifyRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TokenResponse:
    result = await service.verify_magic_link(data.token, ctx)
    _set_refresh_cookie(response, result)
    return result.tokens


@router.post("/otp", response_model=MessageResponse, summary="Request an email sign-in code")
async def request_otp(data: OtpRequestBody, service: AuthServiceDep) -> MessageResponse:
    return MessageResponse(message=await service.request_otp(data.email))


@router.post("/otp/verify", response_model=TokenResponse, summary="Sign in with an email code")
async def verify_otp(
    data: OtpVerifyRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TokenResponse:
    result = await service.verify_otp(data.email, data.code, ctx)
    _set_refresh_cookie(response, result)
    return result.tokens


# =============================================================================
# Password management
# =============================================================================
@router.get(
    "/password-policy",
    response_model=PasswordPolicyResponse,
    summary="The enforced password policy",
)
async def password_policy() -> PasswordPolicyResponse:
    """Served so the client's hints cannot drift from server enforcement."""
    return PasswordPolicyResponse.model_validate(describe_policy())


@router.post(
    "/forgot-password",
    response_model=MessageResponse,
    summary="Request a password reset code by email",
)
async def forgot_password(
    data: ForgotPasswordRequest,
    service: AuthServiceDep,
) -> MessageResponse:
    """Always reports the same message, whether or not the account exists."""
    return MessageResponse(message=await service.forgot_password(data.email))


@router.post(
    "/reset-password",
    response_model=MessageResponse,
    summary="Set a new password using an emailed reset code",
)
async def reset_password(
    data: ResetPasswordRequest,
    response: Response,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> MessageResponse:
    await service.reset_password(data.email, data.code, data.new_password, ctx)
    # Every session was revoked, so any refresh cookie in this browser is dead.
    _clear_refresh_cookie(response)
    return MessageResponse(
        message="Password updated. Sign in with your new password.",
        detail="All other sessions were signed out.",
    )


@router.post("/change-password", response_model=MessageResponse, summary="Change your password")
async def change_password(
    data: ChangePasswordRequest,
    response: Response,
    user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> MessageResponse:
    await service.change_password(user, data.current_password, data.new_password, ctx)
    _clear_refresh_cookie(response)
    return MessageResponse(
        message="Password changed.",
        detail="All sessions were signed out. Please sign in again.",
    )


# =============================================================================
# Two-factor authentication
# =============================================================================
@router.post(
    "/2fa/setup",
    response_model=TwoFactorSetupResponse,
    summary="Begin two-factor enrolment",
)
async def begin_two_factor_setup(
    user: CurrentUser,
    service: AuthServiceDep,
) -> TwoFactorSetupResponse:
    """Generate a secret and QR code. 2FA is not active until confirmed."""
    secret, provisioning_uri, qr_code = await service.begin_two_factor_setup(user)
    return TwoFactorSetupResponse(secret=secret, provisioning_uri=provisioning_uri, qr_code=qr_code)


@router.post(
    "/2fa/enable",
    response_model=TwoFactorEnableResponse,
    summary="Confirm two-factor enrolment",
)
async def enable_two_factor(
    data: TwoFactorEnableRequest,
    user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TwoFactorEnableResponse:
    """Recovery codes are returned once and never again."""
    codes = await service.enable_two_factor(user, data.code, ctx)
    return TwoFactorEnableResponse(enabled=True, recovery_codes=codes)


@router.post(
    "/2fa/disable",
    response_model=MessageResponse,
    summary="Turn off two-factor authentication",
)
async def disable_two_factor(
    data: TwoFactorDisableRequest,
    user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> MessageResponse:
    await service.disable_two_factor(user, data.password, ctx)
    return MessageResponse(message="Two-factor authentication disabled.")


@router.post(
    "/2fa/recovery-codes",
    response_model=RecoveryCodesResponse,
    summary="Regenerate recovery codes",
)
async def regenerate_recovery_codes(
    data: TwoFactorDisableRequest,
    user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> RecoveryCodesResponse:
    """Invalidates all previously issued codes."""
    codes = await service.regenerate_recovery_codes(user, data.password, ctx)
    return RecoveryCodesResponse(recovery_codes=codes)


# =============================================================================
# Session & identity
# =============================================================================
@router.get("/me", response_model=AuthenticatedUser, summary="The current user")
async def me(
    request: Request,
    user: CurrentUser,
    service: AuthServiceDep,
) -> AuthenticatedUser:
    """Everything the client needs to render the app shell."""
    claims = getattr(request.state, "claims", {})
    organization_id = claims.get("org")
    return await service.build_authenticated_user(
        user, uuid.UUID(organization_id) if organization_id else None
    )


@router.get("/sessions", response_model=list[SessionRead], summary="List active sessions")
async def list_sessions(
    user: CurrentUser,
    session: CurrentSession,
    service: AuthServiceDep,
) -> list[SessionRead]:
    """Device history. The current session is flagged ``is_current``."""
    return await service.list_sessions(user, session.id)


@router.delete(
    "/sessions/{session_id}",
    response_model=MessageResponse,
    summary="Revoke a session",
)
async def revoke_session(
    session_id: uuid.UUID,
    user: CurrentUser,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> MessageResponse:
    await service.revoke_session(user, session_id, ctx)
    return MessageResponse(message="Session revoked.")


@router.post(
    "/switch-organization/{organization_id}",
    response_model=TokenResponse,
    summary="Switch the active organization",
)
async def switch_organization(
    organization_id: uuid.UUID,
    user: CurrentUser,
    session: CurrentSession,
    service: AuthServiceDep,
    ctx: RequestCtx,
) -> TokenResponse:
    """Re-mints the access token, since permissions are organization-specific."""
    return await service.switch_organization(user, session, organization_id, ctx)


@router.get(
    "/permissions",
    response_model=list[str],
    summary="The caller's permissions in the active organization",
)
async def my_permissions(
    user: CurrentUser,
    organization_id: ActiveOrganizationId,
    service: AuthServiceDep,
) -> list[str]:
    """Resolved live from the database rather than read off the token.

    Deliberate: this is the endpoint a client polls after a role change, so it
    must reflect current state, not what was true when the token was issued.
    """
    return sorted(await service.effective_permissions(user, organization_id))
