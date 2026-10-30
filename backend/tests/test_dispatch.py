"""Automated tests for durable transactional outbox dispatch and failure recovery."""

import uuid
from unittest.mock import patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.models.workflow_outbox import OutboxStatus, WorkflowOutbox
from flowpilot.workers.recovery import RecoveryService
from flowpilot.workflows.dispatch import WorkflowDispatcher


@pytest.mark.asyncio
async def test_transactional_outbox_persists_with_agent_run(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify dispatching creates both an AgentRun and outbox entry atomically."""
    # Mock dispatch_outbox_entry so it doesn't immediately dispatch
    with patch.object(WorkflowDispatcher, "try_dispatch_outbox_entry", return_value=True):
        run = await WorkflowDispatcher.create_and_dispatch_run(
            db=db_session,
            user_id=registered_user.id,
            request="Audit inventory records.",
        )

    assert run.id is not None
    assert run.status == AgentRunStatus.QUEUED

    # Check outbox record
    res = await db_session.execute(select(WorkflowOutbox).where(WorkflowOutbox.run_id == run.id))
    outbox = res.scalar_one_or_none()
    assert outbox is not None
    assert outbox.task_type == "start_run"
    assert outbox.status == OutboxStatus.PENDING
    assert outbox.payload["user_id"] == str(registered_user.id)


@pytest.mark.asyncio
async def test_redis_broker_outage_preserves_committed_request(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify that if broker raises an exception, the outbox record retries."""
    with patch(
        "flowpilot.workers.tasks.execute_workflow_task.delay",
        side_effect=ConnectionError("Redis connection refused"),
    ):
        run = await WorkflowDispatcher.create_and_dispatch_run(
            db=db_session,
            user_id=registered_user.id,
            request="Process payments asynchronously.",
        )

    # Run was still committed in PostgreSQL
    assert run.id is not None
    assert run.status == AgentRunStatus.QUEUED

    # Outbox is marked PENDING with incremented retry count
    res = await db_session.execute(select(WorkflowOutbox).where(WorkflowOutbox.run_id == run.id))
    outbox = res.scalar_one()
    assert outbox.status == OutboxStatus.PENDING
    assert outbox.retry_count == 1
    assert "Redis connection refused" in (outbox.last_error or "")


@pytest.mark.asyncio
async def test_outbox_recovery_sweep_republishes_pending_entries(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify RecoveryService sweeps stuck pending outbox entries and republishes them."""
    run_id = uuid.uuid4()
    thread_id = f"flowpilot_run_{run_id}"

    agent_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=thread_id,
        original_request="Stuck request waiting for recovery.",
        status=AgentRunStatus.QUEUED,
    )
    db_session.add(agent_run)

    stuck_outbox = WorkflowOutbox(
        run_id=run_id,
        task_type="start_run",
        payload={
            "run_id": str(run_id),
            "user_id": str(registered_user.id),
        },
        status=OutboxStatus.PENDING,
        retry_count=1,
    )
    db_session.add(stuck_outbox)
    await db_session.commit()

    # Run recovery sweep with working Celery delay
    with patch("flowpilot.workers.tasks.execute_workflow_task.delay") as mock_delay:
        recovered_count = await RecoveryService.recover_stuck_outbox(
            db=db_session, max_age_seconds=0
        )
        assert recovered_count >= 1
        assert mock_delay.called

    # Outbox status updated to DISPATCHED
    await db_session.refresh(stuck_outbox)
    assert stuck_outbox.status == OutboxStatus.DISPATCHED
    assert stuck_outbox.dispatched_at is not None
