"""Transactional email through the Gmail API.

**One transport, in one file.** Everything here - parsing the credential, minting
access tokens, posting the message, and the six message templates - is the single
path an email takes out of this application. There is no SMTP fallback and no
local mail catcher: a second transport means two code paths that can render the
same email differently, and the one that is not exercised is the one that breaks.

Two behaviours, chosen by whether ``GMAIL_CREDENTIALS_B64`` is configured:

* **Configured** - sends through the Gmail API.
* **Not configured** - renders the message and writes it to the logifyx log,
  including the verification/reset link. This is not a transport; it is what makes
  the test suite and a fresh checkout work with no credentials at all, and it is
  the only way to click a verification link without them.

**Why the Gmail API rather than SMTP.** Google refuses plain passwords, and app
passwords require 2FA plus a per-account secret that any Workspace admin can
switch off org-wide. A refresh token scoped to ``gmail.send`` grants exactly one
capability - sending - so a leaked credential cannot read the mailbox it sends
from.

**The official client, not hand-rolled HTTP.** ``google-api-python-client`` owns the
send and ``google-auth`` owns the token lifecycle, so neither is reimplemented here
and neither drifts when Google changes it. The catch is that both are synchronous -
httplib2 underneath - so a send must leave the event loop or it stalls every other
request while it waits; see :func:`_send_sync`.

Configuration is a single base64 blob. The JSON inside needs three fields -
``client_id``, ``client_secret`` and ``refresh_token`` - and both file layouts
Google's tooling emits are accepted:

* ``token.json`` from the OAuth quickstart - the three fields at the top level,
  alongside others that are ignored.
* ``credentials.json`` with an ``installed`` or ``web`` wrapper, provided the
  refresh token is in there too.

Base64 rather than raw JSON because a ``.env`` value cannot hold newlines, and
quoting a JSON document through docker compose, a shell and pydantic is a reliable
source of corrupted secrets. One opaque line has no such edges.

Sending never raises into a request. A signup that succeeded must not report
failure because Google was briefly unreachable - the user can always request
another verification email, but a rolled-back registration is unrecoverable. A
transient failure is retried a few times and logged as a warning; a permanent one,
or the last attempt, is logged at error level for alerting.

Templates are inline Jinja2 rather than files: Stage 1 has six emails, and a
template directory plus loader configuration is machinery for a problem that does
not exist yet. Extracting them is mechanical when the count grows.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import threading
from dataclasses import dataclass
from email.message import EmailMessage
from email.policy import SMTP as SMTP_POLICY
from typing import Any, Final

import anyio.to_thread
from google.auth.exceptions import RefreshError, TransportError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from jinja2 import Environment, select_autoescape
from markupsafe import Markup

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_TOKEN_URI: Final = "https://oauth2.googleapis.com/token"

#: The scope the refresh token must carry. Not requested here - it is fixed when the
#: token is minted - but declared so google-auth knows what it holds, and so the
#: error path can say what is missing.
SEND_SCOPE: Final = "https://www.googleapis.com/auth/gmail.send"

#: Attempts per message, and the waits between them.
#:
#: Deliberately short. Sends are awaited inside the request that triggered them -
#: registration waits for its own verification email - so every second here is a
#: second the user waits. Three quick attempts ride out a blip; a longer ladder
#: would just make a failing signup feel broken. Only transient failures are
#: retried at all, so a bad credential still fails on the first attempt.
_MAX_ATTEMPTS: Final = 3
_RETRY_WAITS: Final = (1.0, 2.0)


class GmailConfigurationError(RuntimeError):
    """The configured credentials are absent or malformed."""


# =============================================================================
# Credentials
# =============================================================================
@dataclass(frozen=True, slots=True)
class GmailCredentials:
    """The three fields needed to mint access tokens for one mailbox."""

    client_id: str
    client_secret: str
    refresh_token: str


def _decode_credentials(blob: str) -> GmailCredentials:
    """Parse the base64 JSON blob, with errors that name the actual problem.

    Every failure here is a deployment typo, and the difference between "not valid
    base64" and "no refresh_token" is the difference between a five-second fix and
    an hour of guessing - so they are reported separately.
    """
    # Whitespace is stripped rather than rejected: `base64` without `-w0` wraps at
    # 76 columns, and pasting that in is a mistake worth absorbing rather than
    # bouncing.
    packed = "".join(blob.split())
    if not packed:
        raise GmailConfigurationError("GMAIL_CREDENTIALS_B64 is empty")

    try:
        raw = base64.b64decode(packed, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise GmailConfigurationError(
            "GMAIL_CREDENTIALS_B64 is not valid base64. Produce it with: base64 -w0 token.json"
        ) from exc

    # A pickled `Credentials`, which is what the *old* Gmail quickstart wrote as
    # `token.pickle`. Named specifically because the generic "not JSON" message sends
    # you looking for a typo in a blob that is, in fact, exactly what some tutorial
    # told you to produce. `pickle.loads` is deliberately not offered as a fallback:
    # unpickling a value that arrives from configuration is arbitrary code execution,
    # and no convenience is worth putting that in a mail path.
    if raw[:2] in (b"\x80\x02", b"\x80\x03", b"\x80\x04", b"\x80\x05"):
        raise GmailConfigurationError(
            "GMAIL_CREDENTIALS_B64 is a pickled Credentials object (the old "
            "token.pickle format), which this deliberately will not load. Convert it "
            "to JSON once: "
            'python -c "import pickle,base64,pathlib; '
            "print(pickle.loads(base64.b64decode(pathlib.Path('blob.txt').read_text()))"
            '.to_json())" > token.json - then base64 that file.'
        )

    try:
        document: Any = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GmailConfigurationError(
            "GMAIL_CREDENTIALS_B64 decoded to something that is not JSON. It should "
            "be the base64 of an OAuth token file, not of a bare token string."
        ) from exc

    if not isinstance(document, dict):
        raise GmailConfigurationError("GMAIL_CREDENTIALS_B64 must decode to a JSON object")

    # `credentials.json` nests the client under `installed` (desktop apps) or `web`.
    # Flattening both means either file works without the operator having to know
    # which one they downloaded.
    fields: dict[str, Any] = {}
    for wrapper in ("installed", "web"):
        nested = document.get(wrapper)
        if isinstance(nested, dict):
            fields.update(nested)
    fields.update({key: value for key, value in document.items() if not isinstance(value, dict)})

    missing = [
        name
        for name in ("client_id", "client_secret", "refresh_token")
        if not isinstance(fields.get(name), str) or not fields[name]
    ]
    if missing:
        hint = ""
        if document.get("type") == "service_account":
            # Worth naming, because the fix is not "add a field" - it is a different
            # credential entirely, and a service account additionally needs
            # domain-wide delegation before it can send as a user.
            hint = (
                " This looks like a service-account key; this transport expects an "
                "OAuth user credential with a refresh token."
            )
        raise GmailConfigurationError(
            f"GMAIL_CREDENTIALS_B64 is missing {', '.join(missing)}.{hint}"
        )

    return GmailCredentials(
        client_id=fields["client_id"],
        client_secret=fields["client_secret"],
        refresh_token=fields["refresh_token"],
    )


# =============================================================================
# Transport
# =============================================================================
#: The live credential, and the blob it was built from.
#:
#: Rebuilt only when the setting changes. Holding it is what makes an access token
#: last: google-auth refreshes it in place when it expires, so a run of emails costs
#: one token request rather than one per message.
_credentials: Credentials | None = None
_credentials_blob: str | None = None

#: Sends are serialised.
#:
#: Neither the httplib2 connection inside a service object nor a shared
#: ``Credentials`` is thread-safe, and two worker threads refreshing the same
#: credential at once is a race on the token. Transactional mail is a handful of
#: messages per signup, so serialising costs nothing measurable and removes the
#: whole class of problem - where the alternative, a fresh credential per send,
#: would re-authenticate on every email.
_send_lock = threading.Lock()


def reset_credentials_cache() -> None:
    """Forget the built credential. Used by tests and after a config change."""
    global _credentials, _credentials_blob
    with _send_lock:
        _credentials = None
        _credentials_blob = None


def _authenticate_gmail() -> Any:
    """Build an authorised Gmail client.

    Blocking: called only from a worker thread, and only under :data:`_send_lock`.
    """
    global _credentials, _credentials_blob

    blob = settings.gmail_credentials_b64
    if not blob:
        raise GmailConfigurationError("GMAIL_CREDENTIALS_B64 is not set")

    if _credentials is None or _credentials_blob != blob:
        parsed = _decode_credentials(blob)
        # `token=None` starts with nothing but the refresh token, which is all the
        # configuration carries; google-auth mints an access token before the first
        # call and renews it as needed.
        #
        # The ignore is google-auth's own doing: it ships `py.typed` but leaves this
        # constructor unannotated, so strict mode sees an untyped call into a library
        # it otherwise types. Narrower than exempting the whole module.
        _credentials = Credentials(  # type: ignore[no-untyped-call]
            token=None,
            refresh_token=parsed.refresh_token,
            token_uri=_TOKEN_URI,
            client_id=parsed.client_id,
            client_secret=parsed.client_secret,
            scopes=[SEND_SCOPE],
        )
        _credentials_blob = blob

    # `cache_discovery=False` silences a warning about an oauth2client file cache
    # this project does not use. The discovery document is the one bundled with the
    # library, so building a service makes no network call of its own.
    return build("gmail", "v1", credentials=_credentials, cache_discovery=False)


def _send_sync(message: EmailMessage) -> None:
    """Post one message. Blocking - the whole reason this runs in a thread."""
    # `raw` is a complete RFC 5322 message, so it is serialised with the SMTP
    # policy: CRLF line endings and folded headers, the same bytes any mail
    # transport would put on the wire.
    raw = base64.urlsafe_b64encode(message.as_bytes(policy=SMTP_POLICY)).decode("ascii")
    with _send_lock:
        service = _authenticate_gmail()
        service.users().messages().send(userId="me", body={"raw": raw}).execute()


def _is_transient(exc: BaseException) -> bool:
    """Whether retrying this failure could plausibly succeed.

    The distinction matters because the caller is a user waiting on a response.
    Retrying a revoked token or a missing scope cannot work - it only adds delay to a
    failure that is already certain - so those give up immediately.
    """
    if isinstance(exc, (GmailConfigurationError, RefreshError)):
        # A malformed blob, or a refresh token Google has rejected. Neither is fixed
        # by asking again.
        return False
    if isinstance(exc, HttpError):
        status = exc.status_code
        # 429 and 5xx are Google saying "not now". Every other 4xx is "not ever".
        return status is not None and (status == 429 or status >= 500)
    # A DNS failure, a dropped connection, a timeout.
    return isinstance(exc, (TransportError, OSError, TimeoutError))


def _describe(exc: BaseException) -> str:
    """A one-line reason, carrying Google's own wording where there is one."""
    if isinstance(exc, HttpError):
        return f"HTTP {exc.status_code}: {exc}"
    return f"{type(exc).__name__}: {exc}"


# =============================================================================
# Rendering
# =============================================================================
#: ``autoescape`` is non-negotiable: user-supplied names go into these bodies, and
#: an unescaped one is HTML injection into whatever the recipient's client renders.
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
    """Render a body template, then wrap it in the shared layout.

    **`Markup` is what makes the two stages work.** `render()` returns a plain
    `str`, and dropping a plain `str` into the layout's `{{ body }}` escapes it a
    second time - which turned every email into a wall of visible source, `&lt;h1&gt;`
    and all, with the verification button rendered as text rather than a link. The
    styles went the same way: `'Segoe UI'` arrived as `&#39;Segoe UI&#39;` and the
    font declaration died with it.

    This is safe rather than a hole punched in the autoescaping, and the ordering is
    the reason: the inner render escapes every value in `context` as it interpolates
    it, so by the time the result is marked safe, the only markup left in it is the
    template's own. `footer` is deliberately *not* marked - it is prose, and leaving
    it escaped means a caller cannot smuggle markup in through it.
    """
    body = _jinja.from_string(body_template).render(**context)
    return _jinja.from_string(_LAYOUT).render(
        subject=subject,
        # S704 is the right rule in general - `Markup` on a computed string is how
        # XSS arrives - and it cannot see either argument's provenance. `_BASE_STYLES`
        # is a module constant, and `body` was escaped by the render above; see the
        # docstring. Silenced per line, so the next `Markup` still has to argue for
        # itself.
        styles=Markup(_BASE_STYLES),  # noqa: S704
        body=Markup(body),  # noqa: S704
        footer=footer,
    )


# =============================================================================
# Send
# =============================================================================
async def send_email(
    *,
    to: str,
    subject: str,
    html: str,
    text: str,
    category: str = "transactional",
) -> bool:
    """Send one message. Returns success; never raises.

    A plaintext alternative always accompanies the HTML - some clients refuse to
    render HTML, and multipart messages score better with spam filters.
    """
    if not settings.emails_enabled:
        # Development: the link in `text` is the whole point of this branch.
        log.warning(
            "email suppressed (GMAIL_CREDENTIALS_B64 not set) - body follows",
            extra={"to": to, "subject": subject, "category": category, "body": text},
        )
        return True

    message = EmailMessage()
    # Omitted rather than guessed when unset: Gmail fills in the authorised
    # mailbox itself, and inventing an address here would either be rewritten or
    # rejected. Setting GMAIL_SENDER is what buys the display name.
    if settings.gmail_sender:
        message["From"] = f"{settings.email_from_name} <{settings.gmail_sender}>"
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text)
    message.add_alternative(html, subtype="html")

    context = {"to": to, "subject": subject, "category": category}

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            # `googleapiclient` is synchronous - httplib2 under the hood - so it has
            # to leave the event loop or it stalls every other request for the
            # duration of an SMTP-speed round trip. `anyio` rather than
            # `asyncio.to_thread` because that is the pool FastAPI already sizes and
            # instruments.
            await anyio.to_thread.run_sync(_send_sync, message)
            log.info("email sent", extra=context)
            return True
        except Exception as exc:
            retryable = _is_transient(exc) and attempt < _MAX_ATTEMPTS
            # Swallowed either way - see the module docstring. A retryable failure is
            # a warning because it may yet succeed; the last one is the error that
            # should page someone.
            log.log(
                logging.WARNING if retryable else logging.ERROR,
                "email delivery failed",
                extra={
                    **context,
                    "attempt": attempt,
                    "attempts": _MAX_ATTEMPTS,
                    "error": _describe(exc),
                    "will_retry": retryable,
                },
                exc_info=not retryable,
            )
            if not retryable:
                return False
            await asyncio.sleep(_RETRY_WAITS[attempt - 1])

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
