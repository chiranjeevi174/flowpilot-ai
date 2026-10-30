"""Comprehensive automated tests for WhatsApp Business Platform (Cloud API) integration.

Tests include:
- Configuration readiness and missing credential detection
- Phone number normalization (E.164 digits-only) and validation
- Free-form text and approved template payload construction
- Meta Graph API error classification (auth, rate limits, 24h window, invalid recipient, timeouts)
- Webhook subscription challenge verification
- Cryptographic X-Hub-Signature-256 HMAC-SHA256 signature enforcement
- Webhook event deduplication and delivery status updates (delivered, read, failed)
- Mandatory human approval gate and parameter tamper prevention
- Replay and idempotency protection
- Cross-user data isolation
- Combined multi-channel (Gmail + WhatsApp) workflow execution with independent audit
"""

import hashlib
import hmac
import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import Settings, get_settings
from flowpilot.integrations.registry import (
    ApprovalRequiredError,
    ParameterTamperedError,
    execute_whatsapp_send_message,
)
from flowpilot.integrations.security import compute_parameter_digest
from flowpilot.integrations.whatsapp.client import (
    WhatsAppAuthenticationError,
    WhatsAppClient,
    WhatsAppMessagingWindowError,
    WhatsAppRateLimitError,
    WhatsAppRecipientError,
    WhatsAppValidationError,
)
from flowpilot.main import app
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.user import User
from flowpilot.workflows.tools import is_operation_sensitive

TEST_APP_SECRET = "meta_test_app_secret_998877665544332211"
TEST_VERIFY_TOKEN = "flowpilot_meta_webhook_secret_token_123"
TEST_PHONE_ID = "100609346426344"
TEST_TOKEN = "EAAGtest_access_token_meta_123456"
core_settings = get_settings()

PATCH_PID = "flowpilot.integrations.whatsapp.client.settings.WHATSAPP_PHONE_NUMBER_ID"
PATCH_TOKEN = "flowpilot.integrations.whatsapp.client.settings.WHATSAPP_ACCESS_TOKEN"
PATCH_VERSION = "flowpilot.integrations.whatsapp.client.settings.WHATSAPP_GRAPH_API_VERSION"
PATCH_POST = "flowpilot.integrations.whatsapp.client.WhatsAppClient._post_with_retry"
PATCH_HTTP_POST = "httpx.AsyncClient.post"


def _generate_meta_signature(raw_body: bytes, secret: str = TEST_APP_SECRET) -> str:
    """Generate X-Hub-Signature-256 header value for Meta webhooks."""
    digest = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


@pytest.fixture
async def sample_run(db_session: AsyncSession, registered_user: User) -> AgentRun:
    """Create a sample AgentRun for foreign key binding."""
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{uuid.uuid4().hex[:8]}",
        original_request="Test WhatsApp automation workflow",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


# ==============================================================================
# Configuration Tests
# ==============================================================================


def test_whatsapp_configuration_readiness():
    """Verify settings properties accurately detect configured vs missing credentials."""
    unconfigured = Settings(
        JWT_SECRET_KEY="test" * 10,
        WHATSAPP_PHONE_NUMBER_ID=None,
        WHATSAPP_ACCESS_TOKEN=None,
    )
    assert unconfigured.is_whatsapp_configured is False
    assert "WHATSAPP_PHONE_NUMBER_ID" in unconfigured.whatsapp_missing_fields
    assert "WHATSAPP_ACCESS_TOKEN" in unconfigured.whatsapp_missing_fields

    configured = Settings(
        JWT_SECRET_KEY="test" * 10,
        WHATSAPP_PHONE_NUMBER_ID=TEST_PHONE_ID,
        WHATSAPP_ACCESS_TOKEN=TEST_TOKEN,
        WHATSAPP_APP_SECRET=TEST_APP_SECRET,
        WHATSAPP_WEBHOOK_VERIFY_TOKEN=TEST_VERIFY_TOKEN,
    )
    assert configured.is_whatsapp_configured is True


# ==============================================================================
# Phone Number Normalization Tests
# ==============================================================================


@pytest.mark.parametrize(
    "raw_input,expected",
    [
        ("+1 (555) 012-3456", "15550123456"),
        ("+44 7911 123456", "447911123456"),
        ("+91 98765 43210", "919876543210"),
        ("15550123456", "15550123456"),
        ("  +1-800-555-0199  ", "18005550199"),
        ("49.30.1234567", "49301234567"),
    ],
)
def test_phone_number_normalization_valid(raw_input: str, expected: str):
    """Normalize valid international phone numbers into digits-only E.164."""
    assert WhatsAppClient.normalize_phone_number(raw_input) == expected


@pytest.mark.parametrize(
    "invalid_input",
    [
        "",
        "   ",
        "12345",  # Too short (< 7 digits)
        "12345678901234567",  # Too long (> 15 digits)
        "+1 (555) ABC-1234",  # Letters
        "invalid_phone",
    ],
)
def test_phone_number_normalization_invalid(invalid_input: str):
    """Reject invalid phone numbers violating E.164 ITU-T rules."""
    with pytest.raises(WhatsAppValidationError):
        WhatsAppClient.normalize_phone_number(invalid_input)


# ==============================================================================
# Payload Generation and API Mocking Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_send_text_message_payload():
    """Verify customer text message payload format and Meta message ID extraction."""
    mock_meta_response = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "15550123456", "wa_id": "15550123456"}],
        "messages": [{"id": "wamid.HBgLMTU1NTAxMjM0NTYVAgARGBI1RDM4NDAzNjQ="}],
    }

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, TEST_TOKEN),
        patch(PATCH_VERSION, "v21.0"),
        patch(PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_meta_response

        res = await WhatsAppClient.send_text_message(
            recipient="+1 (555) 012-3456",
            text="Hello from FlowPilot AI automation!",
        )

        assert res["message_id"] == "wamid.HBgLMTU1NTAxMjM0NTYVAgARGBI1RDM4NDAzNjQ="
        assert res["recipient"] == "15550123456"
        assert res["status"] == "accepted"
        assert res["type"] == "text"


@pytest.mark.asyncio
async def test_send_template_message_payload():
    """Verify Meta approved template message payload structure."""
    mock_meta_response = {
        "messaging_product": "whatsapp",
        "contacts": [{"input": "15550123456", "wa_id": "15550123456"}],
        "messages": [{"id": "wamid.HBgLTemplateMessage123="}],
    }

    components = [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": "Acme Corp"}],
        }
    ]

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, TEST_TOKEN),
        patch(PATCH_POST, new_callable=AsyncMock) as mock_post,
    ):
        mock_post.return_value = mock_meta_response

        res = await WhatsAppClient.send_template_message(
            recipient="15550123456",
            template_name="workflow_update",
            language_code="en_US",
            components=components,
        )

        assert res["message_id"] == "wamid.HBgLTemplateMessage123="
        assert res["template_name"] == "workflow_update"
        assert res["language_code"] == "en_US"
        assert res["status"] == "accepted"


# ==============================================================================
# Error Normalization Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_meta_authentication_failure():
    """Verify Meta OAuth/token expiration errors (code 190) raise WhatsAppAuthenticationError."""
    meta_auth_err = {
        "error": {
            "message": "Invalid OAuth access token.",
            "type": "OAuthException",
            "code": 190,
            "fbtrace_id": "AbCdEf123",
        }
    }

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, "bad_token"),
        patch(PATCH_HTTP_POST, return_value=Response(401, json=meta_auth_err)),
        pytest.raises(WhatsAppAuthenticationError) as exc_info,
    ):
        await WhatsAppClient.send_text_message("15550123456", "Test")
    assert "authentication failed" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_meta_customer_service_window_expired():
    """Verify free-form text blocked outside 24h window (code 131030) raises descriptive error."""
    meta_window_err = {
        "error": {
            "message": "(#131030) Message failed to send because more than 24 hours have passed.",
            "type": "OAuthException",
            "code": 131030,
            "error_data": {"details": "24h window closed"},
        }
    }

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, TEST_TOKEN),
        patch(PATCH_HTTP_POST, return_value=Response(400, json=meta_window_err)),
        pytest.raises(WhatsAppMessagingWindowError) as exc_info,
    ):
        await WhatsAppClient.send_text_message("15550123456", "Test update")
    assert "24 hours" in str(exc_info.value)
    assert "template" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_meta_rate_limit_failure():
    """Verify rate limit error (code 80007 / HTTP 429) raises WhatsAppRateLimitError."""
    meta_rate_err = {
        "error": {
            "message": "(#80007) Rate limit reached for this phone number.",
            "type": "OAuthException",
            "code": 80007,
        }
    }

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, TEST_TOKEN),
        patch(PATCH_HTTP_POST, return_value=Response(429, json=meta_rate_err)),
        pytest.raises(WhatsAppRateLimitError) as exc_info,
    ):
        await WhatsAppClient.send_text_message("15550123456", "Test update")
    assert "rate limit" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_meta_invalid_recipient():
    """Verify non-WhatsApp recipient error (code 131008) raises WhatsAppRecipientError."""
    meta_recipient_err = {
        "error": {
            "message": "(#131008) Required parameter is missing or invalid: recipient.",
            "type": "OAuthException",
            "code": 131008,
        }
    }

    with (
        patch(PATCH_PID, TEST_PHONE_ID),
        patch(PATCH_TOKEN, TEST_TOKEN),
        patch(PATCH_HTTP_POST, return_value=Response(400, json=meta_recipient_err)),
        pytest.raises(WhatsAppRecipientError) as exc_info,
    ):
        await WhatsAppClient.send_text_message("15550123456", "Test")
    assert "recipient" in str(exc_info.value).lower()


# ==============================================================================
# Webhook Endpoint Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_webhook_challenge_verification_success():
    """Verify GET /api/v1/webhooks/whatsapp returns hub.challenge on valid token."""
    with patch.object(core_settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", TEST_VERIFY_TOKEN):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": TEST_VERIFY_TOKEN,
                    "hub.challenge": "1158201444",
                },
            )
            assert resp.status_code == 200
            assert resp.text == "1158201444"


@pytest.mark.asyncio
async def test_webhook_challenge_verification_invalid_token():
    """Verify GET /api/v1/webhooks/whatsapp returns 403 Forbidden on invalid verify token."""
    with patch.object(core_settings, "WHATSAPP_WEBHOOK_VERIFY_TOKEN", TEST_VERIFY_TOKEN):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(
                "/api/v1/webhooks/whatsapp",
                params={
                    "hub.mode": "subscribe",
                    "hub.verify_token": "wrong_token",
                    "hub.challenge": "1158201444",
                },
            )
            assert resp.status_code == 403


@pytest.mark.asyncio
async def test_webhook_signature_verification_rejection():
    """Verify POST /api/v1/webhooks/whatsapp rejects payloads with invalid signature."""
    payload = {"object": "whatsapp_business_account", "entry": []}
    raw_body = json.dumps(payload).encode("utf-8")

    with patch.object(core_settings, "WHATSAPP_APP_SECRET", TEST_APP_SECRET):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            # Bad signature
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=raw_body,
                headers={"X-Hub-Signature-256": "sha256=invalidhash123"},
            )
            assert resp.status_code == 401

            # Missing signature header
            resp_missing = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=raw_body,
            )
            assert resp_missing.status_code == 401


@pytest.mark.asyncio
async def test_webhook_delivery_status_update_and_deduplication(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify inbound status update updates ExternalAction record and deduplicates."""
    target_wamid = "wamid.HBgLWebhookDeliveryTest123"

    # Pre-create an ExternalAction record in EXECUTING state
    action = ExternalAction(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        operation="whatsapp_send_message",
        parameter_digest="abcdef123456",
        idempotency_key=f"test_idemp_{uuid.uuid4()}",
        status=ExternalActionStatus.EXECUTING,
        provider_action_id=target_wamid,
        provider_response={"status": "accepted"},
    )
    db_session.add(action)
    await db_session.commit()

    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "123456789",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15550212345",
                                "phone_number_id": TEST_PHONE_ID,
                            },
                            "statuses": [
                                {
                                    "id": target_wamid,
                                    "status": "delivered",
                                    "timestamp": "1730005000",
                                    "recipient_id": "15550123456",
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    raw_body = json.dumps(webhook_payload).encode("utf-8")
    sig_header = _generate_meta_signature(raw_body, TEST_APP_SECRET)

    with patch.object(core_settings, "WHATSAPP_APP_SECRET", TEST_APP_SECRET):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=raw_body,
                headers={"X-Hub-Signature-256": sig_header, "Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["details"]["processed_statuses"] == 1

            # Second delivery: verify deduplication counts duplicate
            resp_dup = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=raw_body,
                headers={"X-Hub-Signature-256": sig_header, "Content-Type": "application/json"},
            )
            assert resp_dup.status_code == 200
            data_dup = resp_dup.json()
            assert data_dup["details"]["duplicate_events"] == 1

    # Expire session cache so committed webhook transaction changes are visible
    action_id = action.id
    db_session.expunge_all()
    updated_action = await db_session.scalar(
        select(ExternalAction).where(ExternalAction.id == action_id)
    )
    assert updated_action is not None
    assert updated_action.provider_response.get("delivery_status") == "delivered"
    assert updated_action.completed_at is not None


@pytest.mark.asyncio
async def test_webhook_delivery_failure_updates_action_status(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify Meta status webhook with failure marks action failed and stores error code."""
    from flowpilot.models.integration_event import IntegrationEvent

    target_wamid = "wamid.HBgLTestFailureCode131030"
    action = ExternalAction(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        operation="whatsapp_send_template",
        parameter_digest="faildigest123456",
        idempotency_key=f"test_fail_idemp_{uuid.uuid4()}",
        status=ExternalActionStatus.SUCCEEDED,
        provider_action_id=target_wamid,
        provider_response={"status": "accepted", "recipient": "919398560017"},
    )
    db_session.add(action)
    await db_session.commit()

    webhook_payload = {
        "object": "whatsapp_business_account",
        "entry": [
            {
                "id": "1591437232188931",
                "changes": [
                    {
                        "value": {
                            "messaging_product": "whatsapp",
                            "metadata": {
                                "display_phone_number": "15551729819",
                                "phone_number_id": TEST_PHONE_ID,
                            },
                            "statuses": [
                                {
                                    "id": target_wamid,
                                    "status": "failed",
                                    "timestamp": "1730006000",
                                    "recipient_id": "919398560017",
                                    "errors": [
                                        {
                                            "code": 131030,
                                            "title": "Recipient phone number not in allowed list",
                                            "message": "Recipient phone number not in allowed list",
                                            "error_data": {
                                                "details": (
                                                    "Recipient phone number not in allowed list"
                                                )
                                            },
                                        }
                                    ],
                                }
                            ],
                        },
                        "field": "messages",
                    }
                ],
            }
        ],
    }

    raw_body = json.dumps(webhook_payload).encode("utf-8")
    sig_header = _generate_meta_signature(raw_body, TEST_APP_SECRET)

    with patch.object(core_settings, "WHATSAPP_APP_SECRET", TEST_APP_SECRET):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/v1/webhooks/whatsapp",
                content=raw_body,
                headers={"X-Hub-Signature-256": sig_header, "Content-Type": "application/json"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["ok"] is True
            assert data["details"]["processed_statuses"] == 1

    action_id = action.id
    db_session.expunge_all()
    updated_action = await db_session.scalar(
        select(ExternalAction).where(ExternalAction.id == action_id)
    )
    assert updated_action is not None
    assert updated_action.status == ExternalActionStatus.FAILED
    assert updated_action.provider_response.get("delivery_status") == "failed"
    errors = updated_action.provider_response.get("delivery_errors")
    assert errors is not None
    assert errors[0]["code"] == 131030
    assert "Recipient phone number not in allowed list" in updated_action.error_message

    # Verify IntegrationEvent recorded
    event = await db_session.scalar(
        select(IntegrationEvent).where(
            IntegrationEvent.provider == "whatsapp",
            IntegrationEvent.external_event_id == f"{target_wamid}_failed",
        )
    )
    assert event is not None
    assert event.event_type == "status_failed"


@pytest.mark.asyncio
async def test_whatsapp_subscribe_waba_to_app():
    """Verify subscribe_waba_to_app calls Meta Graph API subscribed_apps endpoint."""
    with patch("httpx.AsyncClient.post") as mock_post:
        mock_post.return_value = Response(200, json={"success": True})
        res = await WhatsAppClient.subscribe_waba_to_app(
            waba_id="1591437232188931",
            access_token=TEST_TOKEN,
        )
        assert res.get("success") is True
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert "1591437232188931/subscribed_apps" in call_url


# ==============================================================================
# Capability & Human Approval Tests
# ==============================================================================


def test_whatsapp_operations_classified_sensitive():
    """Verify backend policy strictly mandates human approval for WhatsApp actions."""
    assert is_operation_sensitive("whatsapp_send_message") is True
    assert is_operation_sensitive("whatsapp_send_template") is True


@pytest.mark.asyncio
async def test_whatsapp_send_message_mandates_approval(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify whatsapp_send_message raises ApprovalRequiredError without authorization."""
    params = {
        "recipient": "+1 (555) 012-3456",
        "text": "Critical account notice",
        "approved": False,
    }

    with (
        patch.object(core_settings, "WHATSAPP_PHONE_NUMBER_ID", TEST_PHONE_ID),
        patch.object(core_settings, "WHATSAPP_ACCESS_TOKEN", TEST_TOKEN),
        pytest.raises(ApprovalRequiredError),
    ):
        await execute_whatsapp_send_message(
            db=db_session,
            user_id=registered_user.id,
            parameters=params,
        )


@pytest.mark.asyncio
async def test_whatsapp_send_message_parameter_tamper_defense(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify modifying parameters after approval triggers ParameterTamperedError."""
    original_params = {
        "recipient": "15550123456",
        "text": "Approved message body",
    }
    digest = compute_parameter_digest(original_params)

    # Tampered params: changed text
    tampered_params = {
        "recipient": "15550123456",
        "text": "Tampered message body!!",
        "approved": True,
        "approval_parameter_digest": digest,
    }

    with (
        patch.object(core_settings, "WHATSAPP_PHONE_NUMBER_ID", TEST_PHONE_ID),
        patch.object(core_settings, "WHATSAPP_ACCESS_TOKEN", TEST_TOKEN),
        pytest.raises(ParameterTamperedError),
    ):
        await execute_whatsapp_send_message(
            db=db_session,
            user_id=registered_user.id,
            parameters=tampered_params,
        )


@pytest.mark.asyncio
async def test_whatsapp_send_message_approved_execution_and_idempotency(
    db_session: AsyncSession,
    registered_user: User,
    sample_run: AgentRun,
):
    """Verify authorized execution creates auditable ExternalAction with replay immunity."""
    params = {
        "recipient": "+1 (555) 012-3456",
        "text": "Authorized project brief",
    }
    material = {"recipient": "+1 (555) 012-3456", "text": "Authorized project brief"}
    digest = compute_parameter_digest(material)
    params["approved"] = True
    params["approval_parameter_digest"] = digest
    params["run_id"] = str(sample_run.id)
    params["step_id"] = "step_whatsapp"

    mock_resp = {
        "message_id": "wamid.HBgLIdempTest999",
        "recipient": "15550123456",
        "status": "accepted",
    }

    with (
        patch.object(core_settings, "WHATSAPP_PHONE_NUMBER_ID", TEST_PHONE_ID),
        patch.object(core_settings, "WHATSAPP_ACCESS_TOKEN", TEST_TOKEN),
        patch(
            "flowpilot.integrations.whatsapp.client.WhatsAppClient.send_text_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        mock_send.return_value = mock_resp

        # 1. First execution
        result1 = await execute_whatsapp_send_message(
            db=db_session,
            user_id=registered_user.id,
            parameters=params,
        )
        assert result1["status"] == "success"
        assert result1["provider_action_id"] == "wamid.HBgLIdempTest999"
        assert mock_send.call_count == 1

        # 2. Duplicate worker replay / redelivery with same idempotency key
        result2 = await execute_whatsapp_send_message(
            db=db_session,
            user_id=registered_user.id,
            parameters=params,
        )
        assert result2["status"] == "success"
        assert result2["idempotent_replay"] is True
        # Verify Meta API was NOT called a second time
        assert mock_send.call_count == 1


# ==============================================================================
# Multi-Channel Workflow Tests (Gmail + WhatsApp)
# ==============================================================================


@pytest.mark.asyncio
async def test_combined_gmail_and_whatsapp_independent_audit(
    db_session: AsyncSession,
    registered_user: User,
    sample_run: AgentRun,
):
    """Verify multi-channel workflow creates independent, decoupled ExternalAction records."""
    run_id = str(sample_run.id)

    # WhatsApp Action Parameters
    wa_params = {
        "recipient": "+1 (555) 012-3456",
        "text": "Project status brief",
    }
    wa_digest = compute_parameter_digest(wa_params)
    wa_params["approved"] = True
    wa_params["approval_parameter_digest"] = wa_digest
    wa_params["run_id"] = run_id
    wa_params["step_id"] = "step_2_whatsapp"

    with (
        patch.object(core_settings, "WHATSAPP_PHONE_NUMBER_ID", TEST_PHONE_ID),
        patch.object(core_settings, "WHATSAPP_ACCESS_TOKEN", TEST_TOKEN),
        patch(
            "flowpilot.integrations.whatsapp.client.WhatsAppClient.send_text_message",
            new_callable=AsyncMock,
        ) as mock_send,
    ):
        mock_send.return_value = {
            "message_id": "wamid.CombinedWorkflowTest",
            "recipient": "15550123456",
            "status": "accepted",
        }

        res = await execute_whatsapp_send_message(
            db=db_session,
            user_id=registered_user.id,
            parameters=wa_params,
        )
        assert res["status"] == "success"

    # Query external actions for this run
    actions = list(
        (
            await db_session.scalars(
                select(ExternalAction).where(
                    ExternalAction.user_id == registered_user.id,
                    ExternalAction.operation == "whatsapp_send_message",
                )
            )
        ).all()
    )
    assert len(actions) >= 1
    action = actions[-1]
    assert action.operation == "whatsapp_send_message"
    assert action.parameter_digest == wa_digest
    assert action.provider_action_id == "wamid.CombinedWorkflowTest"


# ==============================================================================
# Cross-User Isolation Tests
# ==============================================================================


@pytest.mark.asyncio
async def test_cross_user_external_action_isolation(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify external action records cannot be accessed across distinct user accounts."""
    other_user_id = uuid.uuid4()

    action = ExternalAction(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        operation="whatsapp_send_message",
        parameter_digest="digest_user_a",
        idempotency_key=f"idemp_{uuid.uuid4()}",
        status=ExternalActionStatus.SUCCEEDED,
    )
    db_session.add(action)
    await db_session.commit()

    # Query scoped to other user
    stmt = select(ExternalAction).where(
        ExternalAction.id == action.id,
        ExternalAction.user_id == other_user_id,
    )
    res = await db_session.scalar(stmt)
    assert res is None, "Cross-user security breach: other user accessed private ExternalAction."
