import os
from datetime import timedelta


def _require_env(name: str, default: str = "") -> str:
    """Return env var; in production raise if missing and no default allowed."""
    val = os.getenv(name, default)
    return val


class Config:
    """Base configuration."""

    # ── Security ──────────────────────────────────────────────────────────────
    SECRET_KEY = os.getenv("SECRET_KEY", "")
    if not SECRET_KEY:
        import secrets
        SECRET_KEY = secrets.token_hex(32)  # random per process (fine for dev)

    # ── Database ──────────────────────────────────────────────────────────────
    _db_url = os.getenv("DATABASE_URL", "sqlite:///friendship_app.db")
    # Heroku/Render sometimes gives postgres:// — SQLAlchemy 1.4+ needs postgresql://
    if _db_url.startswith("postgres://"):
        _db_url = _db_url.replace("postgres://", "postgresql://", 1)
    SQLALCHEMY_DATABASE_URI = _db_url
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }

    # ── Admin ─────────────────────────────────────────────────────────────────
    ADMIN_USERNAMES = [
        name.strip()
        for name in os.getenv("ADMIN_USERNAMES", "").split(",")
        if name.strip()
    ]

    # ── Session ───────────────────────────────────────────────────────────────
    PERMANENT_SESSION_LIFETIME = timedelta(days=1)
    SESSION_COOKIE_SECURE = False   # overridden True in ProductionConfig
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Strict"

    # ── Socket.IO ─────────────────────────────────────────────────────────────
    SOCKETIO_MESSAGE_QUEUE = None

    # ── Email (Resend) ────────────────────────────────────────────────────────
    RESEND_API_KEY      = os.getenv("RESEND_API_KEY", "")
    EMAIL_FROM          = os.getenv("EMAIL_FROM", "noreply@friendshipcircle.app")
    EMAIL_SUPPORT       = os.getenv("EMAIL_SUPPORT", "support@friendshipcircle.app")
    APP_BASE_URL        = os.getenv("APP_BASE_URL", "https://friendshipcircle.app")

    # ── Clerk ─────────────────────────────────────────────────────────────────
    CLERK_API_KEY      = os.getenv("CLERK_API_KEY", "")
    CLERK_JWT_KEYS_URL = os.getenv("CLERK_JWT_KEYS_URL", "https://api.clerk.com/v1/jwks")
    CLERK_ISSUER       = os.getenv("CLERK_ISSUER", "")

    # ── Razorpay ──────────────────────────────────────────────────────────────
    RAZORPAY_KEY_ID         = os.getenv("RAZORPAY_KEY_ID", "")
    RAZORPAY_KEY_SECRET     = os.getenv("RAZORPAY_KEY_SECRET", "")
    RAZORPAY_WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

    # ── Rate limiting ─────────────────────────────────────────────────────────
    LOGIN_RATE_LIMIT  = int(os.getenv("LOGIN_RATE_LIMIT", "5"))
    LOGIN_RATE_WINDOW = int(os.getenv("LOGIN_RATE_WINDOW", "900"))  # 15 minutes


class DevelopmentConfig(Config):
    DEBUG = True
    # Relax rate limit in dev so manual testing isn't painful
    LOGIN_RATE_LIMIT  = 50
    LOGIN_RATE_WINDOW = 60


class ProductionConfig(Config):
    DEBUG = False
    SESSION_COOKIE_SECURE = True

    @classmethod
    def validate(cls):
        """Call at startup to catch missing production secrets early."""
        required = ["SECRET_KEY", "DATABASE_URL"]
        missing = [k for k in required if not os.getenv(k)]
        if missing:
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(missing)}"
            )


config = {
    "development": DevelopmentConfig,
    "production":  ProductionConfig,
    "default":     DevelopmentConfig,
}
