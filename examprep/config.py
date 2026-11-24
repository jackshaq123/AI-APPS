"""Settings, all read from environment variables (see .env.example)."""
import os


def _bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    BASE_URL = os.environ.get("BASE_URL", "http://localhost:5000").rstrip("/")
    BRAND_NAME = os.environ.get("BRAND_NAME", "PassPrep")
    SUPPORT_EMAIL = os.environ.get("SUPPORT_EMAIL", "support@example.com")
    BUSINESS_ADDRESS = os.environ.get("BUSINESS_ADDRESS", "")

    DATABASE_URL = os.environ.get("DATABASE_URL", "sqlite:///examprep.db")
    CONTENT_DIR = os.environ.get(
        "CONTENT_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "content")
    )
    # Exam shown at "/". Every pack is also served at /exam/<slug>.
    DEFAULT_EXAM = os.environ.get("DEFAULT_EXAM", "us-citizenship-2025")
    # Demo packs are hidden unless this is on (it is on in local dev by default).
    SHOW_DEMO_PACKS = _bool("SHOW_DEMO_PACKS", True)

    STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
    STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
    # Shown after the account name on card statements, so buyers recognize the
    # charge when this shares a Stripe account with another business.
    STATEMENT_DESCRIPTOR_SUFFIX = os.environ.get("STATEMENT_DESCRIPTOR_SUFFIX", "")

    SMTP_HOST = os.environ.get("SMTP_HOST", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USER = os.environ.get("SMTP_USER", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    MAIL_FROM = os.environ.get("MAIL_FROM", "")

    # Local testing only: a "Buy" button that skips Stripe. Ignored when a Stripe key is set.
    ALLOW_FAKE_CHECKOUT = _bool("ALLOW_FAKE_CHECKOUT", False)

    META_PIXEL_ID = os.environ.get("META_PIXEL_ID", "")

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = BASE_URL.startswith("https://")
    PERMANENT_SESSION_LIFETIME = 60 * 60 * 24 * 365
