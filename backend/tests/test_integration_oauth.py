"""Integration tests for OAuth 2.0 flows, PKCE, token refresh, and connection endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.integrations.security import (
    encrypt_oauth_token,
    generate_oauth_state,
)
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User

settings = get_settings()


def test_list_providers_endpoint(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify listing supported providers returns Google and Slack with capability metadata."""
    res = client.get("/api/v1/integrations/providers", headers=auth_headers)
    assert res.status_code == 200
    providers = res.json()
    provider_ids = [p["id"] for p in providers]
    assert "google" in provider_ids
    assert "slack" in provider_ids


def test_authorize_google_without_credentials_raises_503(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify attempting OAuth when credentials are missing returns 503."""
    with patch.object(settings, "GOOGLE_CLIENT_ID", None):
        res = client.get("/api/v1/integrations/google/authorize", headers=auth_headers)
        assert res.status_code == 503
        assert "not configured" in res.json()["detail"]


def test_authorize_google_generates_url_and_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify initiating Google OAuth returns valid URL with PKCE and signed state."""
    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-google-client-secret"),
    ):
        res = client.get(
            "/api/v1/integrations/google/authorize?service=gmail",
            headers=auth_headers,
        )
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "google"
        auth_url = data["authorization_url"]
        assert "accounts.google.com/o/oauth2/v2/auth" in auth_url
        assert "client_id=test-google-client-id" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "state=" in auth_url
        assert data["state"]


def test_authorize_slack_generates_url_and_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify initiating Slack OAuth returns valid URL with bot scopes and state."""
    with (
        patch.object(settings, "SLACK_CLIENT_ID", "test-slack-client-id"),
        patch.object(settings, "SLACK_CLIENT_SECRET", "test-slack-client-secret"),
    ):
        res = client.get("/api/v1/integrations/slack/authorize", headers=auth_headers)
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "slack"
        auth_url = data["authorization_url"]
        assert "slack.com/oauth/v2/authorize" in auth_url
        assert "client_id=test-slack-client-id" in auth_url
        assert "scope=" in auth_url


def test_google_oauth_callback_success(
    client: TestClient,
    registered_user: User,
) -> None:
    """Verify exchanging code in Google OAuth callback persists encrypted connection."""
    # Generate valid state bound to registered_user
    state = generate_oauth_state(
        user_id=registered_user.id,
        provider="google",
        service="gmail",
        code_verifier="test_code_verifier_12345",
    )

    mock_token_resp = {
        "access_token": "ya29.google-test-access-token",
        "refresh_token": "1//google-test-refresh-token",
        "expires_in": 3600,
        "scope": "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/gmail.send",
        "token_type": "Bearer",
    }
    mock_userinfo_resp = {
        "email": "flowpilot_user@gmail.com",
        "name": "FlowPilot Test User",
    }

    import httpx

    with (
        patch.object(settings, "GOOGLE_CLIENT_ID", "test-google-client-id"),
        patch.object(settings, "GOOGLE_CLIENT_SECRET", "test-google-client-secret"),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
        patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get,
    ):
        mock_post.return_value = httpx.Response(200, json=mock_token_resp)
        mock_get.return_value = httpx.Response(200, json=mock_userinfo_resp)

        res = client.get(
            f"/api/v1/integrations/google/callback?code=mock_auth_code&state={state}",
            headers={"Accept": "application/json"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "google"
        assert data["external_account_id"] == "flowpilot_user@gmail.com"
        assert data["status"] == "active"
        # Plaintext tokens must never be in API responses
        assert "access_token" not in data
        assert "refresh_token" not in data


def test_slack_oauth_callback_success(
    client: TestClient,
    registered_user: User,
) -> None:
    """Verify Slack OAuth callback stores workspace identity and encrypted bot token."""
    state = generate_oauth_state(
        user_id=registered_user.id,
        provider="slack",
        service="slack",
    )

    mock_slack_resp = {
        "ok": True,
        "access_token": "xoxb-mock-bot-token-12345",
        "token_type": "bot",
        "scope": "channels:read,chat:write,chat:write.public",
        "bot_user_id": "U0123BOT",
        "app_id": "A0123APP",
        "team": {
            "id": "T09876543",
            "name": "Acme Engineering",
        },
    }

    import httpx

    with (
        patch.object(settings, "SLACK_CLIENT_ID", "test-slack-client-id"),
        patch.object(settings, "SLACK_CLIENT_SECRET", "test-slack-client-secret"),
        patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = httpx.Response(200, json=mock_slack_resp)

        res = client.get(
            f"/api/v1/integrations/slack/callback?code=mock_slack_code&state={state}",
            headers={"Accept": "application/json"},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["provider"] == "slack"
        assert data["external_account_id"] == "T09876543"
        assert data["external_account_name"] == "Acme Engineering"
        assert data["status"] == "active"


def test_oauth_callback_user_denied_raises_400(client: TestClient) -> None:
    """Verify that user-denied authorization error in callback raises 400."""
    res = client.get("/api/v1/integrations/google/callback?error=access_denied")
    assert res.status_code == 400
    assert "access_denied" in res.json()["detail"]


def test_oauth_callback_invalid_state_csrf_rejected(client: TestClient) -> None:
    """Verify that an altered state signature raises 400 Bad Request."""
    res = client.get("/api/v1/integrations/google/callback?code=mock&state=invalid.signature")
    assert res.status_code == 400
    assert "verification failed" in res.json()["detail"]


@pytest.mark.asyncio
async def test_user_connections_isolation(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot view or access User A's integration connections."""
    conn_a = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="gmail",
        external_account_id="user_a@gmail.com",
        encrypted_access_token=encrypt_oauth_token("mock_token_a"),
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn_a)
    await db_session.commit()

    # User A can view connection
    res_a = client.get(f"/api/v1/integrations/{conn_a.id}", headers=auth_headers)
    assert res_a.status_code == 200
    assert res_a.json()["external_account_id"] == "user_a@gmail.com"

    # User B receives 404 (ownership denied)
    res_b = client.get(f"/api/v1/integrations/{conn_a.id}", headers=second_auth_headers)
    assert res_b.status_code == 404


@pytest.mark.asyncio
async def test_disconnect_and_delete_connection(
    client: TestClient,
    db_session: AsyncSession,
    registered_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify disconnecting a connection removes it and revokes token."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="slack",
        external_account_id="T012345",
        encrypted_access_token=encrypt_oauth_token("xoxb-token"),
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    await db_session.commit()

    with patch(
        "flowpilot.integrations.slack.oauth.SlackOAuth.revoke_token",
        new_callable=AsyncMock,
    ) as mock_revoke:
        mock_revoke.return_value = True
        del_res = client.delete(f"/api/v1/integrations/{conn.id}", headers=auth_headers)
        assert del_res.status_code == 204
        assert mock_revoke.called

    # Connection must now be gone
    get_res = client.get(f"/api/v1/integrations/{conn.id}", headers=auth_headers)
    assert get_res.status_code == 404
