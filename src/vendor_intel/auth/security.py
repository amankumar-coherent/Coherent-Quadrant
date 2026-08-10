"""OTP + session token helpers."""
from __future__ import annotations

import hashlib
import hmac
import secrets


def normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def generate_otp(digits: int = 6) -> str:
    upper = 10**digits
    return f"{secrets.randbelow(upper):0{digits}d}"


def hash_secret(value: str) -> str:
    """One-way hash for OTP codes and session tokens (SHA-256 hex)."""
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)


def generate_session_token() -> str:
    """Opaque random id used as JWT jti (session id)."""
    return secrets.token_urlsafe(32)


def generate_jti() -> str:
    return secrets.token_urlsafe(24)
