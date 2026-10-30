"""Automated test suite for password recovery, rate limiting, and auth error granularity."""

import secrets
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.security import hash_token, verify_password
from flowpilot.models.password_reset_token import PasswordResetToken
from flowpilot.models.refresh_token import RefreshToken
from flowpilot.models.user import User


def test_login_development_unknown_account(client: TestClient) -> None:
    """Verify development mode returns detailed unknown account error."""
    settings = get_settings()
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "development"
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": "nonexistent_operator@example.com", "password": "AnyPassword123!"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "No account found with this email address."
        assert data["error_code"] == "USER_NOT_FOUND"
    finally:
        settings.ENVIRONMENT = original_env


def test_login_development_incorrect_password(client: TestClient, registered_user: User) -> None:
    """Verify development mode returns specific incorrect password error."""
    settings = get_settings()
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "development"
    try:
        response = client.post(
            "/api/v1/auth/login",
            json={"email": registered_user.email, "password": "WrongPassword999!"},
        )
        assert response.status_code == 401
        data = response.json()
        assert data["detail"] == "Incorrect password. Please try again."
        assert data["error_code"] == "INCORRECT_PASSWORD"
    finally:
        settings.ENVIRONMENT = original_env


def test_login_production_generic_error(client: TestClient, registered_user: User) -> None:
    """Verify production mode returns generic error to prevent enumeration."""
    settings = get_settings()
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "production"
    try:
        # Unknown email
        res1 = client.post(
            "/api/v1/auth/login",
            json={"email": "unknown_user@example.com", "password": "WrongPassword123!"},
        )
        assert res1.status_code == 401
        data1 = res1.json()
        assert data1["detail"] == "Invalid email or password."
        assert data1["error_code"] == "INVALID_CREDENTIALS"

        # Wrong password for existing user
        res2 = client.post(
            "/api/v1/auth/login",
            json={"email": registered_user.email, "password": "WrongPassword123!"},
        )
        assert res2.status_code == 401
        data2 = res2.json()
        assert data2["detail"] == "Invalid email or password."
        assert data2["error_code"] == "INVALID_CREDENTIALS"
    finally:
        settings.ENVIRONMENT = original_env


def test_forgot_password_unknown_email(client: TestClient) -> None:
    """Verify public forgot-password endpoint does not expose account non-existence."""
    response = client.post(
        "/api/v1/auth/forgot-password",
        json={"email": "does_not_exist@example.com"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "If an account exists" in data["message"]
    assert data["email_sent"] is False
    assert data["dev_reset_url"] is None


@pytest.mark.asyncio
async def test_forgot_password_existing_user(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify forgot-password generates hashed single-use token in DB."""
    settings = get_settings()
    original_env = settings.ENVIRONMENT
    settings.ENVIRONMENT = "development"
    try:
        response = client.post(
            "/api/v1/auth/forgot-password",
            json={"email": registered_user.email},
        )
        assert response.status_code == 200
        data = response.json()
        assert "If an account exists" in data["message"]

        # Verify token was created in DB
        tokens = (
            (
                await db_session.execute(
                    select(PasswordResetToken).where(
                        PasswordResetToken.user_id == registered_user.id
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(tokens) >= 1
        latest_token = tokens[-1]
        assert latest_token.is_used is False
        assert latest_token.expires_at > datetime.now(UTC)
    finally:
        settings.ENVIRONMENT = original_env


@pytest.mark.asyncio
async def test_validate_reset_token(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify reset token validation for valid, expired, and used tokens."""
    # 1. Invalid token
    res_invalid = client.get("/api/v1/auth/reset-password/validate?token=nonexistent_token_12345")
    assert res_invalid.status_code == 200
    assert res_invalid.json()["valid"] is False

    # 2. Valid token
    raw_token = secrets.token_urlsafe(32)
    token_record = PasswordResetToken(
        user_id=registered_user.id,
        token_hash=hash_token(raw_token),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        is_used=False,
    )
    db_session.add(token_record)
    await db_session.commit()

    res_valid = client.get(f"/api/v1/auth/reset-password/validate?token={raw_token}")
    assert res_valid.status_code == 200
    valid_data = res_valid.json()
    assert valid_data["valid"] is True
    assert valid_data["email"] == registered_user.email

    # 3. Used token
    token_record.is_used = True
    await db_session.commit()
    res_used = client.get(f"/api/v1/auth/reset-password/validate?token={raw_token}")
    assert res_used.status_code == 200
    assert res_used.json()["valid"] is False
    assert "already been used" in res_used.json()["reason"]

    # 4. Expired token
    raw_token_expired = secrets.token_urlsafe(32)
    expired_record = PasswordResetToken(
        user_id=registered_user.id,
        token_hash=hash_token(raw_token_expired),
        expires_at=datetime.now(UTC) - timedelta(minutes=5),
        is_used=False,
    )
    db_session.add(expired_record)
    await db_session.commit()

    res_expired = client.get(f"/api/v1/auth/reset-password/validate?token={raw_token_expired}")
    assert res_expired.status_code == 200
    assert res_expired.json()["valid"] is False
    assert "expired" in res_expired.json()["reason"]


@pytest.mark.asyncio
async def test_successful_password_reset_and_session_invalidation(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify password reset updates password hash, consumes token, and revokes sessions."""
    # Add an active refresh token session for user
    raw_refresh = secrets.token_urlsafe(32)
    refresh_rec = RefreshToken(
        user_id=registered_user.id,
        token_hash=hash_token(raw_refresh),
        family_id=registered_user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
        is_revoked=False,
    )
    db_session.add(refresh_rec)

    # Add active reset token
    raw_reset = secrets.token_urlsafe(32)
    reset_rec = PasswordResetToken(
        user_id=registered_user.id,
        token_hash=hash_token(raw_reset),
        expires_at=datetime.now(UTC) + timedelta(minutes=15),
        is_used=False,
    )
    db_session.add(reset_rec)
    await db_session.commit()

    # Perform password reset
    new_password = "BrandNewSecurePassword2026!"
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_reset, "password": new_password},
    )
    assert response.status_code == 200
    assert "reset successfully" in response.json()["message"]

    # Refresh user and token from DB
    await db_session.refresh(registered_user)
    await db_session.refresh(reset_rec)
    await db_session.refresh(refresh_rec)

    # 1. Password must verify with new password
    assert verify_password(new_password, registered_user.password_hash)
    # 2. Token must be marked used
    assert reset_rec.is_used is True
    # 3. All previous user sessions must be revoked
    assert refresh_rec.is_revoked is True

    # 4. Token cannot be reused
    reused_res = client.post(
        "/api/v1/auth/reset-password",
        json={"token": raw_reset, "password": "YetAnotherPassword123!"},
    )
    assert reused_res.status_code == 400
    assert reused_res.json()["error_code"] == "TOKEN_ALREADY_USED"


def test_reset_password_invalid_token(client: TestClient) -> None:
    """Verify reset password with invalid token returns 400 INVALID_TOKEN."""
    response = client.post(
        "/api/v1/auth/reset-password",
        json={"token": "totally_invalid_token_12345", "password": "ValidPassword123!"},
    )
    assert response.status_code == 400
    assert response.json()["error_code"] == "INVALID_TOKEN"
