"""Automated tests for App Connections: custom credentials, multi-user isolation,
setup guides, safe token encryption, and default connection management.
"""

import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.integrations.security import decrypt_oauth_token, encrypt_oauth_token
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User

settings = get_settings()


def test_app_connections_overview_initial_state(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify App Connections overview returns all 4 providers in valid initial state."""
    res = client.get("/api/v1/integrations/overview", headers=auth_headers)
    assert res.status_code == 200
    overview = res.json()
    assert len(overview) == 4

    ids = [item["id"] for item in overview]
    assert "gmail" in ids
    assert "sheets" in ids
    assert "slack" in ids
    assert "whatsapp" in ids

    for item in overview:
        assert "status" in item
        assert "supported_methods" in item
        assert item["has_access_token"] is False
        assert "secret" not in item


def test_provider_setup_guides_endpoint(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify setup guides return official portal links, steps, and copyable callback URLs."""
    res = client.get("/api/v1/integrations/guides", headers=auth_headers)
    assert res.status_code == 200
    guides = res.json()
    assert len(guides) == 3

    guide_map = {g["provider"]: g for g in guides}
    assert "google" in guide_map
    assert "slack" in guide_map
    assert "whatsapp" in guide_map

    # Check Google guide details
    google_guide = guide_map["google"]
    assert "console.cloud.google.com" in google_guide["portal_url"]
    assert "/api/v1/integrations/google/callback" in google_guide["callback_url"]
    assert len(google_guide["steps"]) >= 4

    # Check specific provider guide endpoint
    single_res = client.get("/api/v1/integrations/guides/slack", headers=auth_headers)
    assert single_res.status_code == 200
    assert single_res.json()["name"] == "Slack"
    assert "api.slack.com/apps" in single_res.json()["portal_url"]


def test_save_custom_google_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify user can save custom Google credentials and secret is encrypted."""
    payload = {
        "provider": "google",
        "service": "gmail",
        "client_id": "987654321-custom.apps.googleusercontent.com",
        "client_secret": "GOCSPX-supersecretkey12345",
        "is_default": True,
    }
    res = client.post("/api/v1/integrations/credentials", json=payload, headers=auth_headers)
    assert res.status_code == 200
    data = res.json()

    assert data["provider"] == "google"
    assert data["config_method"] == "custom_credentials"
    assert data["client_id"] == "987654321-custom.apps.googleusercontent.com"
    assert data["has_client_secret"] is True
    # Secret must never be returned in plaintext
    assert "client_secret" not in data
    assert "GOCSPX" not in str(data)
    assert data["status"] in ("authorization_required", "configured")


def test_save_custom_whatsapp_credentials_probes_sender(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify saving WhatsApp credentials immediately probes sender validity."""
    mock_details = {
        "verified_name": "Acme Support Line",
        "display_phone_number": "+1 555 0199",
        "status": "ACTIVE",
    }

    with patch(
        "flowpilot.integrations.whatsapp.client.WhatsAppClient.get_phone_number_details",
        new=AsyncMock(return_value=mock_details),
    ):
        payload = {
            "provider": "whatsapp",
            "phone_number_id": "104928301928471",
            "access_token": "EAAG_whatsapp_secret_system_token_xyz",
            "business_account_id": "992837461029384",
            "is_default": True,
        }
        res = client.post("/api/v1/integrations/credentials", json=payload, headers=auth_headers)
        assert res.status_code == 200
        data = res.json()

        assert data["provider"] == "whatsapp"
        assert data["status"] == "active"
        assert data["has_access_token"] is True
        assert "Acme Support Line" in data["external_account_name"]
        # Secret token must not be in response
        assert "EAAG" not in str(data)


@pytest.mark.asyncio
async def test_user_isolation_between_accounts(
    client: TestClient,
    auth_headers: dict[str, str],
    second_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify strict user isolation: User A cannot view, test, or modify User B's connection."""
    # Create connection belonging to User B (second_user)
    b_conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=second_user.id,
        provider="slack",
        service="slack",
        config_method="custom_credentials",
        client_id="user_b_slack_client_id",
        encrypted_client_secret=encrypt_oauth_token("user_b_slack_secret"),
        external_account_name="User B Workspace",
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(b_conn)
    await db_session.commit()

    # User A tries to get User B's connection -> must 404
    get_res = client.get(f"/api/v1/integrations/{b_conn.id}", headers=auth_headers)
    assert get_res.status_code == 404

    # User A tries to test User B's connection -> must 404
    test_res = client.post(f"/api/v1/integrations/{b_conn.id}/test", headers=auth_headers)
    assert test_res.status_code == 404

    # User A tries to set User B's connection as default -> must 404
    default_res = client.post(f"/api/v1/integrations/{b_conn.id}/default", headers=auth_headers)
    assert default_res.status_code == 404

    # User A tries to disconnect User B's connection -> must 404
    del_res = client.delete(f"/api/v1/integrations/{b_conn.id}", headers=auth_headers)
    assert del_res.status_code == 404


def test_overview_reflects_saved_credentials(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify App Connections overview cards reflect saved custom credentials accurately."""
    # Save custom Slack credentials
    payload = {
        "provider": "slack",
        "service": "slack",
        "client_id": "11223344.55667788",
        "client_secret": "slack_custom_app_secret_abc123",
        "is_default": True,
    }
    client.post("/api/v1/integrations/credentials", json=payload, headers=auth_headers)

    res = client.get("/api/v1/integrations/overview", headers=auth_headers)
    assert res.status_code == 200
    overview = res.json()
    slack_card = next(c for c in overview if c["id"] == "slack")

    assert slack_card["has_credentials"] is True
    assert slack_card["status"] == "authorization_required"
    assert "112233" in slack_card["client_id_preview"]
    assert "secret" not in str(slack_card["client_id_preview"])


@pytest.mark.asyncio
async def test_tokens_are_encrypted_at_rest(
    client: TestClient,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """Verify secrets and tokens are encrypted with MultiFernet before database storage."""
    secret_text = "ultra_sensitive_meta_token_value_99999"
    payload = {
        "provider": "whatsapp",
        "phone_number_id": "112233445566",
        "access_token": secret_text,
    }
    with patch(
        "flowpilot.integrations.whatsapp.client.WhatsAppClient.get_phone_number_details",
        new=AsyncMock(return_value={"status": "ACTIVE"}),
    ):
        res = client.post("/api/v1/integrations/credentials", json=payload, headers=auth_headers)
        assert res.status_code == 200
        conn_id = uuid.UUID(res.json()["id"])

    # Inspect direct database column
    db_conn = await db_session.get(IntegrationConnection, conn_id)
    assert db_conn is not None
    assert db_conn.encrypted_access_token is not None
    # Ciphertext must differ completely from plaintext secret
    assert db_conn.encrypted_access_token != secret_text
    assert secret_text not in db_conn.encrypted_access_token
    # MultiFernet decryption recovers original plaintext
    assert decrypt_oauth_token(db_conn.encrypted_access_token) == secret_text
