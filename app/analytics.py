"""
analytics.py — Lightweight analytics, error tracking, and funnel instrumentation.

Drop-in addition to the existing app/monitoring.py.
Tracks:
  - Page views (anonymised)
  - Sign-up funnel events
  - Match creation & acceptance
  - Chat engagement (messages sent, session length)
  - User retention signals

Production stack recommended:
  - Posthog (self-hostable, privacy-first analytics)
  - Sentry (error tracking, performance)
  - structlog (already in monitoring.py — reused here)

Set environment variables:
  POSTHOG_API_KEY   — from posthog.com or your self-hosted instance
  POSTHOG_HOST      — default: https://app.posthog.com
  SENTRY_DSN        — from sentry.io

All events use an anonymous session_id — never a user ID or email.
"""

import logging
import time
import uuid
from functools import wraps

from flask import g, request, session

logger = logging.getLogger(__name__)

# ── Try to import optional analytics libraries ──────────────────────────────
try:
    import posthog as _ph
    _POSTHOG_AVAILABLE = True
except ImportError:
    _POSTHOG_AVAILABLE = False
    logger.warning("posthog not installed. Run: pip install posthog")

try:
    import sentry_sdk
    from sentry_sdk.integrations.flask import FlaskIntegration
    _SENTRY_AVAILABLE = True
except ImportError:
    _SENTRY_AVAILABLE = False
    logger.warning("sentry-sdk not installed. Run: pip install sentry-sdk[flask]")


# ── Initialisation ───────────────────────────────────────────────────────────

def init_analytics(app):
    """
    Call this from create_app(), after init_monitoring().

    Example:
        from app.analytics import init_analytics
        init_analytics(app)
    """
    _init_sentry(app)
    _init_posthog(app)
    _register_request_hooks(app)
    logger.info("Analytics initialised")


def _init_sentry(app):
    dsn = app.config.get("SENTRY_DSN") or ""
    if not dsn or not _SENTRY_AVAILABLE:
        return

    environment = app.config.get("ENV", "production")

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FlaskIntegration()],
        environment=environment,
        # Only sample 20% of transactions in prod to keep costs low
        traces_sample_rate=0.2,
        # Don't send PII
        send_default_pii=False,
    )
    logger.info("Sentry initialised (env=%s)", environment)


def _init_posthog(app):
    api_key = app.config.get("POSTHOG_API_KEY") or ""
    host = app.config.get("POSTHOG_HOST", "https://app.posthog.com")

    if not api_key or not _POSTHOG_AVAILABLE:
        return

    import posthog
    posthog.project_api_key = api_key
    posthog.host = host
    # Disable in development
    if app.config.get("FLASK_ENV") == "development":
        posthog.disabled = True
    logger.info("Posthog initialised (host=%s)", host)


def _register_request_hooks(app):
    """Track page views and request timing anonymously."""

    @app.before_request
    def _start_timer():
        g.request_start = time.time()
        # Assign anonymous session ID if none exists
        if "analytics_id" not in session:
            session["analytics_id"] = str(uuid.uuid4())
        g.analytics_id = session["analytics_id"]

    @app.after_request
    def _track_pageview(response):
        # Only track GET requests to non-API routes
        if request.method != "GET":
            return response
        if request.path.startswith(("/api/", "/static/", "/favicon")):
            return response

        duration_ms = int((time.time() - g.get("request_start", time.time())) * 1000)

        _capture(
            event="$pageview",
            properties={
                "$current_url": request.url,
                "path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "referrer": request.referrer or "",
            },
        )
        return response


# ── Public event API ─────────────────────────────────────────────────────────

def track_signup_started():
    """User opened the registration page."""
    _capture("signup_started", {"step": "register_page_view"})


def track_signup_completed(user_id_hash: str, problems_count: int):
    """
    User successfully registered.
    Pass a hashed (non-reversible) user ID for funnel stitching.
    Never pass raw user ID or email.
    """
    _capture("signup_completed", {
        "problems_selected": problems_count,
        "user_cohort": user_id_hash[:8],  # First 8 chars of hash only
    })


def track_match_created(common_problems_count: int):
    """A match was successfully made between two users."""
    _capture("match_created", {
        "common_problems": common_problems_count,
    })


def track_match_accepted():
    """User accepted / started chatting with a match."""
    _capture("match_accepted")


def track_message_sent(is_first_message: bool = False):
    """A message was sent in a chat. Track volume and first-message milestone."""
    _capture("message_sent", {
        "first_message_in_conversation": is_first_message,
    })


def track_chat_session_ended(duration_seconds: int, message_count: int):
    """Called when a user leaves a chat page. Measures engagement depth."""
    _capture("chat_session_ended", {
        "duration_seconds": duration_seconds,
        "message_count": message_count,
        "engaged": duration_seconds > 120 and message_count > 3,
    })


def track_report_submitted(reason: str):
    """User filed a safety report."""
    _capture("report_submitted", {"reason": reason})


def track_premium_page_view():
    _capture("premium_page_view")


def track_premium_conversion(plan: str):
    _capture("premium_converted", {"plan": plan})


def track_error(error_type: str, context: str = ""):
    """Application-level error (distinct from Sentry's automatic capture)."""
    _capture("app_error", {"error_type": error_type, "context": context})
    logger.error("App error tracked: %s (context: %s)", error_type, context)


# ── Internal capture helper ──────────────────────────────────────────────────

def _capture(event: str, properties: dict = None):
    """
    Send an event to Posthog using the anonymous session ID.
    Silently no-ops if Posthog is not configured.
    """
    if not _POSTHOG_AVAILABLE:
        return

    import posthog
    if posthog.disabled:
        logger.debug("Analytics [DISABLED]: %s %s", event, properties or {})
        return

    distinct_id = getattr(g, "analytics_id", "anonymous")
    props = properties or {}
    # Add common context
    props.setdefault("platform", "web")

    try:
        posthog.capture(distinct_id, event, props)
    except Exception as exc:
        logger.warning("Posthog capture failed for event '%s': %s", event, exc)


# ── Decorator helper ─────────────────────────────────────────────────────────

def track_event(event_name: str, **extra_props):
    """
    Route decorator to fire an analytics event when a route is called.

    Usage:
        @main_bp.route('/dashboard')
        @login_required
        @track_event('dashboard_viewed')
        def dashboard():
            ...
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            _capture(event_name, extra_props)
            return f(*args, **kwargs)
        return wrapper
    return decorator
