"""Automated tests for user profile management and data isolation."""

import uuid

from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.security import create_access_token, hash_password
from flowpilot.models.user import User


def test_authenticated_profile_retrieval(client: TestClient, registered_user: User) -> None:
    """Verify an authenticated user can retrieve their profile with accurate details."""
    token = create_access_token(registered_user.id)
    response = client.get(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(registered_user.id)
    assert data["email"] == registered_user.email
    assert data["full_name"] == registered_user.full_name
    assert data["is_active"] is True
    assert "password" not in data
    assert "password_hash" not in data


def test_unauthorized_profile_access(client: TestClient) -> None:
    """Verify requesting the profile endpoint without an authorization header is rejected."""
    response = client.get("/api/v1/users/me")
    assert response.status_code == 401
    assert "WWW-Authenticate" in response.headers


def test_profile_update_full_name(client: TestClient, registered_user: User) -> None:
    """Verify an authenticated user can update their display name."""
    token = create_access_token(registered_user.id)
    response = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"full_name": "Updated Navigator"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["full_name"] == "Updated Navigator"
    assert data["email"] == registered_user.email
    assert "password" not in data
    assert "password_hash" not in data


async def test_profile_update_password(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify an authenticated user can update their password and login with the new password."""
    token = create_access_token(registered_user.id)
    new_password = "BrandNewPassword456!"
    response = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": new_password},
    )
    assert response.status_code == 200

    # Verify old password no longer works
    login_old = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": "Password123!"},
    )
    assert login_old.status_code == 401

    # Verify new password works
    login_new = client.post(
        "/api/v1/auth/login",
        json={"email": registered_user.email, "password": new_password},
    )
    assert login_new.status_code == 200


async def test_user_data_isolation(
    client: TestClient,
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify strict tenant and user profile isolation between distinct users."""
    # Create second independent user
    other_user = User(
        id=uuid.uuid4(),
        email="seconduser@example.com",
        full_name="Second Pilot",
        password_hash=hash_password("SecretPass123!"),
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    # User 1 accesses /me
    token_1 = create_access_token(registered_user.id)
    res_1 = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_1}"})
    assert res_1.status_code == 200
    assert res_1.json()["id"] == str(registered_user.id)
    assert res_1.json()["email"] == registered_user.email

    # User 2 accesses /me
    token_2 = create_access_token(other_user.id)
    res_2 = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_2}"})
    assert res_2.status_code == 200
    assert res_2.json()["id"] == str(other_user.id)
    assert res_2.json()["email"] == other_user.email

    # User 1 updates their profile; User 2 remains completely unchanged
    update_res = client.patch(
        "/api/v1/users/me",
        headers={"Authorization": f"Bearer {token_1}"},
        json={"full_name": "Solo Pilot"},
    )
    assert update_res.status_code == 200

    # User 2 profile remains identical
    res_2_after = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token_2}"})
    assert res_2_after.json()["full_name"] == "Second Pilot"
    assert res_2_after.json()["id"] == str(other_user.id)
