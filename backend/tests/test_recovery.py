"""Automated tests for crash recovery, abandoned run sweep, and outbox failure thresholds."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.user import User
from flowpilot.workers.recovery import RecoveryService


@pytest.mark.asyncio
async def test_recover_abandoned_run_requeues_or_fails(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify that a worker crash leaving a run in RUNNING with expired heartbeat is recovered."""
    run_id = uuid.uuid4()
    expired_heartbeat = datetime.now(UTC) - timedelta(minutes=10)

    stranded_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Job interrupted by power outage.",
        status=AgentRunStatus.RUNNING,
        locked_by="crashed_worker_node_1",
        heartbeat_at=expired_heartbeat,
        retry_count=0,
    )
    db_session.add(stranded_run)
    await db_session.commit()

    with patch("flowpilot.workers.tasks.execute_workflow_task.delay") as mock_delay:
        recovered_count = await RecoveryService.recover_abandoned_runs(
            db=db_session,
            heartbeat_timeout_seconds=300,
        )
        assert recovered_count >= 1
        assert mock_delay.called

    await db_session.refresh(stranded_run)
    # With retry_count < max_retries, it should be re-queued
    assert stranded_run.status == AgentRunStatus.QUEUED
    assert stranded_run.locked_by is None
    assert stranded_run.retry_count == 1


@pytest.mark.asyncio
async def test_recover_abandoned_run_exhausted_retries_marks_failed(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify that a repeatedly crashing run exceeding retry threshold transitions to FAILED."""
    run_id = uuid.uuid4()
    expired_heartbeat = datetime.now(UTC) - timedelta(minutes=15)

    fatally_failing_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Repeated segfault trigger.",
        status=AgentRunStatus.RUNNING,
        locked_by="crashed_worker_node_2",
        heartbeat_at=expired_heartbeat,
        retry_count=2,  # Already at max_retries
    )
    db_session.add(fatally_failing_run)
    await db_session.commit()

    recovered_count = await RecoveryService.recover_abandoned_runs(
        db=db_session,
        heartbeat_timeout_seconds=300,
    )
    assert recovered_count >= 1

    await db_session.refresh(fatally_failing_run)
    assert fatally_failing_run.status == AgentRunStatus.FAILED
    assert fatally_failing_run.completed_at is not None
    assert "heartbeat timed out" in (fatally_failing_run.error_message or "")


@pytest.mark.asyncio
async def test_recover_stuck_outbox_exhausted_retries_marks_run_failed(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify that permanent outbox delivery failure marks the linked run as FAILED."""
    from flowpilot.models.workflow_outbox import OutboxStatus, WorkflowOutbox
    from flowpilot.services.monitoring import MonitoringService

    run_id = uuid.uuid4()
    queued_run = AgentRun(
        id=run_id,
        user_id=registered_user.id,
        thread_id=f"flowpilot_run_{run_id}",
        original_request="Task with failing broker dispatch.",
        status=AgentRunStatus.QUEUED,
    )
    db_session.add(queued_run)

    stuck_outbox = WorkflowOutbox(
        run_id=run_id,
        task_type="start_run",
        payload={"run_id": str(run_id), "user_id": str(registered_user.id)},
        status=OutboxStatus.PENDING,
        retry_count=5,  # Matches or exceeds OUTBOX_MAX_RETRIES (5)
        created_at=datetime.now(UTC) - timedelta(seconds=60),
    )
    db_session.add(stuck_outbox)
    await db_session.commit()

    recovered_count = await RecoveryService.recover_stuck_outbox(
        db=db_session,
        max_age_seconds=5,
    )
    # Exceeded retries are not dispatched, so recovered_count is 0
    assert recovered_count == 0

    await db_session.refresh(stuck_outbox)
    await db_session.refresh(queued_run)

    assert stuck_outbox.status == OutboxStatus.FAILED
    assert "Exceeded max retries" in (stuck_outbox.last_error or "")

    # Crucial Phase 5 hardening check: run is not left queued forever
    assert queued_run.status == AgentRunStatus.FAILED
    assert queued_run.completed_at is not None
    assert "permanently failed" in (queued_run.error_message or "")

    # Verify monitoring visibility
    health = await MonitoringService.get_system_health(db_session)
    assert health.failed_outbox_count >= 1
