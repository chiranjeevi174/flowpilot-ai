"""Automated persistence tests verifying durable PostgreSQL checkpoints and crash recovery."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.graph import create_agent_graph
from flowpilot.core.config import get_settings
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRunStatus
from flowpilot.models.user import User
from flowpilot.workflows.engine import WorkflowEngine, _ensure_win32_selector_loop


@pytest.fixture
async def setup_persistence_user(db_session: AsyncSession, registered_user: User) -> User:
    """Setup active credential and preference for test user."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

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
        await db_session.commit()
    return registered_user


def get_mock_persistence_generator():
    """Mock LLM generator for persistence testing."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "support",
                "action": "reply",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {},
                "clarification_message": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    plan_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "steps": [
                    {
                        "step_id": "step_1",
                        "operation": "response_drafting",
                        "parameters": {"context": "Customer warranty claim"},
                        "required_capability": "response_drafting",
                        "approval_required": True,
                        "expected_outcome": "Drafted reply",
                    }
                ],
                "unsupported_capability": False,
                "unsupported_reason": None,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    tool_resp = GatewayGenerationResult(
        content=json.dumps({"subject": "Warranty Update", "body": "Your claim is approved."}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Verified claim response.",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    async def mock_gateway_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        if "Verification" in sys_msg:
            return verifier_resp
        return tool_resp

    return mock_gateway_generate


@pytest.mark.asyncio
async def test_persistence_survives_graph_reconstruction(
    db_session: AsyncSession,
    setup_persistence_user: User,
) -> None:
    """Verify state persists in checkpointer and resumes cleanly after graph reconstruction."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_persistence_generator()

    # 1. Start execution with graph instance 1
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_persistence_user.id,
            request="Handle warranty claim.",
            checkpointer=checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    # 2. Simulate process crash / total reconstruction of graph using same checkpointer
    new_graph = create_agent_graph(checkpointer=checkpointer)
    thread_config = {"configurable": {"thread_id": run.thread_id}}

    snapshot = await new_graph.aget_state(thread_config)
    assert snapshot.values["run_id"] == str(run.id)
    assert snapshot.values["approval_status"] == "pending"

    # 3. Resume execution on reconstructed graph
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=setup_persistence_user.id,
            decision="approve",
            comment="Approved by manager.",
            checkpointer=checkpointer,
        )

    assert resumed_run.status == AgentRunStatus.COMPLETED
    assert resumed_run.completed_at is not None


@pytest.mark.asyncio
async def test_real_postgres_checkpointer_integration(
    db_session: AsyncSession,
    setup_persistence_user: User,
) -> None:
    """Integration test verifying persistence directly using PostgreSQL AsyncPostgresSaver."""
    _ensure_win32_selector_loop()
    settings = get_settings()

    # Use test database URL converted to standard postgres psycopg format
    test_conninfo = settings.TEST_DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://")

    async with AsyncConnectionPool(
        conninfo=test_conninfo,
        min_size=1,
        max_size=3,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    ) as pool:
        pg_checkpointer = AsyncPostgresSaver(conn=pool)
        await pg_checkpointer.setup()

        mock_gen = get_mock_persistence_generator()

        # Phase 1: Start run and persist checkpoint in PostgreSQL
        with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
            run = await WorkflowEngine.start_run(
                db=db_session,
                user_id=setup_persistence_user.id,
                request="Process real PostgreSQL persisted request.",
                checkpointer=pg_checkpointer,
            )

        assert run.status == AgentRunStatus.AWAITING_APPROVAL

        # Verify checkpoint tuple can be retrieved directly from Postgres checkpointer
        tuple_state = await pg_checkpointer.aget_tuple(
            {"configurable": {"thread_id": run.thread_id}}
        )
        assert tuple_state is not None
        assert tuple_state.checkpoint["channel_values"]["run_id"] == str(run.id)

        # Phase 2: Resume execution using PostgreSQL checkpointer
        with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
            resumed_run = await WorkflowEngine.resume_run(
                db=db_session,
                run_id=run.id,
                user_id=setup_persistence_user.id,
                decision="approve",
                checkpointer=pg_checkpointer,
            )

        assert resumed_run.status == AgentRunStatus.COMPLETED


@pytest.mark.asyncio
async def test_run_and_event_record_consistency(
    db_session: AsyncSession,
    setup_persistence_user: User,
) -> None:
    """Verify consistency of relational AgentRun and AgentEvent audit records in PostgreSQL."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_persistence_generator()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_persistence_user.id,
            request="Audit trail verification request.",
            checkpointer=checkpointer,
        )

    # Fetch recorded events
    events_res = await db_session.execute(
        select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.timestamp.asc())
    )
    events = list(events_res.scalars().all())

    # Should contain intent_detected, plan_generated, approval_requested
    event_types = [e.event_type for e in events]
    assert "intent_detected" in event_types
    assert "plan_generated" in event_types
    assert "approval_requested" in event_types

    # Resume and verify approval_granted event recorded
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=setup_persistence_user.id,
            decision="approve",
            checkpointer=checkpointer,
        )

    events_res2 = await db_session.execute(
        select(AgentEvent).where(AgentEvent.run_id == run.id).order_by(AgentEvent.timestamp.asc())
    )
    events2 = list(events_res2.scalars().all())
    event_types2 = [e.event_type for e in events2]

    assert "approval_granted" in event_types2
    assert "step_executed" in event_types2
    assert "verification_completed" in event_types2
