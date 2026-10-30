"""Unit and integration tests for LangGraph StateGraph, agent nodes, and routing."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.graph import create_agent_graph
from flowpilot.agents.intent import analyze_intent_node
from flowpilot.agents.planner import plan_workflow_node
from flowpilot.agents.state import AgentState
from flowpilot.agents.verifier import verify_execution_node
from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User


@pytest.fixture
async def setup_agent_user(db_session: AsyncSession, registered_user: User) -> User:
    """Configure mock LLM credentials and preference for testing."""
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
    """Provide a database AgentRun instance."""
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test_thread_1",
        original_request="Analyze customer feedback and draft a response.",
        status=AgentRunStatus.RUNNING,
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)
    return run


@pytest.mark.asyncio
async def test_intent_node_success(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Intent Analysis Agent extracts valid structured intent and logs audit event."""
    mock_payload = {
        "intent": "customer_support",
        "action": "prepare_response",
        "requires_clarification": False,
        "is_actionable": True,
        "parameters": {"task": "analyze_complaint"},
        "clarification_message": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=120,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        update = await analyze_intent_node(state)

    assert update["execution_status"] == "running"
    assert update["detected_intent"]["intent"] == "customer_support"
    assert update["detected_intent"]["action"] == "prepare_response"
    assert update["current_step"] == 1


@pytest.mark.asyncio
async def test_intent_node_unactionable_clarification(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Intent Analysis Agent stops execution when a request requires clarification."""
    mock_payload = {
        "intent": "unknown",
        "action": "none",
        "requires_clarification": True,
        "is_actionable": False,
        "parameters": {},
        "clarification_message": "Please specify which customer complaint you want analyzed.",
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_payload),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": "Do that thing.",
        "current_step": 0,
    }

    with patch(
        "flowpilot.agents.intent.gateway.generate", new_callable=AsyncMock, return_value=mock_result
    ):
        update = await analyze_intent_node(state)

    assert update["execution_status"] == "failed"
    assert "clarification_needed" in update["final_response"]["status"]
    assert "specify" in update["error_details"].lower()


@pytest.mark.asyncio
async def test_planner_node_valid_plan(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Planning Agent constructs a validated sequence of allowed internal operations."""
    mock_plan = {
        "steps": [
            {
                "step_id": "step_1",
                "operation": "information_extraction",
                "parameters": {"text": "Customer was delayed for 3 hours."},
                "required_capability": "information_extraction",
                "approval_required": False,
                "expected_outcome": "Extracted delay details",
            },
            {
                "step_id": "step_2",
                "operation": "response_drafting",
                "parameters": {"tone": "apologetic"},
                "required_capability": "response_drafting",
                "approval_required": True,
                "expected_outcome": "Drafted apology letter",
            },
        ],
        "unsupported_capability": False,
        "unsupported_reason": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_plan),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=150,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "detected_intent": {"intent": "customer_support", "action": "prepare_response"},
    }

    with patch(
        "flowpilot.agents.planner.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await plan_workflow_node(state)

    assert update["execution_status"] == "running"
    assert len(update["execution_plan"]) == 2
    assert update["execution_plan"][0]["operation"] == "information_extraction"
    assert update["execution_plan"][1]["operation"] == "response_drafting"
    assert update["execution_plan"][1]["approval_required"] is True


@pytest.mark.asyncio
async def test_planner_backend_approval_policy_enforcement(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify backend approval policy overrides LLM proposal for sensitive operations."""
    # LLM attempts to bypass approval by setting approval_required=False
    mock_plan = {
        "steps": [
            {
                "step_id": "step_1",
                "operation": "response_drafting",
                "parameters": {"text": "Apology"},
                "required_capability": "response_drafting",
                "approval_required": False,  # Bypassed by LLM
                "expected_outcome": "Drafted message",
            }
        ],
        "unsupported_capability": False,
        "unsupported_reason": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_plan),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "detected_intent": {"intent": "support"},
    }

    with patch(
        "flowpilot.agents.planner.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await plan_workflow_node(state)

    # Backend policy must have forced approval_required=True
    assert update["execution_plan"][0]["approval_required"] is True


@pytest.mark.asyncio
async def test_planner_unsupported_capability_rejection(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Planning Agent rejects requests demanding unavailable external integrations."""
    mock_plan = {
        "steps": [],
        "unsupported_capability": True,
        "unsupported_reason": "Sending actual Slack messages or phone calls is not supported.",
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_plan),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=90,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": "Send a Slack message and make a phone call to the client.",
        "detected_intent": {"intent": "external_communication"},
    }

    with patch(
        "flowpilot.agents.planner.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await plan_workflow_node(state)

    assert update["execution_status"] == "failed"
    assert "Slack" in update["error_details"]
    assert update["final_response"]["error"] == "UnsupportedCapabilityError"


@pytest.mark.asyncio
async def test_planner_disallowed_capability_rejection(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Planning Agent rejects operations not in allowlist."""
    mock_plan = {
        "steps": [
            {
                "step_id": "step_1",
                "operation": "execute_shell_command",  # Arbitrary unauthorized capability
                "parameters": {"cmd": "ls"},
                "required_capability": "shell",
                "approval_required": False,
                "expected_outcome": "Directory listing",
            }
        ],
        "unsupported_capability": False,
        "unsupported_reason": None,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_plan),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=100,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": "List my files.",
        "detected_intent": {"intent": "system"},
    }

    with patch(
        "flowpilot.agents.planner.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await plan_workflow_node(state)

    assert update["execution_status"] == "failed"
    assert update["final_response"]["error"] == "DisallowedCapabilityError"
    assert "execute_shell_command" in update["error_details"]


@pytest.mark.asyncio
async def test_verifier_node_success(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Verification Agent confirms successful execution completion."""
    mock_verification = {
        "passed": True,
        "critique": "All objectives and deliverables were completed accurately.",
        "missing_outputs": [],
        "needs_correction": False,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_verification),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=110,
    )

    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "execution_plan": [{"step_id": "step_1", "operation": "information_extraction"}],
        "step_results": [
            {
                "step_id": "step_1",
                "operation": "information_extraction",
                "status": "success",
                "result": {"data": 123},
            }
        ],
        "correction_attempts": 0,
    }

    with patch(
        "flowpilot.agents.verifier.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await verify_execution_node(state)

    assert update["execution_status"] == "completed"
    assert update["verification_result"]["passed"] is True
    assert update["final_response"]["status"] == "completed"


@pytest.mark.asyncio
async def test_verifier_bounded_correction(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify Verification Agent triggers bounded correction loops and halts after max attempts."""
    mock_failed_verification = {
        "passed": False,
        "critique": "Draft was incomplete.",
        "missing_outputs": ["step_2"],
        "needs_correction": True,
    }

    mock_result = GatewayGenerationResult(
        content=json.dumps(mock_failed_verification),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=90,
    )

    # 1. First failure triggers correction loop
    state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "execution_plan": [{"step_id": "step_1", "operation": "text_categorization"}],
        "step_results": [
            {"step_id": "step_1", "operation": "text_categorization", "status": "success"}
        ],
        "correction_attempts": 0,
    }

    with patch(
        "flowpilot.agents.verifier.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update = await verify_execution_node(state)

    assert update["execution_status"] == "running"
    assert update["correction_attempts"] == 1

    # 2. Second failure when at max attempts terminates with failed status
    state["correction_attempts"] = 2
    with patch(
        "flowpilot.agents.verifier.gateway.generate",
        new_callable=AsyncMock,
        return_value=mock_result,
    ):
        update_exhausted = await verify_execution_node(state)

    assert update_exhausted["execution_status"] == "failed"
    assert "Verification failed" in update_exhausted["error_details"]


@pytest.mark.asyncio
async def test_agent_graph_orchestration_flow(
    db_session: AsyncSession,
    setup_agent_user: User,
    sample_run: AgentRun,
) -> None:
    """Verify end-to-end routing through compiled StateGraph with in-memory checkpointer."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "analysis",
                "action": "summarize",
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
                        "parameters": {"text": "Simple test string"},
                        "required_capability": "text_categorization",
                        "approval_required": False,
                        "expected_outcome": "Categories",
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
        content=json.dumps({"sentiment": "positive", "confidence": 0.95}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Summary complete",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )

    async def mock_gateway_generate(*args, **kwargs):
        # Route mock response based on messages system prompt
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
    graph = create_agent_graph(checkpointer=checkpointer)

    initial_state: AgentState = {
        "run_id": str(sample_run.id),
        "user_id": str(setup_agent_user.id),
        "thread_id": sample_run.thread_id,
        "original_request": sample_run.original_request,
        "current_step": 0,
        "step_results": [],
        "executed_step_ids": [],
        "approval_status": "pending",
        "execution_status": "running",
        "correction_attempts": 0,
    }

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gateway_generate):
        final_state = await graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": sample_run.thread_id}},
        )

    assert final_state["execution_status"] == "completed"
    assert len(final_state["step_results"]) == 1
    assert final_state["step_results"][0]["operation"] == "text_categorization"
    assert final_state["verification_result"]["passed"] is True
