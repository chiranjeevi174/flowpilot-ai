"""Automated tests for cooperative workflow cancellation and lifecycle termination."""

import uuid
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.services.agents import AgentService


@pytest.mark.asyncio
async def test_cancel_queued_run_transitions_to_cancelled(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify cancelling a queued run directly transitions status to CANCELLED."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Cancel before start.",
        status=AgentRunStatus.QUEUED,
    )
    db_session.add(agent_run)
    await db_session.commit()

    cancelled = await AgentService.cancel_run(
        db=db_session,
        run_id=run_id,
        user_id=registered_user.id,
    )

    assert cancelled.status == AgentRunStatus.CANCELLED
    assert cancelled.cancellation_requested is True
    assert cancelled.completed_at is not None


@pytest.mark.asyncio
async def test_cancel_awaiting_approval_run(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify cancelling a run paused in awaiting_approval transitions immediately to CANCELLED."""
    run_id = uuid.uuid4()
    agent_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Sensitive operation waiting for approval.",
        status=AgentRunStatus.AWAITING_APPROVAL,
    )
    db_session.add(agent_run)
    await db_session.commit()

    cancelled = await AgentService.cancel_run(
        db=db_session,
        run_id=run_id,
        user_id=registered_user.id,
    )

    assert cancelled.status == AgentRunStatus.CANCELLED
    assert cancelled.cancellation_requested is True


def test_api_cancel_run_endpoint_and_idempotency(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify POST /api/v1/agents/runs/{id}/cancel cancels run and repeated calls are idempotent."""
    # 1. Create a run via API
    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        start_res = client.post(
            "/api/v1/agents/runs",
            json={"request": "Execution to be cancelled."},
            headers=auth_headers,
        )
    assert start_res.status_code == 202
    run_id = start_res.json()["id"]

    # 2. Cancel run
    cancel_res = client.post(f"/api/v1/agents/runs/{run_id}/cancel", headers=auth_headers)
    assert cancel_res.status_code == 200
    cancel_data = cancel_res.json()
    assert cancel_data["status"] == "cancelled"

    # 3. Repeat cancel call (idempotent)
    repeat_res = client.post(f"/api/v1/agents/runs/{run_id}/cancel", headers=auth_headers)
    assert repeat_res.status_code == 200
    assert repeat_res.json()["status"] == "cancelled"


def test_api_cancel_cross_user_isolation(
    client: TestClient,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot cancel User A's execution run."""
    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        start_res = client.post(
            "/api/v1/agents/runs",
            json={"request": "User A protected execution."},
            headers=auth_headers,
        )
    run_id = start_res.json()["id"]

    cancel_res = client.post(f"/api/v1/agents/runs/{run_id}/cancel", headers=second_auth_headers)
    assert cancel_res.status_code == 404
