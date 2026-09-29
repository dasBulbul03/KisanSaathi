"""Security primitives: password hashing, JWT issue/verify, opaque tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from jose import JWTError, jwt

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised when a token is malformed, expired or has the wrong type."""


# ---------------------------------------------------------------- passwords
def hash_password(password: str) -> str:
    """Hash a password with PBKDF2-HMAC-SHA256.

    PBKDF2 is used instead of bcrypt so the project has no native build
    dependency and behaves identically on every platform (important for the
    Docker/CI matrix).
    """
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), settings.PBKDF2_ITERATIONS
    )
    return f"pbkdf2_sha256${settings.PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    if not password_hash:
        return False
    try:
        algorithm, iterations, salt, digest_hex = password_hash.split("$")
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt.encode("utf-8"), int(iterations)
    )
    return hmac.compare_digest(candidate.hex(), digest_hex)


def validate_password_strength(password: str) -> None:
    if len(password) < settings.PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Password must be at least {settings.PASSWORD_MIN_LENGTH} characters long."
        )
    if password.lower() == password or password.upper() == password:
        raise ValueError("Password must contain both lowercase and uppercase letters.")
    if not any(ch.isdigit() for ch in password):
        raise ValueError("Password must contain at least one digit.")


# --------------------------------------------------------------------- JWT
def _secret() -> str:
    if settings.JWT_SECRET_KEY:
        return settings.JWT_SECRET_KEY
    # Development/test convenience only; validate_runtime() blocks this elsewhere.
    if settings.ENVIRONMENT in ("development", "test"):
        return "kisansaathi-insecure-development-secret-key"
    raise TokenError("JWT secret is not configured.")


def _create_token(
    subject: str, token_type: TokenType, expires: timedelta, **claims: Any
) -> tuple[str, datetime, str]:
    now = datetime.now(UTC)
    expires_at = now + expires
    jti = uuid.uuid4().hex
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "nbf": int(now.timestamp()),
        "exp": int(expires_at.timestamp()),
        "jti": jti,
    }
    payload.update(claims)
    encoded = jwt.encode(payload, _secret(), algorithm=settings.JWT_ALGORITHM)
    return encoded, expires_at, jti


def create_access_token(
    subject: str,
    *,
    roles: list[str] | None = None,
    extra: dict[str, Any] | None = None,
) -> tuple[str, datetime]:
    token, expires_at, _ = _create_token(
        subject,
        "access",
        timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        roles=roles or [],
        **(extra or {}),
    )
    return token, expires_at


def create_refresh_token(subject: str) -> tuple[str, datetime, str]:
    return _create_token(subject, "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, *, expected_type: TokenType = "access") -> dict[str, Any]:
    try:
        payload = jwt.decode(token, _secret(), algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        raise TokenError(f"Expected a {expected_type} token.")
    if not payload.get("sub"):
        raise TokenError("Token is missing a subject.")
    return payload


# ----------------------------------------------------------- opaque tokens
def generate_opaque_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()
