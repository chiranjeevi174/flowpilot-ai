"""Tests for inbound integration webhooks, Slack signature verification, and deduplication."""

import json
import time
from unittest.mock import patch

from httpx import ASGITransport, AsyncClient
from slack_sdk.signature import SignatureVerifier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.main import app
from flowpilot.models.integration_event import IntegrationEvent, IntegrationEventStatus

TEST_SIGNING_SECRET = "test_slack_signing_secret_12345"
PATCH_SECRET = "flowpilot.integrations.slack.events.settings.SLACK_SIGNING_SECRET"


def _generate_slack_headers(body_str: str, timestamp: int | None = None) -> dict[str, str]:
    """Generate valid Slack signature and timestamp headers for testing."""
    ts = str(timestamp if timestamp is not None else int(time.time()))
    verifier = SignatureVerifier(signing_secret=TEST_SIGNING_SECRET)
    sig = verifier.generate_signature(timestamp=ts, body=body_str)
    return {
        "X-Slack-Request-Timestamp": ts,
        "X-Slack-Signature": sig,
        "Content-Type": "application/json",
    }


async def test_slack_webhook_url_verification_challenge():
    """Verify that Slack URL verification challenges are answered correctly."""
    challenge_payload = {
        "type": "url_verification",
        "token": "verification_token",
        "challenge": "flowpilot_challenge_code_987",
    }
    body_str = json.dumps(challenge_payload)
    headers = _generate_slack_headers(body_str)

    with patch(PATCH_SECRET, TEST_SIGNING_SECRET):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )

    assert response.status_code == 200
    data = response.json()
    assert data["challenge"] == "flowpilot_challenge_code_987"


async def test_slack_webhook_valid_event_enqueued(db_session: AsyncSession):
    """Verify that authentic Slack events are verified, recorded, and accepted."""
    event_payload = {
        "type": "event_callback",
        "event_id": "Ev_test_123456",
        "team_id": "T01234567",
        "event": {
            "type": "app_mention",
            "user": "U123456",
            "text": "<@U0123> run analysis on sales report",
            "channel": "C12345678",
            "event_ts": "1600000000.000200",
        },
    }
    body_str = json.dumps(event_payload)
    headers = _generate_slack_headers(body_str)

    with patch(PATCH_SECRET, TEST_SIGNING_SECRET):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["event_id"] == "Ev_test_123456"
    assert data["status"] == "received"

    # Verify event stored in database
    stmt = select(IntegrationEvent).where(IntegrationEvent.external_event_id == "Ev_test_123456")
    event_record = await db_session.scalar(stmt)
    assert event_record is not None
    assert event_record.provider == "slack"
    assert event_record.event_type == "app_mention"
    assert event_record.status == IntegrationEventStatus.RECEIVED


async def test_slack_webhook_duplicate_event_deduplication(db_session: AsyncSession):
    """Verify that duplicate Slack event deliveries are safely ignored."""
    event_payload = {
        "type": "event_callback",
        "event_id": "Ev_duplicate_test_789",
        "team_id": "T01234567",
        "event": {
            "type": "message",
            "user": "U999",
            "text": "duplicate test",
            "channel": "C999",
        },
    }
    body_str = json.dumps(event_payload)
    headers = _generate_slack_headers(body_str)

    with patch(PATCH_SECRET, TEST_SIGNING_SECRET):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            # First delivery
            resp1 = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )
            assert resp1.status_code == 200
            assert resp1.json()["status"] == "received"

            # Duplicate delivery
            resp2 = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )
            assert resp2.status_code == 200
            assert resp2.json()["status"] == "ignored_duplicate"


async def test_slack_webhook_invalid_signature_rejected():
    """Verify that webhooks with invalid or forged signatures are rejected with 401."""
    event_payload = {"type": "event_callback", "event_id": "Ev_forged"}
    body_str = json.dumps(event_payload)
    headers = {
        "X-Slack-Request-Timestamp": str(int(time.time())),
        "X-Slack-Signature": "v0=invalid_hmac_hash_000000000000000000000000",
        "Content-Type": "application/json",
    }

    with patch(PATCH_SECRET, TEST_SIGNING_SECRET):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )

    assert response.status_code == 401
    assert "Invalid Slack signature" in response.json()["detail"]


async def test_slack_webhook_expired_timestamp_rejected():
    """Verify that requests with timestamps older than 5 minutes are rejected."""
    event_payload = {"type": "event_callback", "event_id": "Ev_expired"}
    body_str = json.dumps(event_payload)
    # 10 minutes ago
    expired_ts = int(time.time()) - 600
    headers = _generate_slack_headers(body_str, timestamp=expired_ts)

    with patch(PATCH_SECRET, TEST_SIGNING_SECRET):
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/webhooks/slack",
                content=body_str.encode("utf-8"),
                headers=headers,
            )

    assert response.status_code == 401
    assert "timestamp is expired" in response.json()["detail"]
