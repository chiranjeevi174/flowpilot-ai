"""Tests for Slack client, messaging, webhook signature verification, and deduplication."""

import hashlib
import hmac
import json
import time
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.integrations.oauth import OAuthScopeError
from flowpilot.integrations.security import encrypt_oauth_token
from flowpilot.integrations.slack.client import SlackClient
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User

settings = get_settings()


@pytest.fixture
async def slack_connection(
    db_session: AsyncSession,
    registered_user: User,
) -> IntegrationConnection:
    """Create an active Slack integration connection with bot token."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="slack",
        service="slack",
        external_account_id="T0123TEAM",
        external_account_name="Test Workspace",
        encrypted_access_token=encrypt_oauth_token("xoxb-mock-slack-token"),
        granted_scopes=["channels:read", "groups:read", "chat:write", "chat:write.public"],
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


@pytest.mark.asyncio
async def test_slack_list_channels(
    db_session: AsyncSession,
    slack_connection: IntegrationConnection,
) -> None:
    """Verify listing Slack channels via AsyncWebClient returns formatted channels."""
    mock_conversations = {
        "ok": True,
        "channels": [
            {"id": "C01", "name": "general", "is_private": False, "num_members": 15},
            {"id": "C02", "name": "random", "is_private": False, "num_members": 10},
        ],
    }

    with patch(
        "slack_sdk.web.async_client.AsyncWebClient.conversations_list",
        new_callable=AsyncMock,
    ) as mock_list:
        mock_list.return_value = mock_conversations

        channels = await SlackClient.list_channels(db_session, slack_connection)
        assert len(channels) == 2
        assert channels[0]["name"] == "general"
        assert channels[0]["id"] == "C01"


@pytest.mark.asyncio
async def test_slack_list_channels_missing_scope(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify listing channels without channels:read scope raises OAuthScopeError."""
    narrow_conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="slack",
        encrypted_access_token=encrypt_oauth_token("mock_token"),
        granted_scopes=["chat:write"],  # channels:read is missing
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(narrow_conn)
    await db_session.commit()

    with pytest.raises(OAuthScopeError, match="Missing required Slack scope"):
        await SlackClient.list_channels(db_session, narrow_conn)


@pytest.mark.asyncio
async def test_slack_prepare_message() -> None:
    """Verify prepare_message structures payload without side-effect."""
    res = await SlackClient.prepare_message(
        channel="C0123",
        text="Status update from FlowPilot.",
    )
    assert res["status"] == "prepared"
    assert res["channel"] == "C0123"
    assert res["approval_required"] is True


@pytest.mark.asyncio
async def test_slack_send_message_success(
    db_session: AsyncSession,
    slack_connection: IntegrationConnection,
) -> None:
    """Verify sending an approved Slack message invokes chat_postMessage."""
    mock_post_resp = {
        "ok": True,
        "channel": "C0123",
        "ts": "1729780000.000100",
        "message": {"text": "Workflow completed."},
    }

    with patch(
        "slack_sdk.web.async_client.AsyncWebClient.chat_postMessage",
        new_callable=AsyncMock,
    ) as mock_post:
        mock_post.return_value = mock_post_resp

        res = await SlackClient.send_message(
            db=db_session,
            connection=slack_connection,
            channel="C0123",
            text="Workflow completed.",
        )

        assert res["status"] == "sent"
        assert res["ts"] == "1729780000.000100"
        assert mock_post.called


def _compute_slack_signature(secret: str, timestamp: str, body: bytes) -> str:
    """Compute standard Slack v0 signature."""
    sig_basestring = f"v0:{timestamp}:".encode() + body
    computed = hmac.new(secret.encode(), sig_basestring, hashlib.sha256).hexdigest()
    return f"v0={computed}"


def test_slack_webhook_url_verification_challenge(client: TestClient) -> None:
    """Verify Slack URL verification challenge returns challenge payload."""
    secret = "test-signing-secret"
    payload = {
        "type": "url_verification",
        "token": "verification-token",
        "challenge": "flowpilot_challenge_string_12345",
    }
    raw_body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _compute_slack_signature(secret, ts, raw_body)

    with patch.object(settings, "SLACK_SIGNING_SECRET", secret):
        res = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": sig,
                "X-Slack-Request-Timestamp": ts,
            },
        )
        assert res.status_code == 200
        assert res.json() == {"challenge": "flowpilot_challenge_string_12345"}


def test_slack_webhook_invalid_signature_rejected(client: TestClient) -> None:
    """Verify invalid or forged Slack signature is rejected with 401 Unauthorized."""
    secret = "test-signing-secret"
    payload = {"type": "event_callback", "event": {"type": "app_mention"}}
    raw_body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))

    with patch.object(settings, "SLACK_SIGNING_SECRET", secret):
        res = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": "v0=invalid_signature_hash_abcdef",
                "X-Slack-Request-Timestamp": ts,
            },
        )
        assert res.status_code == 401


def test_slack_webhook_expired_timestamp_rejected(client: TestClient) -> None:
    """Verify webhook with timestamp older than 300s is rejected to prevent replay attacks."""
    secret = "test-signing-secret"
    payload = {"type": "event_callback", "event": {"type": "app_mention"}}
    raw_body = json.dumps(payload).encode("utf-8")
    # Expired timestamp (10 minutes ago)
    old_ts = str(int(time.time()) - 600)
    sig = _compute_slack_signature(secret, old_ts, raw_body)

    with patch.object(settings, "SLACK_SIGNING_SECRET", secret):
        res = client.post(
            "/api/v1/webhooks/slack",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Slack-Signature": sig,
                "X-Slack-Request-Timestamp": old_ts,
            },
        )
        assert res.status_code == 401


def test_slack_webhook_deduplication(client: TestClient) -> None:
    """Verify duplicate deliveries of the same external_event_id are acknowledged but ignored."""
    secret = "test-signing-secret"
    event_id = f"Ev_dedup_{uuid.uuid4().hex[:8]}"
    payload = {
        "event_id": event_id,
        "type": "event_callback",
        "team_id": "T01234",
        "event": {
            "type": "app_mention",
            "channel": "C01",
            "user": "U01",
            "text": "<@U0123> run monthly report",
        },
    }
    raw_body = json.dumps(payload).encode("utf-8")
    ts = str(int(time.time()))
    sig = _compute_slack_signature(secret, ts, raw_body)

    headers = {
        "Content-Type": "application/json",
        "X-Slack-Signature": sig,
        "X-Slack-Request-Timestamp": ts,
    }

    with patch.object(settings, "SLACK_SIGNING_SECRET", secret):
        # 1. First delivery succeeds
        res1 = client.post("/api/v1/webhooks/slack", content=raw_body, headers=headers)
        assert res1.status_code == 200
        assert res1.json()["status"] == "received"

        # 2. Replayed delivery is detected as duplicate and safely ignored
        res2 = client.post("/api/v1/webhooks/slack", content=raw_body, headers=headers)
        assert res2.status_code == 200
        assert res2.json()["status"] == "ignored_duplicate"
