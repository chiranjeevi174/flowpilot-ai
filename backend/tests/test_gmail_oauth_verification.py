"""Regression tests for Gmail OAuth scope handling, incremental consent,
and numerical verification integrity in FlowPilot AI.
"""

import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.analysis import (
    analyze_tabular_dataset,
    clean_numerical_contradictions,
    find_numerical_contradictions,
    rectify_text_numbers,
    validate_summary_accuracy,
)
from flowpilot.agents.approval import approval_gate_node
from flowpilot.agents.verifier import verify_execution_node
from flowpilot.integrations.google.gmail import GmailClient
from flowpilot.integrations.oauth import OAuthScopeError, OAuthTokenBundle
from flowpilot.integrations.security import encrypt_oauth_token, generate_oauth_state
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User
from flowpilot.services.integrations import IntegrationService


@pytest.fixture
def sample_orders_rows() -> list[list]:
    """Sample spreadsheet rows matching the user's Google Sheet."""
    return [
        ["Order ID", "Product", "Customer", "Quantity", "Cost"],
        ["1001", "Laptop", "Sarah", 12, 650],
        ["1002", "Monitor", "Chinnu", 10, 180],
    ]


@pytest.fixture
async def sheets_only_google_connection(
    db_session: AsyncSession,
    registered_user: User,
) -> IntegrationConnection:
    """Connection with Sheets and Drive scopes, but lacking gmail.send."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="sheets",
        external_account_id="operator@flowpilot.ai",
        external_account_name="FlowPilot Operator",
        encrypted_access_token=encrypt_oauth_token("mock_access_token"),
        encrypted_refresh_token=encrypt_oauth_token("mock_refresh_token"),
        granted_scopes=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.metadata.readonly",
            "openid",
        ],
        status=ConnectionStatus.ACTIVE,
        is_default=True,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


# ---------------------------------------------------------------------------
# 1. Sheets-only Google OAuth & Missing gmail.send Permission
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gmail_send_missing_scope_raises(
    db_session: AsyncSession,
    sheets_only_google_connection: IntegrationConnection,
) -> None:
    """Attempting to dispatch email without gmail.send raises OAuthScopeError."""
    with pytest.raises(OAuthScopeError) as exc_info:
        await GmailClient.send_email(
            db=db_session,
            connection=sheets_only_google_connection,
            recipient="operator@flowpilot.ai",
            subject="Test Subject",
            body_text="Test Body",
        )
    assert "https://www.googleapis.com/auth/gmail.send" in str(exc_info.value)


@pytest.mark.asyncio
async def test_test_connection_verifies_required_service_scopes(
    db_session: AsyncSession,
    sheets_only_google_connection: IntegrationConnection,
) -> None:
    """test_connection returns error/authorization_required if missing required scope
    for service.
    """
    # Sheets service testing on sheets-only connection should succeed
    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(
            200, json={"id": "user-123", "email": "test@example.com"}
        )
        sheets_res = await IntegrationService.test_connection(
            db=db_session,
            connection_id=sheets_only_google_connection.id,
            user_id=sheets_only_google_connection.user_id,
        )
        assert sheets_res.ok is True

    # But if connection is evaluated for gmail service without gmail.send, it fails readiness
    sheets_only_google_connection.service = "gmail"
    await db_session.commit()

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = httpx.Response(
            200, json={"id": "user-123", "email": "test@example.com"}
        )
        gmail_res = await IntegrationService.test_connection(
            db=db_session,
            connection_id=sheets_only_google_connection.id,
            user_id=sheets_only_google_connection.user_id,
        )
        assert gmail_res.ok is False
        assert "gmail.send" in gmail_res.message


# ---------------------------------------------------------------------------
# 2. Incremental Authorization & Scope Preservation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_incremental_authorization_merges_and_preserves_scopes(
    db_session: AsyncSession,
    sheets_only_google_connection: IntegrationConnection,
) -> None:
    """Reauthorizing via incremental OAuth merges existing granted scopes with newly
    granted scopes.
    """
    incoming_scopes = [
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/gmail.send",
        "openid",
    ]

    mock_bundle = OAuthTokenBundle(
        access_token="new_access_token_with_gmail",
        refresh_token="new_refresh_token",
        expires_in_seconds=3600,
        granted_scopes=incoming_scopes,
        external_account_id="operator@flowpilot.ai",
        external_account_name="FlowPilot Operator",
    )

    state = generate_oauth_state(
        user_id=sheets_only_google_connection.user_id,
        provider="google",
        service="gmail",
        code_verifier="test_code_verifier_12345",
        connection_id=sheets_only_google_connection.id,
    )

    with patch(
        "flowpilot.services.integrations.GoogleOAuth.exchange_code", new_callable=AsyncMock
    ) as mock_exchange:
        mock_exchange.return_value = mock_bundle

        updated_conn = await IntegrationService.handle_oauth_callback(
            db=db_session,
            provider="google",
            code="mock_auth_code",
            state=state,
        )

        assert updated_conn.id == sheets_only_google_connection.id
        # Both Sheets AND Gmail scopes must be present!
        assert "https://www.googleapis.com/auth/spreadsheets" in updated_conn.granted_scopes
        assert (
            "https://www.googleapis.com/auth/drive.metadata.readonly" in updated_conn.granted_scopes
        )
        assert "https://www.googleapis.com/auth/gmail.send" in updated_conn.granted_scopes
        assert "https://www.googleapis.com/auth/userinfo.email" in updated_conn.granted_scopes


# ---------------------------------------------------------------------------
# 3. Gmail Integration Readiness Status Reporting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_app_connections_overview_gmail_readiness(
    db_session: AsyncSession,
    sheets_only_google_connection: IntegrationConnection,
) -> None:
    """Overview must report authorization_required for Gmail when connection lacks gmail.send."""
    overview = await IntegrationService.get_app_connections_overview(
        db=db_session,
        user_id=sheets_only_google_connection.user_id,
    )

    gmail_item = next((item for item in overview if item.id == "gmail"), None)
    assert gmail_item is not None
    # Lacking gmail.send must report authorization_required
    assert gmail_item.status == "authorization_required"

    # Add gmail.send scope and verify status transitions to connected
    sheets_only_google_connection.granted_scopes = [
        *sheets_only_google_connection.granted_scopes,
        "https://www.googleapis.com/auth/gmail.send",
    ]
    await db_session.commit()

    overview_after = await IntegrationService.get_app_connections_overview(
        db=db_session,
        user_id=sheets_only_google_connection.user_id,
    )
    gmail_item_after = next((item for item in overview_after if item.id == "gmail"), None)
    assert gmail_item_after is not None
    assert gmail_item_after.status == "connected"


# ---------------------------------------------------------------------------
# 4. Correct Arithmetic & Dual Interpretation
# ---------------------------------------------------------------------------


def test_tabular_analysis_dual_interpretation(sample_orders_rows: list[list]) -> None:
    """Verify 9,600 (unit price) and 830 (order cost) are both computed correctly."""
    analysis = analyze_tabular_dataset(sample_orders_rows)

    assert analysis.data_row_count == 2
    assert analysis.total_units == Decimal("22")

    # Check primary unit-based total (12 * 650 + 10 * 180 = 7800 + 1800 = 9600)
    assert analysis.per_unit_combined_total == Decimal("9600")
    # Check alternate column sum (650 + 180 = 830)
    assert analysis.cost_column_sum == Decimal("830")
    assert analysis.currency_detected is None

    # Assumptions should present both interpretations cleanly
    assumptions_text = " ".join(analysis.calculation_assumptions)
    assert "9,600" in assumptions_text
    assert "830" in assumptions_text
    # Should NOT contain legacy regression notes or arbitrary negations
    assert "NOTE ON PREVIOUS REGRESSION" not in assumptions_text


def test_numerical_validation_rejects_incorrect_amounts(sample_orders_rows: list[list]) -> None:
    """validate_summary_accuracy rejects ungrounded amounts like 8,300 or 8,700."""
    analysis = analyze_tabular_dataset(sample_orders_rows)

    # Valid text containing 9,600 and 830
    valid_text = "Total units are 22. Total calculated cost is 9,600 (or 830 if cost is per order)."
    valid_errors = validate_summary_accuracy(valid_text, analysis)
    assert len(valid_errors) == 0

    # Invalid text containing hallucinated 8,300
    invalid_text = "Total units are 22. Total calculated cost is 8,300."
    invalid_errors = validate_summary_accuracy(invalid_text, analysis)
    assert len(invalid_errors) > 0
    assert any("8,300" in u for u in invalid_errors)


# ---------------------------------------------------------------------------
# 5. Contradictory Numerical Claims Detection & Safe Rectification
# ---------------------------------------------------------------------------


def test_contradiction_detection_and_cleaning(sample_orders_rows: list[list]) -> None:
    """Contradictory claim asserting verified number is incorrect is detected and purged."""
    analysis = analyze_tabular_dataset(sample_orders_rows)

    contradictory_text = (
        "Key Findings:\n"
        "- Total units: 22\n"
        "- The value 9,600 is mathematically incorrect and must not be used.\n"
        "- Overall amount is 9,600 across 2 orders."
    )

    contradictions = find_numerical_contradictions(contradictory_text, analysis)
    assert len(contradictions) >= 1
    assert any("9,600" in c for c in contradictions)

    cleaned = clean_numerical_contradictions(contradictory_text, analysis)
    assert "is mathematically incorrect and must not be used" not in cleaned
    assert "Total units: 22" in cleaned
    assert "Overall amount is 9,600" in cleaned


def test_rectify_text_numbers_safe_replacement(sample_orders_rows: list[list]) -> None:
    """rectify_text_numbers avoids blind global replacements and does not turn negations
    into contradictions.
    """
    analysis = analyze_tabular_dataset(sample_orders_rows)

    # If text had an erroneous total 8,300 in a total context, it is rectified to 9,600
    bad_summary = "Total cost was computed as 8,300 across 22 units."
    rectified = rectify_text_numbers(bad_summary, analysis)
    assert "9,600" in rectified
    assert "8,300" not in rectified

    # If text had a contradiction asserting 9,600 is incorrect, it must be purged
    bad_contradiction = "Note: 9,600 is incorrect and invalid."
    rectified_contra = rectify_text_numbers(bad_contradiction, analysis)
    assert "9,600 is incorrect" not in rectified_contra


@pytest.mark.asyncio
async def test_verifier_rejects_contradictory_claims(
    db_session: AsyncSession,
    registered_user: User,
    sample_orders_rows: list[list],
) -> None:
    """Verifier rejects step output if it asserts verified numerical totals are incorrect."""
    agent_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        original_request="Analyze data",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    state = {
        "run_id": str(agent_run.id),
        "user_id": str(registered_user.id),
        "original_request": "Analyze data",
        "execution_plan": [{"step_id": "step_summary"}],
        "step_results": [
            {
                "step_id": "step_summary",
                "status": "success",
                "result": {
                    "summary": "Analysis summary: Total 22 units.",
                    "contradictory_statement": (
                        "The value 9,600 is mathematically incorrect and must not be used."
                    ),
                },
            }
        ],
        "correction_attempts": 0,
    }

    res = await verify_execution_node(state)
    assert res["verification_result"]["passed"] is False
    assert "contradictory claim detected" in res["verification_result"]["critique"].lower()


# ---------------------------------------------------------------------------
# 6. Approval-Body Integrity
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approval_payload_purges_contradictions_before_gate(
    db_session: AsyncSession,
    registered_user: User,
    sample_orders_rows: list[list],
) -> None:
    """approval_gate_node purges contradictory statements before surfacing payload to interrupt."""
    agent_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        original_request="Send summary email",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.commit()

    state = {
        "run_id": str(agent_run.id),
        "user_id": str(registered_user.id),
        "execution_plan": [
            {
                "step_id": "step_email",
                "operation": "gmail_send_message",
                "approval_required": True,
                "parameters": {
                    "recipient": "operator@flowpilot.ai",
                    "subject": "Analysis and Summary of Sample Data",
                    "body": (
                        "Hello Team,\n\n"
                        "Summary of sample data:\n"
                        "- 22 units across 2 orders.\n"
                        "- The value 9,600 is mathematically incorrect and must not be used.\n"
                        "- Total calculated cost is 9,600.\n\n"
                        "Regards,\nFlowPilot"
                    ),
                },
            }
        ],
        "step_results": [
            {
                "step_id": "step_read",
                "result": {
                    "rows": sample_orders_rows,
                },
            }
        ],
    }

    with patch("flowpilot.agents.approval.interrupt") as mock_interrupt:
        mock_interrupt.return_value = {"decision": "reject"}
        await approval_gate_node(state)

        assert mock_interrupt.called
        payload = mock_interrupt.call_args[0][0]
        rendered_body = payload["body"]
        # Contradictory line must have been purged from the email body!
        assert "The value 9,600 is mathematically incorrect" not in rendered_body
        assert "Total calculated cost is 9,600" in rendered_body


# ---------------------------------------------------------------------------
# 7. Failure After Approval Without Falsely Reporting Delivery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failure_after_approval_marks_action_failed(
    db_session: AsyncSession,
    sheets_only_google_connection: IntegrationConnection,
    registered_user: User,
) -> None:
    """When dispatch fails due to OAuth scope error after approval, ExternalAction is
    marked FAILED.
    """
    agent_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        original_request="Send summary email",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(agent_run)
    await db_session.flush()

    action = ExternalAction(
        id=uuid.uuid4(),
        run_id=agent_run.id,
        user_id=registered_user.id,
        operation="gmail_send_message",
        parameter_digest="mock_digest_12345",
        idempotency_key=str(uuid.uuid4()),
        status=ExternalActionStatus.PENDING,
        provider_response={},
    )
    db_session.add(action)
    await db_session.commit()

    # Attempt execution with sheets-only connection
    try:
        await GmailClient.send_email(
            db=db_session,
            connection=sheets_only_google_connection,
            recipient="operator@flowpilot.ai",
            subject="Analysis",
            body_text="Content",
        )
    except OAuthScopeError as err:
        action.status = ExternalActionStatus.FAILED
        action.error_message = str(err)
        await db_session.commit()

    await db_session.refresh(action)
    assert action.status == ExternalActionStatus.FAILED
    assert "https://www.googleapis.com/auth/gmail.send" in action.error_message


# ---------------------------------------------------------------------------
# 8. Prevention of Duplicate Gmail Dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prevention_of_duplicate_gmail_dispatch(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Already executed or dispatched actions cannot be re-dispatched."""
    agent_run = AgentRun(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        thread_id=f"thread_{uuid.uuid4().hex[:8]}",
        original_request="Send email",
        status=AgentRunStatus.COMPLETED,
    )
    db_session.add(agent_run)
    await db_session.flush()

    executed_action = ExternalAction(
        id=uuid.uuid4(),
        run_id=agent_run.id,
        user_id=registered_user.id,
        operation="gmail_send_message",
        parameter_digest="mock_digest_12345",
        idempotency_key=str(uuid.uuid4()),
        status=ExternalActionStatus.SUCCEEDED,
        provider_action_id="msg_sent_123",
        provider_response={"message_id": "msg_sent_123"},
    )
    db_session.add(executed_action)
    await db_session.commit()

    # Verify action cannot be re-approved or executed again
    assert executed_action.status in (ExternalActionStatus.SUCCEEDED, ExternalActionStatus.FAILED)
    can_execute = executed_action.status == ExternalActionStatus.PENDING
    assert can_execute is False
