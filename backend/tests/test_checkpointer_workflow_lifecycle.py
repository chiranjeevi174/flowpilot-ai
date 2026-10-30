"""Regression tests for LangGraph checkpointer lifecycle, worker restart, and idempotency."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.integrations.google.gmail import GmailClient
from flowpilot.integrations.security import encrypt_oauth_token
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRunStatus
from flowpilot.models.integration_connection import ConnectionStatus, IntegrationConnection
from flowpilot.models.user import User
from flowpilot.services.llm import LLMService
from flowpilot.workflows.engine import (
    WorkflowEngine,
    _to_psycopg_conninfo,
)


def get_gmail_workflow_llm_mock(operation: str = "gmail_send_email"):
    """Mock LLM responses that output an actionable plan with a sensitive Gmail action."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "email_communication",
                "action": "send_email",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {"recipient": "client@example.com"},
                "clarification_message": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=25,
    )
    plan_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation": operation,
                        "parameters": {
                            "recipient": "client@example.com",
                            "subject": "Project Status Update",
                            "body": "Here is the requested project status update.",
                        },
                        "required_capability": operation,
                        "approval_required": True,
                        "expected_outcome": "Email dispatched to client.",
                    }
                ],
                "unsupported_capability": False,
                "unsupported_reason": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=30,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Email sent and verified.",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=20,
    )

    async def _mock_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        if "Verification" in sys_msg:
            return verifier_resp
        return GatewayGenerationResult(
            content=json.dumps({"status": "ok"}),
            provider="gemini",
            model="gemini-2.5-flash",
            latency_ms=10,
        )

    return _mock_generate


@pytest.fixture
async def setup_gmail_user_and_connection(
    db_session: AsyncSession,
    registered_user: User,
) -> tuple[User, IntegrationConnection]:
    """Create test user with valid LLM preferences and active Gmail integration."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="gemini",
            api_key="AIzaSyTestGeminiKey1234567890",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gemini-2.5-flash",
        )

    conn = IntegrationConnection(
        id=uuid.uuid4(),
        user_id=registered_user.id,
        provider="google",
        service="gmail",
        external_account_id="tester@gmail.com",
        external_account_name="Tester",
        encrypted_access_token=encrypt_oauth_token("mock_access_token"),
        encrypted_refresh_token=encrypt_oauth_token("mock_refresh_token"),
        granted_scopes=[
            "https://www.googleapis.com/auth/gmail.readonly",
            "https://www.googleapis.com/auth/gmail.compose",
            "https://www.googleapis.com/auth/gmail.send",
        ],
        status=ConnectionStatus.ACTIVE,
    )
    db_session.add(conn)
    await db_session.commit()
    await db_session.refresh(conn)
    return registered_user, conn


@pytest.fixture
async def real_postgres_checkpointer():
    """Fixture providing a real PostgreSQL-backed checkpointer connected to TEST_DATABASE_URL."""
    settings = get_settings()
    test_conninfo = _to_psycopg_conninfo(settings.TEST_DATABASE_URL)
    pool = AsyncConnectionPool(
        conninfo=test_conninfo,
        min_size=1,
        max_size=5,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool.open()
    checkpointer = AsyncPostgresSaver(conn=pool)
    await checkpointer.setup()
    try:
        yield checkpointer
    finally:
        await pool.close()


@pytest.mark.asyncio
async def test_workflow_reaches_planning_and_pauses_for_approval(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirements 1 & 2: A newly queued workflow reaches planning and pauses for approval."""
    user, _ = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Prepare an email to client@example.com about project status.",
            checkpointer=real_postgres_checkpointer,
        )

    # 1. Reaches intent and planning stages
    assert run.detected_intent is not None
    assert run.detected_intent.get("intent") == "email_communication"
    assert run.execution_plan is not None
    assert len(run.execution_plan) == 1
    assert run.execution_plan[0]["operation"] == "gmail_send_email"

    # 2. Pauses for human approval without crashing with 'No checkpointer set'
    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    assert run.error_message is None

    # Checkpoint tuple is persisted in PostgreSQL
    tuple_state = await real_postgres_checkpointer.aget_tuple(
        {"configurable": {"thread_id": run.thread_id}}
    )
    assert tuple_state is not None
    assert tuple_state.checkpoint["channel_values"]["approval_status"] == "pending"


@pytest.mark.asyncio
async def test_workflow_resumes_from_persisted_checkpoint_when_approved(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirement 3: Execution successfully resumes from its persisted PostgreSQL checkpoint."""
    user, _ = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Send an update to client@example.com.",
            checkpointer=real_postgres_checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    # Mock GmailClient.send_email
    mock_send = AsyncMock(return_value={"message_id": "msg_gmail_999", "thread_id": "th_gmail_999"})
    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen),
        patch.object(GmailClient, "send_email", mock_send),
    ):
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=user.id,
            decision="approve",
            comment="Approved by operator",
            checkpointer=real_postgres_checkpointer,
        )

    assert resumed_run.status == AgentRunStatus.COMPLETED
    assert resumed_run.error_message is None
    assert mock_send.await_count == 1


@pytest.mark.asyncio
async def test_rejected_action_does_not_execute(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirement 4: Rejected actions do not execute and GmailClient.send_email is never called."""
    user, _ = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Send an email to client@example.com.",
            checkpointer=real_postgres_checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    mock_send = AsyncMock()
    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen),
        patch.object(GmailClient, "send_email", mock_send),
    ):
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=user.id,
            decision="reject",
            comment="Rejected due to invalid recipient",
            checkpointer=real_postgres_checkpointer,
        )

    assert resumed_run.status == AgentRunStatus.REJECTED
    # Gmail send must NOT have been called
    assert mock_send.await_count == 0


@pytest.mark.asyncio
async def test_restarted_worker_can_resume_existing_checkpoint(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
) -> None:
    """Requirement 5: A restarted worker process can resume an existing PostgreSQL checkpoint."""
    user, _ = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()
    settings = get_settings()
    test_conninfo = _to_psycopg_conninfo(settings.TEST_DATABASE_URL)

    # Worker 1: Runs workflow up to approval interrupt and shuts down
    pool1 = AsyncConnectionPool(
        conninfo=test_conninfo,
        min_size=1,
        max_size=3,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool1.open()
    worker1_checkpointer = AsyncPostgresSaver(conn=pool1)
    await worker1_checkpointer.setup()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Send report to client@example.com.",
            checkpointer=worker1_checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    # Worker 1 terminates completely
    await pool1.close()

    # Worker 2: Simulates brand new process starting up with fresh connection pool
    pool2 = AsyncConnectionPool(
        conninfo=test_conninfo,
        min_size=1,
        max_size=3,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await pool2.open()
    worker2_checkpointer = AsyncPostgresSaver(conn=pool2)
    await worker2_checkpointer.setup()

    mock_send = AsyncMock(return_value={"message_id": "msg_restarted_worker_123"})
    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen),
        patch.object(GmailClient, "send_email", mock_send),
    ):
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=user.id,
            decision="approve",
            comment="Approved after worker restart",
            checkpointer=worker2_checkpointer,
        )

    assert resumed_run.status == AgentRunStatus.COMPLETED
    assert mock_send.await_count == 1
    await pool2.close()


@pytest.mark.asyncio
async def test_no_duplicate_email_sent_during_retries(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirement 6: Redelivery / retries do not send duplicate emails due to idempotency keys."""
    user, conn = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Send single email to client@example.com.",
            checkpointer=real_postgres_checkpointer,
        )

    mock_send = AsyncMock(return_value={"message_id": "msg_unique_101"})
    with (
        patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen),
        patch.object(GmailClient, "send_email", mock_send),
    ):
        # First execution
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=user.id,
            decision="approve",
            checkpointer=real_postgres_checkpointer,
        )

        assert resumed_run.status == AgentRunStatus.COMPLETED
        assert mock_send.await_count == 1

        # Now simulate retry or duplicate execution of the exact same external action capability
        from flowpilot.integrations.registry import execute_gmail_send_email

        step_params = resumed_run.execution_plan[0]["parameters"]
        # Re-executing with the same run_id and step_id
        duplicate_params = {
            **step_params,
            "run_id": str(run.id),
            "step_id": "step_1",
            "approved": True,
        }
        dup_result = await execute_gmail_send_email(
            db=db_session,
            user_id=user.id,
            parameters=duplicate_params,
        )

        # Must return cached result without calling send_email again
        assert dup_result.get("idempotent_replay") is True
        assert dup_result.get("provider_action_id") == "msg_unique_101"
        assert dup_result.get("result", {}).get("message_id") == "msg_unique_101"
        assert mock_send.await_count == 1  # Still 1, NOT 2!


@pytest.mark.asyncio
async def test_cross_user_checkpoint_access_prohibited(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirement 9: Cross-user checkpoint access and resumption is strictly prohibited."""
    owner_user, _ = setup_gmail_user_and_connection
    mock_gen = get_gmail_workflow_llm_mock()

    # Create a second, unauthorized user
    from flowpilot.core.security import hash_password

    other_user = User(
        id=uuid.uuid4(),
        email="unauthorized_attacker@example.com",
        password_hash=hash_password("AttackerPass123!"),
        full_name="Unauthorized User",
        is_active=True,
    )
    db_session.add(other_user)
    await db_session.commit()
    await db_session.refresh(other_user)

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=owner_user.id,
            request="Send confidential email to client@example.com.",
            checkpointer=real_postgres_checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    # Unauthorized user attempts to approve or access owner's paused workflow checkpoint
    with pytest.raises(PermissionError, match="Access denied"):
        await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=other_user.id,
            decision="approve",
            comment="Unauthorized approval attempt",
            checkpointer=real_postgres_checkpointer,
        )

    # Workflow must remain safely paused in AWAITING_APPROVAL
    await db_session.refresh(run)
    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    assert run.error_message is None


@pytest.mark.asyncio
async def test_normal_non_sensitive_workflow_remains_functional(
    db_session: AsyncSession,
    setup_gmail_user_and_connection: tuple[User, IntegrationConnection],
    real_postgres_checkpointer: AsyncPostgresSaver,
) -> None:
    """Requirement 10: Normal non-sensitive workflows execute end-to-end without interruption."""
    user, _ = setup_gmail_user_and_connection

    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "analysis",
                "action": "text_categorization",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {"text": "Great turnaround time!"},
                "clarification_message": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=15,
    )
    plan_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation": "text_categorization",
                        "parameters": {
                            "text": "Great turnaround time!",
                            "categories": ["sentiment"],
                        },
                        "required_capability": "text_categorization",
                        "approval_required": False,
                        "expected_outcome": "Analyzed text sentiment",
                    }
                ],
                "unsupported_capability": False,
                "unsupported_reason": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=20,
    )
    tool_resp = GatewayGenerationResult(
        content=json.dumps({"sentiment": "positive", "confidence": 0.99}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=10,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Text accurately categorized.",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=15,
    )

    async def _mock_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        if "Verification" in sys_msg:
            return verifier_resp
        if "categorization" in sys_msg:
            return tool_resp
        return GatewayGenerationResult(
            content=json.dumps({"status": "ok"}),
            provider="gemini",
            model="gemini-2.5-flash",
            latency_ms=10,
        )

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=_mock_generate):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=user.id,
            request="Categorize customer feedback sentiment.",
            checkpointer=real_postgres_checkpointer,
        )

    # Must complete end-to-end without pausing for approval
    assert run.status == AgentRunStatus.COMPLETED
    assert run.error_message is None
    assert run.current_step >= 1
    assert run.execution_plan is not None

    # Checkpoint is persisted in PostgreSQL
    tuple_state = await real_postgres_checkpointer.aget_tuple(
        {"configurable": {"thread_id": run.thread_id}}
    )
    assert tuple_state is not None
    assert tuple_state.checkpoint["channel_values"]["execution_status"] == "completed"
