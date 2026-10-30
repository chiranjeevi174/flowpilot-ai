"""Tests for Phase 6 external capabilities, audit tracking, idempotency, and tamper detection."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.integrations.registry import (
    EXTERNAL_CAPABILITIES,
    ApprovalRequiredError,
    ConnectionNotFoundError,
    ParameterTamperedError,
    _execute_with_action_audit,
    execute_gmail_send_email,
    execute_sheets_append_rows,
    execute_slack_send_message,
    find_user_connection,
)
from flowpilot.integrations.security import (
    compute_parameter_digest,
    encrypt_oauth_token,
)
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.models.user import User


@pytest.fixture
async def sample_user(db_session: AsyncSession) -> User:
    """Create a sample user."""
    user = User(
        id=uuid.uuid4(),
        email=f"user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="test_hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def sample_run(db_session: AsyncSession, sample_user: User) -> AgentRun:
    """Create a sample AgentRun for foreign key binding."""
    run = AgentRun(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        thread_id=f"flowpilot_run_{uuid.uuid4().hex[:8]}",
        original_request="Send report email and append data",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.fixture
async def another_user(db_session: AsyncSession) -> User:
    """Create another user for isolation tests."""
    user = User(
        id=uuid.uuid4(),
        email=f"user_{uuid.uuid4().hex[:8]}@example.com",
        password_hash="test_hash",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest.fixture
async def google_connection(db_session: AsyncSession, sample_user: User) -> IntegrationConnection:
    """Create an active Google connection for sample_user."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        provider="google",
        service="gmail",
        external_account_id="user@gmail.com",
        encrypted_access_token=encrypt_oauth_token("ya29.sample_access_token"),
        encrypted_refresh_token=encrypt_oauth_token("1//sample_refresh_token"),
        granted_scopes=[
            "https://www.googleapis.com/auth/gmail.send",
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/spreadsheets",
        ],
        status=ConnectionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


@pytest.fixture
async def slack_connection(db_session: AsyncSession, sample_user: User) -> IntegrationConnection:
    """Create an active Slack connection for sample_user."""
    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=sample_user.id,
        provider="slack",
        service="slack",
        external_account_id="T01234567:U01234567",
        encrypted_access_token=encrypt_oauth_token("xoxb-sample_token"),
        granted_scopes=["chat:write", "channels:read"],
        status=ConnectionStatus.ACTIVE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return conn


def test_capability_registry_allowlist():
    """Verify that all Phase 6 capabilities are registered with correct approval specs."""
    expected_capabilities = [
        ("gmail_list_messages", False),
        ("gmail_get_message", False),
        ("gmail_prepare_response", False),
        ("gmail_create_draft", False),
        ("gmail_send_email", True),
        ("slack_list_channels", False),
        ("slack_prepare_message", False),
        ("slack_send_message", True),
        ("sheets_read_range", False),
        ("sheets_append_rows", True),
    ]

    for cap_name, requires_approval in expected_capabilities:
        assert cap_name in EXTERNAL_CAPABILITIES, f"Missing capability {cap_name}"
        cap = EXTERNAL_CAPABILITIES[cap_name]
        assert cap.requires_approval == requires_approval, (
            f"Capability {cap_name} requires_approval mismatch"
        )


async def test_find_user_connection_isolation(
    db_session: AsyncSession,
    sample_user: User,
    another_user: User,
    google_connection: IntegrationConnection,
):
    """Verify that user connection lookups enforce strict multi-tenant isolation."""
    # sample_user finds their connection
    conn = await find_user_connection(db_session, sample_user.id, "google", "gmail")
    assert conn.id == google_connection.id

    # another_user has no connection and raises ConnectionNotFoundError
    with pytest.raises(ConnectionNotFoundError):
        await find_user_connection(db_session, another_user.id, "google", "gmail")

    # another_user querying sample_user's connection by ID raises ConnectionNotFoundError
    with pytest.raises(ConnectionNotFoundError):
        await find_user_connection(
            db_session,
            another_user.id,
            "google",
            connection_id=google_connection.id,
        )


async def test_execute_with_action_audit_success(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
    google_connection: IntegrationConnection,
):
    """Verify that external actions record audit history with EXECUTING -> SUCCEEDED transition."""
    params = {"recipient": "recipient@example.com", "step_id": "step_1", "approved": True}
    mock_fn = AsyncMock(return_value=("msg_12345", {"status": "sent", "id": "msg_12345"}))

    result = await _execute_with_action_audit(
        db=db_session,
        user_id=sample_user.id,
        operation="gmail_send_email",
        parameters=params,
        connection=google_connection,
        run_id=sample_run.id,
        execution_fn=mock_fn,
    )

    assert result["status"] == "success"
    assert result["provider_action_id"] == "msg_12345"
    assert mock_fn.await_count == 1

    # Verify database persistence of ExternalAction
    stmt = select(ExternalAction).where(ExternalAction.run_id == sample_run.id)
    action = await db_session.scalar(stmt)
    assert action is not None
    assert action.user_id == sample_user.id
    assert action.connection_id == google_connection.id
    assert action.operation == "gmail_send_email"
    assert action.status == ExternalActionStatus.SUCCEEDED
    assert action.provider_action_id == "msg_12345"
    assert action.provider_response == {"status": "sent", "id": "msg_12345"}
    assert action.completed_at is not None


async def test_execute_with_action_audit_idempotency_replay(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
    google_connection: IntegrationConnection,
):
    """Verify that redelivered tasks or LangGraph replay does not re-execute side effects."""
    params = {"recipient": "client@example.com", "step_id": "step_idempotent", "approved": True}
    mock_fn = AsyncMock(return_value=("msg_unique_1", {"sent": True}))

    # First invocation executes the side effect
    result_1 = await _execute_with_action_audit(
        db=db_session,
        user_id=sample_user.id,
        operation="gmail_send_email",
        parameters=params,
        connection=google_connection,
        run_id=sample_run.id,
        execution_fn=mock_fn,
    )
    assert result_1["status"] == "success"
    assert mock_fn.await_count == 1

    # Second invocation with same idempotency key short-circuits
    result_2 = await _execute_with_action_audit(
        db=db_session,
        user_id=sample_user.id,
        operation="gmail_send_email",
        parameters=params,
        connection=google_connection,
        run_id=sample_run.id,
        execution_fn=mock_fn,
    )

    assert result_2["status"] == "success"
    assert result_2.get("idempotent_replay") is True
    # mock_fn was NOT called a second time
    assert mock_fn.await_count == 1


async def test_execute_with_action_audit_failure_records_failed_status(
    db_session: AsyncSession,
    sample_user: User,
    sample_run: AgentRun,
    google_connection: IntegrationConnection,
):
    """Verify that execution failures persist FAILED state and error message in ExternalAction."""
    params = {"recipient": "error@example.com", "step_id": "step_fail", "approved": True}
    mock_fn = AsyncMock(side_effect=RuntimeError("Provider API timed out"))

    with pytest.raises(RuntimeError, match="Provider API timed out"):
        await _execute_with_action_audit(
            db=db_session,
            user_id=sample_user.id,
            operation="gmail_send_email",
            parameters=params,
            connection=google_connection,
            run_id=sample_run.id,
            execution_fn=mock_fn,
        )

    stmt = select(ExternalAction).where(ExternalAction.run_id == sample_run.id)
    action = await db_session.scalar(stmt)
    assert action is not None
    assert action.status == ExternalActionStatus.FAILED
    assert "Provider API timed out" in (action.error_message or "")


async def test_approval_mandated_for_sensitive_capabilities(
    db_session: AsyncSession,
    sample_user: User,
    google_connection: IntegrationConnection,
    slack_connection: IntegrationConnection,
):
    """Verify that sensitive operations unconditionally fail if executed without approval."""
    # 1. Gmail send without approval
    with pytest.raises(ApprovalRequiredError, match="requires explicit human approval"):
        await execute_gmail_send_email(
            db_session,
            sample_user.id,
            {"recipient": "test@example.com", "subject": "Hi", "body": "Hello"},
        )

    # 2. Slack send without approval
    with pytest.raises(ApprovalRequiredError, match="requires explicit human approval"):
        await execute_slack_send_message(
            db_session,
            sample_user.id,
            {"channel": "C12345", "text": "Hello world"},
        )

    # 3. Google Sheets append without approval
    with pytest.raises(ApprovalRequiredError, match="requires explicit human approval"):
        await execute_sheets_append_rows(
            db_session,
            sample_user.id,
            {
                "spreadsheet_id": "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms",
                "range": "Sheet1!A1",
                "values": [["1"]],
            },
        )


async def test_parameter_tampering_detection(
    db_session: AsyncSession,
    sample_user: User,
    google_connection: IntegrationConnection,
):
    """Verify that modifying parameters after human approval invalidates authorization."""
    original_params = {
        "recipient": "ceo@example.com",
        "subject": "Budget",
        "body": "Approved $10,000",
    }
    original_digest = compute_parameter_digest(original_params)

    # Tampered params: recipient changed after approval
    tampered_params = {
        "recipient": "attacker@example.com",
        "subject": "Budget",
        "body": "Approved $10,000",
        "approved": True,
        "approval_parameter_digest": original_digest,
    }

    with pytest.raises(ParameterTamperedError, match="Parameter digest mismatch"):
        await execute_gmail_send_email(
            db_session,
            sample_user.id,
            tampered_params,
        )
