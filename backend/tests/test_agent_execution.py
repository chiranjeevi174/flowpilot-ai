"""Automated tests for Execution Agent, internal tools, idempotency, and workflow engine."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.executor import execute_plan_node
from flowpilot.agents.state import AgentState
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.workflows.engine import WorkflowEngine
from flowpilot.workflows.tools import (
    execute_information_extraction,
    execute_response_drafting,
    execute_task_summary_generation,
    execute_text_categorization,
)


@pytest.fixture
async def setup_execution_user(db_session: AsyncSession, registered_user: User) -> User:
    """Setup active credential and preference for the test user."""
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


@pytest.fixture
async def sample_run(db_session: AsyncSession, registered_user: User) -> AgentRun:
    """Create a sample AgentRun in database."""
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="thread_exec_test",
        original_request="Analyze customer complaint and summarize.",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_internal_tool_text_categorization(
    db_session: AsyncSession, setup_execution_user: User
) -> None:
    """Verify safe internal text categorization tool."""
    mock_res = GatewayGenerationResult(
        content=json.dumps({"sentiment": "negative", "urgency": "high"}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=80,
    )

    with patch(
        "flowpilot.workflows.tools.gateway.generate", new_callable=AsyncMock, return_value=mock_res
    ):
        out = await execute_text_categorization(
            db=db_session,
            user_id=setup_execution_user.id,
            parameters={"text": "Service is completely down!"},
        )

    assert out["operation"] == "text_categorization"
    assert out["result"]["sentiment"] == "negative"
    assert out["result"]["urgency"] == "high"


@pytest.mark.asyncio
async def test_internal_tool_information_extraction(
    db_session: AsyncSession, setup_execution_user: User
) -> None:
    """Verify safe structured information extraction tool."""
    mock_res = GatewayGenerationResult(
        content=json.dumps({"customer_name": "Alice", "specific_issues": ["billing error"]}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=90,
    )

    with patch(
        "flowpilot.workflows.tools.gateway.generate", new_callable=AsyncMock, return_value=mock_res
    ):
        out = await execute_information_extraction(
            db=db_session,
            user_id=setup_execution_user.id,
            parameters={"text": "Alice reported an unexpected charge on her bill."},
        )

    assert out["operation"] == "information_extraction"
    assert out["result"]["customer_name"] == "Alice"
    assert "billing error" in out["result"]["specific_issues"]


@pytest.mark.asyncio
async def test_internal_tool_response_drafting(
    db_session: AsyncSession, setup_execution_user: User
) -> None:
    """Verify safe response drafting tool."""
    mock_res = GatewayGenerationResult(
        content=json.dumps({"subject": "We are resolving your issue", "body": "Dear customer..."}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    with patch(
        "flowpilot.workflows.tools.gateway.generate", new_callable=AsyncMock, return_value=mock_res
    ):
        out = await execute_response_drafting(
            db=db_session,
            user_id=setup_execution_user.id,
            parameters={"context": "Customer complaint"},
        )

    assert out["operation"] == "response_drafting"
    assert "resolving" in out["result"]["subject"]


@pytest.mark.asyncio
async def test_internal_tool_task_summary_generation(
    db_session: AsyncSession, setup_execution_user: User
) -> None:
    """Verify safe task summary generation tool."""
    mock_res = GatewayGenerationResult(
        content=json.dumps({"summary": "Issue resolved.", "key_highlights": ["refund issued"]}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=75,
    )

    with patch(
        "flowpilot.workflows.tools.gateway.generate", new_callable=AsyncMock, return_value=mock_res
    ):
        out = await execute_task_summary_generation(
            db=db_session,
            user_id=setup_execution_user.id,
            parameters={"text": "Complete history"},
        )

    assert out["operation"] == "task_summary_generation"
    assert out["result"]["summary"] == "Issue resolved."


@pytest.mark.asyncio
async def test_executor_node_sequential_execution(
    db_session: AsyncSession,
    setup_execution_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Execution Agent executes plan steps sequentially and tracks executed steps."""
    mock_cat = GatewayGenerationResult(
        content=json.dumps({"category": "complaint"}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    mock_ext = GatewayGenerationResult(
        content=json.dumps({"entities": ["service"]}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    async def mock_tool_generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        prompt = messages[1].content if len(messages) > 1 else ""
        if "categorization" in prompt:
            return mock_cat
        return mock_ext

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_execution_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "execution_plan": [
            {
                "step_id": "step_1",
                "operation": "text_categorization",
                "parameters": {"text": "Slow response"},
            },
            {
                "step_id": "step_2",
                "operation": "information_extraction",
                "parameters": {"text": "Slow response"},
            },
        ],
        "executed_step_ids": [],
        "step_results": [],
    }

    with patch("flowpilot.workflows.tools.gateway.generate", side_effect=mock_tool_generate):
        update = await execute_plan_node(state)

    assert update["execution_status"] == "running"
    assert len(update["step_results"]) == 2
    assert "step_1" in update["executed_step_ids"]
    assert "step_2" in update["executed_step_ids"]

    # Verify event audit trail in database
    events_res = await db_session.execute(
        select(AgentEvent).where(AgentEvent.run_id == sample_run.id)
    )
    events = list(events_res.scalars().all())
    executed_events = [e for e in events if e.event_type == "step_executed"]
    assert len(executed_events) == 2


@pytest.mark.asyncio
async def test_executor_node_idempotency_skip(
    db_session: AsyncSession,
    setup_execution_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Execution Agent skips already-executed steps (replay protection)."""
    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_execution_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "execution_plan": [
            {
                "step_id": "step_1",
                "operation": "text_categorization",
                "parameters": {"text": "Fast"},
            },
            {
                "step_id": "step_2",
                "operation": "task_summary_generation",
                "parameters": {"text": "Summary"},
            },
        ],
        "executed_step_ids": ["step_1"],  # step_1 already completed
        "step_results": [
            {"step_id": "step_1", "operation": "text_categorization", "status": "success"}
        ],
    }

    mock_summary = GatewayGenerationResult(
        content=json.dumps({"summary": "Done"}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    with patch(
        "flowpilot.workflows.tools.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_summary,
    ):
        update = await execute_plan_node(state)

    # step_1 must not be executed again; only step_2 was added
    assert len(update["step_results"]) == 2
    assert update["step_results"][0]["step_id"] == "step_1"
    assert update["step_results"][1]["step_id"] == "step_2"


@pytest.mark.asyncio
async def test_workflow_engine_end_to_end_execution(
    db_session: AsyncSession,
    setup_execution_user: User,
) -> None:
    """Verify WorkflowEngine runs full workflow, updates DB to COMPLETED, and stores results."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "analysis",
                "action": "categorize",
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
                        "operation": "text_categorization",
                        "parameters": {"text": "Excellent support."},
                        "required_capability": "text_categorization",
                        "approval_required": False,
                        "expected_outcome": "Sentiment",
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
        content=json.dumps({"sentiment": "positive"}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "All tasks verified successfully",
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

    checkpointer = MemorySaver()

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gateway_generate):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_execution_user.id,
            request="Categorize customer feedback.",
            checkpointer=checkpointer,
        )

    assert run.status == AgentRunStatus.COMPLETED
    assert run.final_result is not None
    assert run.final_result["status"] == "completed"
    assert run.completed_at is not None
    assert run.error_message is None
