"""Transactional email over SMTP.

Two behaviours, chosen by whether ``SMTP_HOST`` is configured:

* **Configured** — sends via :mod:`aiosmtplib`.
* **Not configured** (the local default) — renders the message and writes it to
  the logifyx log, including the verification/reset link. Development works with
  no mail server at all, and nobody has to dig a token out of the database to
  test a flow. ``docker compose up`` also runs Mailpit on
  http://localhost:8025 for those who want a real inbox.

Sending never raises into a request. A signup that succeeded must not report
failure because the mail relay was briefly unreachable — the user can always
request another verification email, but a rolled-back registration is
unrecoverable. Failures are logged at error level for alerting.

Templates are inline Jinja2 rather than files: Stage 1 has six emails, and a
template directory plus loader configuration is machinery for a problem that does
not exist yet. Extracting them is mechanical when the count grows.
"""

from __future__ import annotations

from email.message import EmailMessage
from typing import Any, Final

import aiosmtplib
from jinja2 import Environment, select_autoescape

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

#: ``autoescape`` is non-negotiable: user-supplied names go into these bodies,
#: and an unescaped one is HTML injection into whatever the recipient's client
#: renders.
_jinja = Environment(autoescape=select_autoescape(["html", "xml"]), enable_async=False)

_BASE_STYLES: Final = """
  body{margin:0;padding:0;background:#f6f7f9;font-family:-apple-system,BlinkMacSystemFont,
    'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;color:#18181b;}
  .wrap{max-width:520px;margin:0 auto;padding:40px 24px;}
  .card{background:#fff;border:1px solid #e4e4e7;border-radius:14px;padding:32px;}
  .brand{font-size:15px;font-weight:600;letter-spacing:-.01em;margin:0 0 28px;color:#18181b;}
  .brand span{color:#6366f1;}
  h1{font-size:20px;font-weight:600;letter-spacing:-.02em;margin:0 0 12px;}
  p{font-size:14px;line-height:1.6;color:#52525b;margin:0 0 16px;}
  .btn{display:inline-block;background:#18181b;color:#fff!important;text-decoration:none;
    font-size:14px;font-weight:500;padding:11px 20px;border-radius:8px;margin:8px 0 20px;}
  .code{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:30px;font-weight:600;
    letter-spacing:.18em;background:#f4f4f5;border-radius:10px;padding:18px;text-align:center;
    margin:20px 0;color:#18181b;}
  .fallback{font-size:12px;color:#71717a;word-break:break-all;}
  .foot{font-size:12px;color:#a1a1aa;margin:24px 0 0;padding-top:20px;border-top:1px solid #f4f4f5;}
"""

_LAYOUT: Final = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{ subject }}</title><style>{{ styles }}</style></head>
<body><div class="wrap"><div class="card">
  <p class="brand">Personal <span>ERP</span></p>
  {{ body }}
  <p class="foot">{{ footer|default("You are receiving this because someone used this
    address to sign in to Personal ERP. If that was not you, you can ignore this email.") }}</p>
</div></div></body></html>
"""


def _render(body_template: str, *, subject: str, footer: str | None = None, **context: Any) -> str:
    body = _jinja.from_string(body_template).render(**context)
    return _jinja.from_string(_LAYOUT).render(
        subject=subject, styles=_BASE_STYLES, body=body, footer=footer
    )


async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    category: str = "transactional",
) -> bool:
    """Send one message. Returns success; never raises.

    A plaintext alternative always accompanies the HTML — some clients refuse to
    render HTML, and multipart messages score better with spam filters.
    """
    if not settings.emails_enabled:
        # Development: the link in `text` is the whole point of this branch.
        log.info(
            "email suppressed (SMTP not configured) — body follows",
            extra={"to": to, "subject": subject, "category": category, "body": text},
        )
        return True

    message = EmailMessage()
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    try:
        await aiosmtplib.send(
            message,
            hostname=settings.smtp_host,
            port=settings.smtp_port,
            username=settings.smtp_user or None,
            password=settings.smtp_password or None,
            start_tls=settings.smtp_tls,
            timeout=15,
        )
        log.info("email sent", extra={"to": to, "subject": subject, "category": category})
        return True
    except Exception as exc:
        # Swallowed on purpose — see the module docstring.
        log.error(
            "email delivery failed",
            extra={"to": to, "subject": subject, "category": category, "error": str(exc)},
            exc_info=True,
        )
        return False


def _frontend_url(path: str, **params: str) -> str:
    from urllib.parse import urlencode

    base = settings.frontend_url.rstrip("/")
    query = f"?{urlencode(params)}" if params else ""
    return f"{base}{path}{query}"


# =============================================================================
# Messages
# =============================================================================
async def send_verification_email(*, to: str, name: str, token: str) -> bool:
    link = _frontend_url("/verify-email", token=token)
    hours = settings.email_verification_ttl_hours

    html = _render(
        """
        <h1>Confirm your email</h1>
        <p>Hi {{ name }}, welcome to Personal ERP. Confirm this address to activate
        your account.</p>
        <a class="btn" href="{{ link }}">Verify email address</a>
        <p class="fallback">Or paste this into your browser:<br>{{ link }}</p>
        <p>This link expires in {{ hours }} hours.</p>
        """,
        subject="Confirm your email",
        name=name,
        link=link,
        hours=hours,
    )
    text = (
        f"Hi {name},\n\nConfirm your email address to activate your Personal ERP account:\n"
        f"{link}\n\nThis link expires in {hours} hours.\n"
    )
    return await send_email(
        to=to, subject="Confirm your email", html=html, text=text, category="verification"
    )


async def send_password_reset_email(*, to: str, name: str, token: str) -> bool:
    link = _frontend_url("/reset-password", token=token)
    minutes = settings.password_reset_ttl_minutes

    html = _render(
        """
        <h1>Reset your password</h1>
        <p>Hi {{ name }}, use the link below to choose a new password.</p>
        <a class="btn" href="{{ link }}">Reset password</a>
        <p class="fallback">Or paste this into your browser:<br>{{ link }}</p>
        <p>This link expires in {{ minutes }} minutes and can be used once.
           If you did not request it, no action is needed.</p>
        """,
        subject="Reset your password",
        name=name,
        link=link,
        minutes=minutes,
    )
    text = (
        f"Hi {name},\n\nReset your Personal ERP password:\n{link}\n\n"
        f"This link expires in {minutes} minutes and can be used once.\n"
        "If you did not request it, ignore this email.\n"
    )
    return await send_email(
        to=to, subject="Reset your password", html=html, text=text, category="password_reset"
    )


async def send_magic_link_email(*, to: str, name: str, token: str) -> bool:
    link = _frontend_url("/magic-link", token=token)
    minutes = settings.magic_link_ttl_minutes

    html = _render(
        """
        <h1>Your sign-in link</h1>
        <p>Hi {{ name }}, tap below to sign in. No password needed.</p>
        <a class="btn" href="{{ link }}">Sign in to Personal ERP</a>
        <p class="fallback">Or paste this into your browser:<br>{{ link }}</p>
        <p>This link expires in {{ minutes }} minutes and can be used once.</p>
        """,
        subject="Your sign-in link",
        name=name,
        link=link,
        minutes=minutes,
    )
    text = (
        f"Hi {name},\n\nSign in to Personal ERP:\n{link}\n\n"
        f"This link expires in {minutes} minutes and can be used once.\n"
    )
    return await send_email(
        to=to, subject="Your sign-in link", html=html, text=text, category="magic_link"
    )


async def send_otp_email(*, to: str, name: str, code: str) -> bool:
    minutes = settings.otp_ttl_minutes

    html = _render(
        """
        <h1>Your sign-in code</h1>
        <p>Hi {{ name }}, enter this code to finish signing in.</p>
        <div class="code">{{ code }}</div>
        <p>This code expires in {{ minutes }} minutes. Never share it with anyone.</p>
        """,
        subject=f"{code} is your sign-in code",
        name=name,
        code=code,
        minutes=minutes,
    )
    text = (
        f"Hi {name},\n\nYour Personal ERP sign-in code is: {code}\n\n"
        f"It expires in {minutes} minutes. Never share it with anyone.\n"
    )
    return await send_email(
        to=to, subject=f"{code} is your sign-in code", html=html, text=text, category="otp"
    )


async def send_invitation_email(
    *,
    to: str,
    organization_name: str,
    inviter_name: str,
    role_name: str,
    token: str,
    message: str | None = None,
) -> bool:
    link = _frontend_url("/accept-invite", token=token)
    days = settings.invite_ttl_days

    html = _render(
        """
        <h1>Join {{ organization_name }}</h1>
        <p>{{ inviter_name }} has invited you to join
           <strong>{{ organization_name }}</strong> on Personal ERP as
           <strong>{{ role_name }}</strong>.</p>
        {% if message %}<p style="padding:12px 14px;background:#f4f4f5;border-radius:8px;
           font-style:italic;">"{{ message }}"</p>{% endif %}
        <a class="btn" href="{{ link }}">Accept invitation</a>
        <p class="fallback">Or paste this into your browser:<br>{{ link }}</p>
        <p>This invitation expires in {{ days }} days.</p>
        """,
        subject=f"{inviter_name} invited you to {organization_name}",
        footer=(
            "You are receiving this because someone invited this address to an "
            "organization on Personal ERP. If this was unexpected, you can ignore it."
        ),
        organization_name=organization_name,
        inviter_name=inviter_name,
        role_name=role_name,
        link=link,
        days=days,
        message=message,
    )
    text = (
        f"{inviter_name} invited you to join {organization_name} on Personal ERP "
        f"as {role_name}.\n\n"
        + (f'Their message: "{message}"\n\n' if message else "")
        + f"Accept the invitation:\n{link}\n\nThis invitation expires in {days} days.\n"
    )
    return await send_email(
        to=to,
        subject=f"{inviter_name} invited you to {organization_name}",
        html=html,
        text=text,
        category="invitation",
    )


async def send_password_changed_email(*, to: str, name: str) -> bool:
    """Security notification. Not optional.

    If an attacker changes the password, this is the account owner's only signal
    that it happened while they can still act on it.
    """
    html = _render(
        """
        <h1>Your password was changed</h1>
        <p>Hi {{ name }}, the password on your Personal ERP account was just changed,
           and every other session was signed out.</p>
        <p>If this was not you, reset your password immediately and review your
           active devices.</p>
        <a class="btn" href="{{ link }}">Reset password</a>
        """,
        subject="Your password was changed",
        name=name,
        link=_frontend_url("/forgot-password"),
    )
    text = (
        f"Hi {name},\n\nThe password on your Personal ERP account was just changed and all "
        f"other sessions were signed out.\n\nIf this was not you, reset your password "
        f"immediately: {_frontend_url('/forgot-password')}\n"
    )
    return await send_email(
        to=to, subject="Your password was changed", html=html, text=text, category="security"
    )
