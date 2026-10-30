"""Cryptographic and authentication security utilities."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from flowpilot.core.config import get_settings

# Initialize Argon2 password hasher
_password_hasher = PasswordHash((Argon2Hasher(),))


class SecurityError(Exception):
    """Base exception for authentication and token validation errors."""


class TokenExpiredError(SecurityError):
    """Raised when an access or refresh token has expired."""


class InvalidTokenError(SecurityError):
    """Raised when a token signature, payload, or type is invalid."""


def hash_password(password: str) -> str:
    """Securely hash a plaintext password using Argon2id."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against an Argon2id hash."""
    return _password_hasher.verify(plain_password, hashed_password)


def hash_token(raw_token: str) -> str:
    """Compute a SHA-256 cryptographic hash of a raw token string."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def create_access_token(
    user_id: uuid.UUID,
    expires_delta: timedelta | None = None,
) -> str:
    """Generate a short-lived signed JWT access token."""
    settings = get_settings()
    now = get_utc_now()
    lifetime = expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    expire = now + lifetime

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "type": "access",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    user_id: uuid.UUID,
    family_id: uuid.UUID | None = None,
    expires_delta: timedelta | None = None,
) -> tuple[str, uuid.UUID, datetime]:
    """Generate a rotating signed JWT refresh token with token-family tracking."""
    settings = get_settings()
    now = get_utc_now()
    lifetime = expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    expire = now + lifetime
    actual_family_id = family_id or uuid.uuid4()

    payload: dict[str, Any] = {
        "sub": str(user_id),
        "fam": str(actual_family_id),
        "iat": int(now.timestamp()),
        "exp": int(expire.timestamp()),
        "jti": uuid.uuid4().hex,
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, actual_family_id, expire


def decode_token(
    token: str,
    expected_type: str = "access",
) -> dict[str, Any]:
    """Decode and validate a JWT token, ensuring cryptographic validity and token type."""
    settings = get_settings()
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.ExpiredSignatureError as exc:
        msg = f"{expected_type.capitalize()} token has expired."
        raise TokenExpiredError(msg) from exc
    except jwt.InvalidTokenError as exc:
        msg = f"Invalid {expected_type} token."
        raise InvalidTokenError(msg) from exc

    token_type = payload.get("type")
    if token_type != expected_type:
        msg = f"Token type mismatch: expected '{expected_type}', got '{token_type}'."
        raise InvalidTokenError(msg)

    if not payload.get("sub"):
        msg = "Token is missing subject claim ('sub')."
        raise InvalidTokenError(msg)

    return payload
