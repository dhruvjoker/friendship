"""
app/monitoring.py
=================
Production observability for Sphinx.

Integrates:
  • Sentry  — error tracking + performance tracing
  • structlog — structured JSON logging (feeds Better Stack / Grafana Loki)
  • /health  — uptime ping endpoint (Better Stack / UptimeRobot target)

Usage in app/__init__.py (add near the top of create_app):
    from app.monitoring import init_monitoring
    init_monitoring(app)

Environment variables required:
    SENTRY_DSN=https://...@sentry.io/...
    SENTRY_TRACES_SAMPLE_RATE=0.1      (optional, default 0.05)
    SENTRY_PROFILES_SAMPLE_RATE=0.05   (optional)
    LOG_LEVEL=INFO                     (optional, default WARNING in prod)
"""

import os
import logging
import time
from flask import Blueprint, jsonify, g, request

# ─── Health check blueprint ─────────────────────────────────────────────────
health_bp = Blueprint('health', __name__)

@health_bp.route('/health')
def health():
    """Uptime-monitor target. Returns 200 + basic DB check."""
    from app.models import db
    try:
        db.session.execute(db.text('SELECT 1'))
        db_ok = True
    except Exception:
        db_ok = False
    status = 200 if db_ok else 503
    return jsonify({'status': 'ok' if db_ok else 'degraded', 'db': db_ok}), status


# ─── Sentry ─────────────────────────────────────────────────────────────────
def _init_sentry(app):
    dsn = os.getenv('SENTRY_DSN', '')
    if not dsn:
        app.logger.info('Sentry DSN not set — skipping Sentry init')
        return

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask     import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging   import LoggingIntegration

        sentry_sdk.init(
            dsn=dsn,
            integrations=[
                FlaskIntegration(),
                SqlalchemyIntegration(),
                LoggingIntegration(level=logging.WARNING, event_level=logging.ERROR),
            ],
            traces_sample_rate=float(os.getenv('SENTRY_TRACES_SAMPLE_RATE', '0.05')),
            profiles_sample_rate=float(os.getenv('SENTRY_PROFILES_SAMPLE_RATE', '0.05')),
            environment=os.getenv('FLASK_ENV', 'production'),
            release=os.getenv('APP_VERSION', 'unknown'),
            # Strip PII: don't send IP or user-agent by default
            send_default_pii=False,
        )
        app.logger.info('Sentry initialised')
    except ImportError:
        app.logger.warning('sentry-sdk not installed. Run: pip install sentry-sdk[flask]')


# ─── Structured logging ──────────────────────────────────────────────────────
def _init_structlog(app):
    """
    Configure structlog for JSON output.
    Install: pip install structlog
    """
    try:
        import structlog

        structlog.configure(
            processors=[
                structlog.stdlib.add_log_level,
                structlog.stdlib.add_logger_name,
                structlog.processors.TimeStamper(fmt='iso'),
                structlog.processors.StackInfoRenderer(),
                structlog.processors.format_exc_info,
                structlog.processors.UnicodeDecoder(),
                structlog.processors.JSONRenderer(),
            ],
            wrapper_class=structlog.stdlib.BoundLogger,
            context_class=dict,
            logger_factory=structlog.stdlib.LoggerFactory(),
        )

        # Wire Flask's logger through structlog
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter('%(message)s'))
        level = getattr(logging, os.getenv('LOG_LEVEL', 'WARNING').upper(), logging.WARNING)
        app.logger.handlers = [handler]
        app.logger.setLevel(level)
        app.logger.propagate = False
        app.logger.info('structlog initialised')
    except ImportError:
        app.logger.info('structlog not installed — using stdlib logging. Run: pip install structlog')


# ─── Request timing middleware ───────────────────────────────────────────────
def _init_request_timing(app):
    @app.before_request
    def _start_timer():
        g._req_start = time.perf_counter()

    @app.after_request
    def _log_request(response):
        elapsed = (time.perf_counter() - g.get('_req_start', time.perf_counter())) * 1000
        if elapsed > 500:  # only log slow requests
            app.logger.warning(
                'slow_request',
                extra={
                    'method': request.method,
                    'path': request.path,
                    'status': response.status_code,
                    'ms': round(elapsed, 1),
                }
            )
        return response


# ─── Public init ─────────────────────────────────────────────────────────────
def init_monitoring(app):
    """Call once inside create_app() after app is configured."""
    _init_sentry(app)
    _init_structlog(app)
    _init_request_timing(app)
    app.register_blueprint(health_bp)
    app.logger.info('Monitoring initialised')
