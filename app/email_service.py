"""
app/email_service.py
====================
Transactional email via Resend (https://resend.com).
All send_* functions are safe to call even when RESEND_API_KEY is unset —
they log a warning and return False instead of crashing.

Install:  pip install resend
Env vars: RESEND_API_KEY, EMAIL_FROM, APP_BASE_URL
"""

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


def _client():
    """Return a Resend client, or None if the SDK / key is unavailable."""
    api_key = os.getenv("RESEND_API_KEY", "")
    if not api_key:
        return None
    try:
        import resend as _resend
        _resend.api_key = api_key
        return _resend
    except ImportError:
        logger.warning("resend package not installed — email sending disabled. Run: pip install resend")
        return None


def _send(to: str, subject: str, html: str) -> bool:
    """Low-level send; returns True on success."""
    client = _client()
    if not client:
        logger.warning("Email not sent (no Resend client): subject=%s to=%s", subject, to)
        return False
    from_addr = os.getenv("EMAIL_FROM", "noreply@friendshipcircle.app")
    try:
        client.Emails.send({"from": from_addr, "to": [to], "subject": subject, "html": html})
        logger.info("Email sent: subject=%s to_domain=%s", subject, to.split("@")[-1])
        return True
    except Exception as exc:
        logger.error("Email send failed: %s", exc)
        return False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _base_url() -> str:
    return os.getenv("APP_BASE_URL", "https://friendshipcircle.app").rstrip("/")


def _wrap_html(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>{title}</title>
<style>
  body {{font-family:Arial,sans-serif;background:#0a0a0f;color:#e0e0e0;margin:0;padding:0}}
  .wrap {{max-width:520px;margin:40px auto;background:#13131a;border-radius:12px;padding:36px}}
  h2 {{color:#7b61ff;margin-top:0}}
  a.btn {{display:inline-block;background:#7b61ff;color:#fff;text-decoration:none;
          padding:12px 28px;border-radius:8px;font-weight:bold;margin-top:16px}}
  p {{line-height:1.6;color:#b0b0c0}}
  .footer {{margin-top:32px;font-size:12px;color:#555}}
</style></head>
<body><div class="wrap">{body}
<div class="footer">Friendship Circle &mdash; You&rsquo;re Not Alone<br>
If you didn&rsquo;t request this, ignore this email.</div>
</div></body></html>"""


# ── Public API ────────────────────────────────────────────────────────────────

def send_verification_email(to: str, token: str) -> bool:
    url = f"{_base_url()}/auth/verify-email/{token}"
    body = f"""
<h2>Verify your email</h2>
<p>Welcome to Friendship Circle! Click the button below to confirm your email address
and activate your account.</p>
<a class="btn" href="{url}">Verify my email</a>
<p style="margin-top:20px;font-size:13px;color:#666">
Or copy this link: <a href="{url}" style="color:#7b61ff">{url}</a><br>
This link expires in 24 hours.
</p>"""
    return _send(to, "Verify your Friendship Circle email", _wrap_html("Verify email", body))


def send_welcome_email(to: str, username: str) -> bool:
    dashboard = f"{_base_url()}/dashboard"
    body = f"""
<h2>Welcome, {username} 🎉</h2>
<p>Your account is verified and ready. Friendship Circle is a safe, anonymous space
to connect with people who truly understand what you're going through.</p>
<a class="btn" href="{dashboard}">Go to my dashboard</a>
<p>Remember: you can update your interests, find matches, and reach out to our
support team any time from the dashboard.</p>"""
    return _send(to, "Welcome to Friendship Circle 🌙", _wrap_html("Welcome", body))


def send_password_reset_email(to: str, token: str) -> bool:
    url = f"{_base_url()}/auth/reset-password/{token}"
    body = f"""
<h2>Reset your password</h2>
<p>We received a request to reset the password for this account.
Click the button below to choose a new password.</p>
<a class="btn" href="{url}">Reset my password</a>
<p style="margin-top:20px;font-size:13px;color:#666">
Or copy this link: <a href="{url}" style="color:#7b61ff">{url}</a><br>
This link expires in 1 hour. If you didn&rsquo;t request a reset, you can safely ignore this.
</p>"""
    return _send(to, "Reset your Friendship Circle password", _wrap_html("Reset password", body))


def send_account_deletion_email(to: str, username: str) -> bool:
    body = f"""
<h2>Your account has been deleted</h2>
<p>Hi {username}, your Friendship Circle account and all associated data have been
permanently deleted as requested.</p>
<p>We're sorry to see you go. If this was a mistake or you have questions,
please contact us at <a href="mailto:support@friendshipcircle.app" style="color:#7b61ff">
support@friendshipcircle.app</a> within 7 days — we may be able to help.</p>"""
    return _send(to, "Your account has been deleted", _wrap_html("Account deleted", body))


def send_report_received_email(to: str) -> bool:
    body = """
<h2>Report received</h2>
<p>Thank you for your report. Our moderation team has received it and will review
it within 24 hours. We take all reports seriously.</p>
<p>We'll notify you once a decision has been made.</p>"""
    return _send(to, "We received your report", _wrap_html("Report received", body))


def send_report_actioned_email(to: str) -> bool:
    body = """
<h2>Action taken on your report</h2>
<p>Our moderation team has reviewed the report you submitted and has taken
appropriate action in line with our Community Guidelines.</p>
<p>Thank you for helping keep Friendship Circle safe.</p>"""
    return _send(to, "Update on your report", _wrap_html("Report update", body))


def send_ban_notification_email(to: str, reason: str) -> bool:
    body = f"""
<h2>Account suspended</h2>
<p>Your Friendship Circle account has been suspended for the following reason:</p>
<blockquote style="border-left:3px solid #7b61ff;padding-left:12px;color:#aaa">{reason}</blockquote>
<p>If you believe this is a mistake, please contact
<a href="mailto:support@friendshipcircle.app" style="color:#7b61ff">support@friendshipcircle.app</a>
to appeal.</p>"""
    return _send(to, "Your Friendship Circle account has been suspended", _wrap_html("Account suspended", body))


def send_contact_form_email(from_email: str, category: str, subject: str, message: str) -> bool:
    """Forward a contact form submission to the support inbox."""
    support = os.getenv("EMAIL_SUPPORT", "support@friendshipcircle.app")
    routing = {
        "safety":  "safety@friendshipcircle.app",
        "billing": "billing@friendshipcircle.app",
        "privacy": "privacy@friendshipcircle.app",
        "legal":   "legal@friendshipcircle.app",
    }
    to = routing.get(category, support)
    body = f"""
<h2>[{category.upper()}] {subject}</h2>
<p><strong>From:</strong> {from_email}</p>
<hr style="border-color:#333">
<p style="white-space:pre-wrap">{message}</p>"""
    return _send(to, f"[Contact Form] [{category.upper()}] {subject}", _wrap_html("Contact form", body))
