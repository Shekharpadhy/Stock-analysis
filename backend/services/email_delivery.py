"""
Transactional email sender — verification, password reset, and any future
account-lifecycle messages.

Why split from alerts.py
────────────────────────
Alerts and account emails have different ownership: account emails MUST
deliver (a missed verification email is a stuck signup) while a missed alert
is a soft failure. Splitting the codepath documents this contract and lets
us evolve them independently (alerts may be queued, account emails are
sent synchronously and surface failures to the user).

Backend reuse
─────────────
We reuse the SMTP config block defined on `Settings` for alerts so operators
only configure one set of credentials.  The `From` header is the same too.

Templates
─────────
Plain-text body for now — sufficient for transactional content, avoids
HTML-rendering edge cases that hurt deliverability scores.  Swap to MJML or
Jinja2 templates when we add marketing emails.

Public API
──────────
  send_verification_email(to_address, link)
  send_password_reset_email(to_address, link)

Both return True on success, False on any failure (logged, never raises).
The caller decides whether to surface the failure to the user.

Test discipline
───────────────
The actual smtplib.SMTP call is wrapped in _send() — tests patch that to
assert subject/body content without touching the network.
"""

from __future__ import annotations

import logging
import smtplib
import ssl
from email.mime.text import MIMEText

from backend.config import settings

log = logging.getLogger(__name__)


# ── shared transport ─────────────────────────────────────────────────────────

def _send(to_address: str, subject: str, body_plain: str) -> bool:
    """
    Single SMTP submission. Returns True on success, False (logged) otherwise.
    Centralised so tests need only patch this one symbol.
    """
    if not settings.alert_smtp_host or not settings.alert_smtp_user:
        log.warning("email: SMTP not configured — message to %s dropped",
                    to_address)
        return False

    msg = MIMEText(body_plain, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"]    = settings.alert_email_from
    msg["To"]      = to_address

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(settings.alert_smtp_host,
                          settings.alert_smtp_port) as srv:
            srv.ehlo()
            srv.starttls(context=ctx)
            srv.login(settings.alert_smtp_user, settings.alert_smtp_password)
            srv.sendmail(settings.alert_email_from, to_address, msg.as_string())
        log.info("email: sent to %s — %s", to_address, subject)
        return True
    except Exception as exc:                              # noqa: BLE001
        log.warning("email: SMTP delivery to %s failed — %s", to_address, exc)
        return False


# ── account lifecycle templates ───────────────────────────────────────────────

def send_verification_email(to_address: str, verification_link: str) -> bool:
    """Send the post-registration confirmation email."""
    body = (
        "Welcome to Banking Client Sector Intelligence.\n\n"
        "Confirm your email address to activate alerts and watchlists:\n\n"
        f"  {verification_link}\n\n"
        "This link expires in 24 hours.  If you didn't sign up, ignore this "
        "message — no account will be created.\n"
    )
    return _send(to_address, "Confirm your email — BCSI", body)


def send_password_reset_email(to_address: str, reset_link: str) -> bool:
    """Send the password-reset link triggered by /auth/password-reset/request."""
    body = (
        "A password reset was requested for your BCSI account.\n\n"
        "If this was you, follow this link within the next hour to set a "
        "new password:\n\n"
        f"  {reset_link}\n\n"
        "If you didn't request a reset, ignore this message — your password "
        "will stay unchanged and the link will simply expire.\n"
    )
    return _send(to_address, "Reset your BCSI password", body)
