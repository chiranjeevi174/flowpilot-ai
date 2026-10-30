"""Automated tests for Human-in-the-Loop approval gate, interrupt semantics, and resumption."""

import json
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import MemorySaver
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRunStatus
from flowpilot.models.user import User
from flowpilot.services.agents import AgentService, RunAccessDeniedError
from flowpilot.workflows.engine import WorkflowEngine


@pytest.fixture
async def setup_approval_user(db_session: AsyncSession, registered_user: User) -> User:
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


def get_mock_generator(requires_approval: bool = True):
    """Return a mock gateway generator function configured for approval testing."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "customer_support",
                "action": "prepare_response",
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
                        "operation": "response_drafting",  # Sensitive -> triggers approval
                        "parameters": {"context": "Customer complaint details"},
                        "required_capability": "response_drafting",
                        "approval_required": requires_approval,
                        "expected_outcome": "Drafted communication",
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
        content=json.dumps({"subject": "Resolution", "body": "We apologize..."}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=50,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "Draft verified.",
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
async def test_approval_gate_interrupts_for_sensitive_action(
    db_session: AsyncSession,
    setup_approval_user: User,
) -> None:
    """Verify sensitive planned operation triggers an interrupt and enters awaiting_approval."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_generator(requires_approval=True)

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_approval_user.id,
            request="Draft an apology letter to the customer.",
            checkpointer=checkpointer,
        )

    # Must be paused in awaiting_approval
    assert run.status == AgentRunStatus.AWAITING_APPROVAL
    assert run.execution_plan is not None
    assert len(run.execution_plan) == 1
    assert run.completed_at is None


@pytest.mark.asyncio
async def test_approval_gate_resumed_with_approval(
    db_session: AsyncSession,
    setup_approval_user: User,
) -> None:
    """Verify that approving a paused run resumes execution and finishes in COMPLETED state."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_generator(requires_approval=True)

    # 1. Start run and pause at approval gate
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_approval_user.id,
            request="Draft an apology letter to the customer.",
            checkpointer=checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    # 2. Submit approval decision
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        resumed_run = await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=setup_approval_user.id,
            decision="approve",
            comment="Looks good, proceed.",
            checkpointer=checkpointer,
        )

    assert resumed_run.status == AgentRunStatus.COMPLETED
    assert resumed_run.completed_at is not None
    assert resumed_run.final_result is not None


@pytest.mark.asyncio
async def test_approval_gate_resumed_with_rejection(
    db_session: AsyncSession,
    setup_approval_user: User,
) -> None:
    """Verify that rejecting a paused run aborts execution and marks status REJECTED."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_generator(requires_approval=True)

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_approval_user.id,
            request="Draft an apology letter to the customer.",
            checkpointer=checkpointer,
        )

    assert run.status == AgentRunStatus.AWAITING_APPROVAL

    # Submit rejection decision
    resumed_run = await WorkflowEngine.resume_run(
        db=db_session,
        run_id=run.id,
        user_id=setup_approval_user.id,
        decision="reject",
        comment="Do not send communications to this customer.",
        checkpointer=checkpointer,
    )

    assert resumed_run.status == AgentRunStatus.REJECTED
    assert resumed_run.completed_at is not None
    assert "rejected" in resumed_run.error_message.lower()


@pytest.mark.asyncio
async def test_duplicate_approval_rejected(
    db_session: AsyncSession,
    setup_approval_user: User,
) -> None:
    """Verify that submitting an approval for a run not awaiting approval raises an error."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_generator(requires_approval=True)

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_approval_user.id,
            request="Draft an apology letter to the customer.",
            checkpointer=checkpointer,
        )

    # Approve once
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=setup_approval_user.id,
            decision="approve",
            checkpointer=checkpointer,
        )

    # Attempt second approval on now-completed run
    with pytest.raises(ValueError, match="awaiting_approval"):
        await WorkflowEngine.resume_run(
            db=db_session,
            run_id=run.id,
            user_id=setup_approval_user.id,
            decision="approve",
            checkpointer=checkpointer,
        )


@pytest.mark.asyncio
async def test_unauthorized_user_cannot_approve(
    db_session: AsyncSession,
    setup_approval_user: User,
    second_user: User,
) -> None:
    """Verify that User B cannot approve a run owned by User A."""
    checkpointer = MemorySaver()
    mock_gen = get_mock_generator(requires_approval=True)

    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        run = await WorkflowEngine.start_run(
            db=db_session,
            user_id=setup_approval_user.id,
            request="Draft an apology letter.",
            checkpointer=checkpointer,
        )

    # User B attempts to approve User A's run via service
    with pytest.raises(RunAccessDeniedError):
        await AgentService.approve_run(
            db=db_session,
            run_id=run.id,
            user_id=second_user.id,
            checkpointer=checkpointer,
        )


def test_api_approval_and_rejection_flow(
    client: TestClient,
    setup_approval_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify approval and rejection through FastAPI REST endpoints."""
    mock_gen = get_mock_generator(requires_approval=True)

    # 1. Start a run via API
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        start_res = client.post(
            "/api/v1/agents/runs",
            json={"request": "Draft customer reply."},
            headers=auth_headers,
        )
    assert start_res.status_code in (200, 201, 202)
    run_data = start_res.json()
    run_id = run_data["id"]
    assert run_data["status"] == "awaiting_approval"

    # 2. Approve via API
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=mock_gen):
        approve_res = client.post(
            f"/api/v1/agents/runs/{run_id}/approve",
            json={"comment": "Approved by supervisor."},
            headers=auth_headers,
        )
    assert approve_res.status_code == 200
    approved_data = approve_res.json()
    assert approved_data["status"] == "completed"

    # 3. Second approval attempt returns 409 Conflict
    dup_res = client.post(
        f"/api/v1/agents/runs/{run_id}/approve",
        headers=auth_headers,
    )
    assert dup_res.status_code == 409
