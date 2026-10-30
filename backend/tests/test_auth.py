"""Comprehensive automated tests for authentication and session lifecycle."""

from datetime import timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.security import (
    create_access_token,
    decode_token,
    hash_token,
    verify_password,
)
from flowpilot.models.refresh_token import RefreshToken
from flowpilot.models.user import User


def test_successful_user_registration(client: TestClient) -> None:
    """1. Verify successful user registration returns HTTP 201 with public profile."""
    payload = {
        "email": "newuser@example.com",
        "password": "SecurePassword123!",
        "full_name": "New Pilot",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == "newuser@example.com"
    assert data["full_name"] == "New Pilot"
    assert data["is_active"] is True
    assert "id" in data
    assert "password" not in data
    assert "password_hash" not in data


def test_duplicate_registration_rejection(client: TestClient, registered_user: User) -> None:
    """2. Verify duplicate registration attempts are rejected with HTTP 409 Conflict."""
    payload = {
        "email": registered_user.email,
        "password": "AnotherPassword123!",
        "full_name": "Duplicate Attempt",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


def test_valid_login(client: TestClient, registered_user: User) -> None:
    """3. Verify valid login returns HTTP 200, access token, and sets HttpOnly cookie."""
    payload = {
        "email": registered_user.email,
        "password": "Password123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] > 0

    # Verify HttpOnly refresh cookie is set
    settings = get_settings()
    assert settings.AUTH_COOKIE_NAME in response.cookies
    cookie = response.cookies[settings.AUTH_COOKIE_NAME]
    assert len(cookie) > 0


def test_invalid_password_rejection(client: TestClient, registered_user: User) -> None:
    """4. Verify invalid password returns HTTP 401 without revealing internal details."""
    payload = {
        "email": registered_user.email,
        "password": "WrongPassword999!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    detail = response.json()["detail"].lower()
    assert "invalid email or password" in detail or "incorrect password" in detail


def test_unknown_account_rejection(client: TestClient) -> None:
    """5. Verify unknown email returns HTTP 401 without leaking user existence."""
    payload = {
        "email": "nonexistent@example.com",
        "password": "AnyPassword123!",
    }
    response = client.post("/api/v1/auth/login", json=payload)
    assert response.status_code == 401
    detail = response.json()["detail"].lower()
    assert "invalid email or password" in detail or "no account found" in detail


async def test_password_hashing(client: TestClient, db_session: AsyncSession) -> None:
    """6. Verify passwords are encrypted using Argon2 and plaintext is never stored."""
    email = "argon2user@example.com"
    plain_password = "StrictPassword123!"
    response = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": plain_password},
    )
    assert response.status_code == 201

    result = await db_session.execute(select(User).where(User.email == email))
    db_user = result.scalar_one()

    # Must start with standard Argon2id prefix
    assert db_user.password_hash.startswith("$argon2id$")
    assert db_user.password_hash != plain_password
    assert verify_password(plain_password, db_user.password_hash) is True


def test_access_token_generation_and_claims(registered_user: User) -> None:
    """7. Verify generated access tokens contain correct claims and subject."""
    token = create_access_token(registered_user.id)
    payload = decode_token(token, expected_type="access")

    assert payload["sub"] == str(registered_user.id)
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload
    assert "jti" in payload


def test_expired_and_malformed_tokens(client: TestClient, registered_user: User) -> None:
    """8. Verify expired and malformed tokens return HTTP 401."""
    # Test malformed token
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": "Bearer this.is.an.invalid.token"},
    )
    assert response.status_code == 401

    # Test expired token
    expired_token = create_access_token(
        registered_user.id,
        expires_delta=timedelta(seconds=-10),
    )
    response_expired = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response_expired.status_code == 401
    assert "expired" in response_expired.json()["detail"].lower()


async def test_refresh_token_rotation(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """9. Verify refresh token rotation revokes old token and issues a new valid token."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    assert login_res.status_code == 200
    settings = get_settings()
    first_cookie = login_res.cookies[settings.AUTH_COOKIE_NAME]

    # Rotate token
    rotate_res = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={first_cookie}"},
    )
    assert rotate_res.status_code == 200
    rotate_data = rotate_res.json()
    assert "access_token" in rotate_data

    second_cookie = rotate_res.cookies[settings.AUTH_COOKIE_NAME]
    assert second_cookie != first_cookie

    # Verify first token is marked revoked in DB
    first_hash = hash_token(first_cookie)
    result = await db_session.execute(
        select(RefreshToken).where(RefreshToken.token_hash == first_hash)
    )
    first_record = result.scalar_one()
    assert first_record.is_revoked is True


def test_revoked_token_rejection(client: TestClient, registered_user: User) -> None:
    """10. Verify attempting to use an already revoked token is rejected."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    settings = get_settings()
    token = login_res.cookies[settings.AUTH_COOKIE_NAME]

    # First rotation succeeds
    r1 = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={token}"},
    )
    assert r1.status_code == 200

    # Second rotation with original revoked token is rejected
    r2 = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={token}"},
    )
    assert r2.status_code == 401


async def test_refresh_token_replay_rejection(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """11. Verify replay attack revokes the entire token family."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    settings = get_settings()
    first_token = login_res.cookies[settings.AUTH_COOKIE_NAME]

    # Legitimate client rotates token
    legit_res = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={first_token}"},
    )
    assert legit_res.status_code == 200
    second_token = legit_res.cookies[settings.AUTH_COOKIE_NAME]

    # Attacker replays first_token
    replay_res = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={first_token}"},
    )
    assert replay_res.status_code == 401

    # Legitimate second_token should now also be rejected because family was revoked
    subsequent_res = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={second_token}"},
    )
    assert subsequent_res.status_code == 401


def test_successful_logout(client: TestClient, registered_user: User) -> None:
    """12. Verify logout revokes the refresh session and clears the cookie."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    settings = get_settings()
    token = login_res.cookies[settings.AUTH_COOKIE_NAME]

    logout_res = client.post(
        "/api/v1/auth/logout",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={token}"},
    )
    assert logout_res.status_code == 200
    assert logout_res.json()["message"] == "Successfully logged out."

    # Verify refresh attempt fails after logout
    refresh_res = client.post(
        "/api/v1/auth/refresh",
        headers={"Cookie": f"{settings.AUTH_COOKIE_NAME}={token}"},
    )
    assert refresh_res.status_code == 401


def test_unauthorized_endpoint_access(client: TestClient) -> None:
    """13. Verify protected endpoint rejects requests lacking valid Bearer credentials."""
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401


def test_inactive_user_rejection(client: TestClient, inactive_user: User) -> None:
    """14. Verify inactive users cannot log in or access protected resources."""
    # Attempt login
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": inactive_user.email, "password": "Password123!"},
    )
    assert login_res.status_code == 403
    assert "inactive" in login_res.json()["detail"].lower()

    # Attempt accessing protected endpoint with forged token
    token = create_access_token(inactive_user.id)
    profile_res = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert profile_res.status_code == 403
    assert "inactive" in profile_res.json()["detail"].lower()
