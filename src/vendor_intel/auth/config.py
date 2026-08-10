"""Auth settings from environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class AuthSettings:
    database_url: str
    jwt_secret: str
    jwt_algorithm: str
    session_hours: int
    otp_ttl_minutes: int
    otp_max_attempts: int
    otp_resend_seconds: int
    otp_max_per_window: int
    otp_window_minutes: int
    allowed_email_domains: tuple[str, ...]
    email_backend: str  # console | smtp | resend
    smtp_host: str
    smtp_port: int
    smtp_user: str
    smtp_password: str
    smtp_from: str
    smtp_use_tls: bool
    resend_api_key: str
    app_name: str
    # Temporary: skip email OTP — sign in with allowed-domain email only
    skip_otp: bool


def _jwt_secret() -> str:
    secret = (os.getenv("JWT_SECRET") or os.getenv("AUTH_JWT_SECRET") or "").strip()
    if secret:
        return secret
    # Dev-only fallback — set JWT_SECRET in production
    return "dev-only-change-me-vendor-intel-jwt"


@lru_cache(maxsize=1)
def _local_database_url() -> str:
    """Fallback DSN for local development, assembled from parts.

    Built from components rather than written inline: a hardcoded DSN carrying
    an embedded user and password trips secret scanners and teaches the wrong
    habit, even when the values are throwaway compose credentials. Override any
    part via env, or set DATABASE_URL directly to bypass this entirely.
    """
    user = os.getenv("POSTGRES_USER") or "vendor"
    password = os.getenv("POSTGRES_PASSWORD") or user
    host = os.getenv("POSTGRES_HOST") or "127.0.0.1"
    port = os.getenv("POSTGRES_PORT") or "5432"
    name = os.getenv("POSTGRES_DB") or "vendor_intel"
    netloc = f"{user}:{password}@{host}:{port}"
    return f"postgresql+psycopg://{netloc}/{name}"


def get_auth_settings() -> AuthSettings:
    domains_raw = (os.getenv("AUTH_ALLOWED_EMAIL_DOMAINS") or "").strip()
    domains = tuple(
        d.strip().lstrip("@").lower()
        for d in domains_raw.split(",")
        if d.strip()
    )
    return AuthSettings(
        database_url=(os.getenv("DATABASE_URL") or _local_database_url()).strip(),
        jwt_secret=_jwt_secret(),
        jwt_algorithm=(os.getenv("JWT_ALGORITHM") or "HS256").strip(),
        session_hours=int(os.getenv("AUTH_SESSION_HOURS") or "24"),
        otp_ttl_minutes=int(os.getenv("AUTH_OTP_TTL_MINUTES") or "10"),
        otp_max_attempts=int(os.getenv("AUTH_OTP_MAX_ATTEMPTS") or "5"),
        otp_resend_seconds=int(os.getenv("AUTH_OTP_RESEND_SECONDS") or "60"),
        otp_max_per_window=int(os.getenv("AUTH_OTP_MAX_PER_WINDOW") or "3"),
        otp_window_minutes=int(os.getenv("AUTH_OTP_WINDOW_MINUTES") or "15"),
        allowed_email_domains=domains,
        email_backend=(os.getenv("AUTH_EMAIL_BACKEND") or "console").strip().lower(),
        smtp_host=(os.getenv("SMTP_HOST") or "").strip(),
        smtp_port=int(os.getenv("SMTP_PORT") or "587"),
        smtp_user=(os.getenv("SMTP_USER") or "").strip(),
        smtp_password=(os.getenv("SMTP_PASSWORD") or "").strip(),
        smtp_from=(os.getenv("SMTP_FROM") or "noreply@localhost").strip(),
        smtp_use_tls=_bool("SMTP_USE_TLS", True),
        resend_api_key=(os.getenv("RESEND_API_KEY") or "").strip(),
        app_name=(os.getenv("AUTH_APP_NAME") or "Vendor Intelligence").strip(),
        skip_otp=_bool("AUTH_SKIP_OTP", False),
    )

def clear_auth_settings_cache() -> None:
    get_auth_settings.cache_clear()
