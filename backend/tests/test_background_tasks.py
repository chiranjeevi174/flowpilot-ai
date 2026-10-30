"""Automated integration tests for Celery background tasks and atomic claiming."""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.llm.gateway import GatewayGenerationResult
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.services.llm import LLMService
from flowpilot.workers.tasks import execute_workflow_task
from flowpilot.workflows.dispatch import WorkflowDispatcher


def get_mock_gateway():
    """Mock gateway generator returning valid sequential agent responses."""
    intent_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "intent": "data_analysis",
                "action": "summarize",
                "requires_clarification": False,
                "is_actionable": True,
                "parameters": {},
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
                        "operation": "task_summary_generation",
                        "parameters": {"task_name": "quarterly_summary"},
                        "required_capability": "task_summary_generation",
                        "approval_required": False,
                        "expected_outcome": "Generated summary",
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
    tool_resp = GatewayGenerationResult(
        content=json.dumps({"summary": "Q4 sales increased 25%."}),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=20,
    )
    verifier_resp = GatewayGenerationResult(
        content=json.dumps(
            {
                "passed": True,
                "critique": "All metrics confirmed.",
                "missing_outputs": [],
                "needs_correction": False,
            }
        ),
        provider="gemini",
        model="gemini-2.5-flash",
        latency_ms=20,
    )

    async def _generate(*args, **kwargs):
        messages = kwargs.get("messages") or []
        sys_msg = messages[0].content if messages else ""
        if "Intent" in sys_msg:
            return intent_resp
        if "Planning" in sys_msg:
            return plan_resp
        if "Verification" in sys_msg:
            return verifier_resp
        return tool_resp

    return _generate


@pytest.fixture
async def user_with_creds(db_session: AsyncSession, registered_user: User) -> User:
    """Fixture ensuring registered user has active credentials."""
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
        await db_session.commit()
    return registered_user


@pytest.mark.asyncio
async def test_worker_execute_workflow_task_success(
    db_session: AsyncSession,
    user_with_creds: User,
) -> None:
    """Verify execute_workflow_task runs full LangGraph workflow and transitions to completed."""
    with patch("flowpilot.llm.gateway.gateway.generate", side_effect=get_mock_gateway()):
        run = await WorkflowDispatcher.create_and_dispatch_run(
            db=db_session,
            user_id=user_with_creds.id,
            request="Generate Q4 summary report.",
        )

        # In test mode with eager execution, the task was executed by dispatch.
        # Verify the terminal state in the database.
        await db_session.refresh(run)
        assert run.status == AgentRunStatus.COMPLETED

        # Re-executing a completed run skips claim
        result = execute_workflow_task(
            run_id_str=str(run.id),
            user_id_str=str(user_with_creds.id),
        )

    assert result["status"] in ("completed", "skipped")


@pytest.mark.asyncio
async def test_worker_duplicate_delivery_protection(
    db_session: AsyncSession,
    user_with_creds: User,
) -> None:
    """Verify that multiple concurrent or duplicate deliveries do not duplicate execution."""
    run_id = uuid.uuid4()
    thread_id = f"flowpilot_run_{run_id}"

    # Manually create a run in completed status
    agent_run = AgentRun(
        id=run_id,
        user_id=user_with_creds.id,
        thread_id=thread_id,
        original_request="Test run already finished.",
        status=AgentRunStatus.COMPLETED,
    )
    db_session.add(agent_run)
    await db_session.commit()

    # Celery duplicate task delivery arrives
    res = execute_workflow_task(
        run_id_str=str(run_id),
        user_id_str=str(user_with_creds.id),
    )

    # Worker skips claiming completed run
    assert res["status"] == "completed"


@pytest.mark.asyncio
async def test_worker_cancelled_run_claim_rejection(
    db_session: AsyncSession,
    user_with_creds: User,
) -> None:
    """Verify worker detects cancellation_requested and transitions run to cancelled."""
    run_id = uuid.uuid4()
    thread_id = f"flowpilot_run_{run_id}"

    # Create run with cancellation_requested=True
    agent_run = AgentRun(
        id=run_id,
        user_id=user_with_creds.id,
        thread_id=thread_id,
        original_request="Doomed execution.",
        status=AgentRunStatus.QUEUED,
        cancellation_requested=True,
    )
    db_session.add(agent_run)
    await db_session.commit()

    res = execute_workflow_task(
        run_id_str=str(run_id),
        user_id_str=str(user_with_creds.id),
    )

    assert res["status"] == "cancelled"

    await db_session.refresh(agent_run)
    assert agent_run.status == AgentRunStatus.CANCELLED
