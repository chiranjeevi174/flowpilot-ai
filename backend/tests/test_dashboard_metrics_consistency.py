"""Regression tests for dashboard metrics, approval state, and schedule lifecycle.

Verifies:
- Approval Metrics (awaiting, approved, rejected, cancelled, completed historical,
  failed stale, multi-user isolation)
- Scheduling Metrics (one-time active vs consumed, history retention, paused exclusion,
  recurring active, duplicate prevention)
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.models.user import User
from flowpilot.services.agents import AgentService
from flowpilot.services.monitoring import MonitoringService
from flowpilot.services.scheduling import SchedulingService
from flowpilot.workers.scheduler import SchedulerService

# =========================================================================
# PART B & G: APPROVAL METRICS REGRESSION TESTS
# =========================================================================


@pytest.mark.asyncio
async def test_awaiting_approval_run_is_counted(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """1. An awaiting-approval run is counted in dashboard metrics and matches list_runs."""
    plan = [{"step_id": "step_1", "operation": "gmail_send_message", "approval_required": True}]
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-1",
        original_request="Send confidential email to board",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=plan,
    )
    db_session.add(run)
    await db_session.commit()

    # Verify MonitoringService scoped to user
    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 1

    # Verify REST endpoint
    res = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert res.status_code == 200
    assert res.json()["runs_by_status"]["awaiting_approval"] == 1

    # Verify Approvals page endpoint returns identical count
    runs_res = client.get("/api/v1/agents/runs?status=awaiting_approval", headers=auth_headers)
    assert runs_res.status_code == 200
    assert runs_res.json()["total"] == 1
    assert len(runs_res.json()["items"]) == 1


@pytest.mark.asyncio
async def test_approved_and_resumed_run_is_no_longer_pending(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """2. An approved action is no longer pending in dashboard counter."""
    plan = [{"step_id": "step_1", "operation": "gmail_send_message", "approval_required": True}]
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-2",
        original_request="Send report",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=plan,
    )
    db_session.add(run)
    await db_session.commit()

    # User approves
    with patch("flowpilot.workflows.dispatch.WorkflowDispatcher.try_dispatch_outbox_entry"):
        approve_res = client.post(
            f"/api/v1/agents/runs/{run.id}/approve",
            json={"comment": "Approved by compliance"},
            headers=auth_headers,
        )
        assert approve_res.status_code == 200

    # Dashboard counter should now be 0
    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 0

    api_res = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert api_res.json()["runs_by_status"]["awaiting_approval"] == 0


@pytest.mark.asyncio
async def test_rejected_action_is_no_longer_pending(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """3. A rejected action is terminated and no longer pending."""
    plan = [{"step_id": "step_1", "operation": "slack_post_message", "approval_required": True}]
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-3",
        original_request="Broadcast notification",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=plan,
    )
    db_session.add(run)
    await db_session.commit()

    with patch("flowpilot.workflows.dispatch.WorkflowDispatcher.try_dispatch_outbox_entry"):
        reject_res = client.post(
            f"/api/v1/agents/runs/{run.id}/reject",
            json={"comment": "Broadcast rejected"},
            headers=auth_headers,
        )
        assert reject_res.status_code == 200

    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 0


@pytest.mark.asyncio
async def test_cancelled_workflow_is_excluded(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """4. A cancelled workflow run is excluded from pending approvals."""
    plan = [{"step_id": "step_1", "operation": "test_op", "approval_required": True}]
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-4",
        original_request="Test cancel",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=plan,
    )
    db_session.add(run)
    await db_session.commit()

    # Cancel run
    cancel_res = client.post(f"/api/v1/agents/runs/{run.id}/cancel", headers=auth_headers)
    assert cancel_res.status_code == 200

    # Ensure excluded from dashboard and approvals
    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 0

    runs_res = client.get("/api/v1/agents/runs?status=awaiting_approval", headers=auth_headers)
    assert runs_res.json()["total"] == 0


@pytest.mark.asyncio
async def test_completed_workflow_with_historical_approvals_is_excluded(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """5. Completed workflow is excluded even if it previously had approval requirements."""
    now_utc = datetime.now(UTC)
    plan = [
        {
            "step_id": "step_1",
            "operation": "gmail_send_message",
            "approval_required": True,
            "status": "approved",
        }
    ]
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-5",
        original_request="Historical completed run",
        status=AgentRunStatus.COMPLETED,
        current_step=1,
        execution_plan=plan,
        completed_at=now_utc,
    )
    db_session.add(run)
    await db_session.commit()

    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 0


@pytest.mark.asyncio
async def test_failed_workflow_with_stale_status_is_excluded(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """6. A failed workflow or run without execution plan is excluded from actionable approvals."""
    # Stale run that failed during intent analysis with plan=None
    run = AgentRun(
        user_id=registered_user.id,
        thread_id="test-thread-6",
        original_request="Broken run",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=None,  # No plan!
    )
    db_session.add(run)
    await db_session.commit()

    count = await AgentService.count_pending_approvals(db_session, user_id=registered_user.id)
    assert count == 0

    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.runs_by_status["awaiting_approval"] == 0


@pytest.mark.asyncio
async def test_another_users_approvals_are_excluded(
    client: TestClient,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """7 & 8. Multi-user isolation: User B's approvals do not leak to User A."""
    plan = [{"step_id": "s1", "operation": "gmail_send", "approval_required": True}]
    # Run owned by User B (second_user)
    run_b = AgentRun(
        user_id=second_user.id,
        thread_id="thread-user-b",
        original_request="User B sensitive request",
        status=AgentRunStatus.AWAITING_APPROVAL,
        current_step=0,
        execution_plan=plan,
    )
    db_session.add(run_b)
    await db_session.commit()

    # User A requests health
    res_a = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert res_a.status_code == 200
    assert res_a.json()["runs_by_status"]["awaiting_approval"] == 0

    # User A requests approvals list
    list_a = client.get("/api/v1/agents/runs?status=awaiting_approval", headers=auth_headers)
    assert list_a.json()["total"] == 0

    # User B requests health
    res_b = client.get("/api/v1/monitoring/health", headers=second_auth_headers)
    assert res_b.status_code == 200
    assert res_b.json()["runs_by_status"]["awaiting_approval"] == 1

    # User B requests approvals list
    list_b = client.get("/api/v1/agents/runs?status=awaiting_approval", headers=second_auth_headers)
    assert list_b.json()["total"] == 1


# =========================================================================
# PART C & G: SCHEDULING METRICS REGRESSION TESTS
# =========================================================================


@pytest.mark.asyncio
async def test_newly_created_enabled_one_time_schedule_is_active(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """1. A newly created enabled one-time schedule contributes to active schedule count."""
    future_time = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    payload = {
        "name": "Upcoming Single Audit",
        "workflow_request": "Audit system records",
        "schedule_type": "one_time",
        "timezone": "UTC",
        "schedule_configuration": {"run_at": future_time},
    }
    create_res = client.post("/api/v1/schedules", json=payload, headers=auth_headers)
    assert create_res.status_code == 201

    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.active_schedules == 1

    api_res = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert api_res.json()["active_schedules"] == 1


@pytest.mark.asyncio
async def test_consumed_one_time_schedule_leaves_active_schedules(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """2-4. Consumed one-time schedule leaves active count and enters history."""
    now_utc = datetime.now(UTC)
    past_time = now_utc - timedelta(minutes=10)

    sched = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Consumed One-Time Job",
        workflow_request="One-time data pull",
        schedule_type=ScheduleType.ONE_TIME,
        timezone="UTC",
        schedule_configuration={"run_at": past_time.isoformat()},
        next_run_at=past_time,
        is_active=True,
    )
    db_session.add(sched)
    await db_session.commit()

    # Process due schedules via scheduler
    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        dispatched = await SchedulerService.process_due_schedules(db=db_session)
        assert dispatched == 1

    await db_session.refresh(sched)
    # Lifecycle transition: is_active is now False, last_run_at is set
    assert sched.is_active is False
    assert sched.last_run_at is not None

    # Linked execution exists
    runs_stmt = select(AgentRun).where(AgentRun.schedule_id == sched.id)
    runs = (await db_session.execute(runs_stmt)).scalars().all()
    assert len(runs) == 1
    assert runs[0].user_id == registered_user.id

    # Active schedules count is now 0
    active_count = await SchedulingService.count_active_schedules(
        db_session, user_id=registered_user.id
    )
    assert active_count == 0

    # Schedule history still contains the record
    all_schedules = await SchedulingService.list_schedules(db_session, user_id=registered_user.id)
    assert len(all_schedules) == 1
    assert all_schedules[0].id == sched.id


@pytest.mark.asyncio
async def test_paused_schedule_is_excluded(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """5. Paused schedules (recurring or one-time) do not contribute to active count."""
    sched = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Paused Daily Report",
        workflow_request="Generate daily analytics",
        schedule_type=ScheduleType.DAILY,
        timezone="UTC",
        schedule_configuration={"time": "08:00"},
        next_run_at=datetime.now(UTC) + timedelta(days=1),
        is_active=False,  # PAUSED
    )
    db_session.add(sched)
    await db_session.commit()

    health = await MonitoringService.get_system_health(db_session, user_id=registered_user.id)
    assert health.active_schedules == 0

    api_res = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert api_res.json()["active_schedules"] == 0


@pytest.mark.asyncio
async def test_valid_recurring_schedule_remains_active_after_one_execution(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """6. A recurring schedule remains active after an individual execution completes."""
    now_utc = datetime.now(UTC)
    past_time = now_utc - timedelta(minutes=5)

    sched = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Recurring Production Health Check",
        workflow_request="Check system endpoints",
        schedule_type=ScheduleType.DAILY,
        timezone="UTC",
        schedule_configuration={"time": "12:00"},
        next_run_at=past_time,
        is_active=True,
    )
    db_session.add(sched)
    await db_session.commit()

    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        dispatched = await SchedulerService.process_due_schedules(db=db_session)
        assert dispatched == 1

    await db_session.refresh(sched)
    # Recurring schedule should advance next_run_at and remain is_active=True
    assert sched.is_active is True
    assert sched.last_run_at is not None
    assert sched.next_run_at > now_utc

    active_count = await SchedulingService.count_active_schedules(
        db_session, user_id=registered_user.id
    )
    assert active_count == 1


@pytest.mark.asyncio
async def test_different_users_schedules_are_isolated(
    client: TestClient,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
    db_session: AsyncSession,
) -> None:
    """8 & 10. Multi-user isolation for active schedules metric."""
    sched_b = ScheduledWorkflow(
        user_id=second_user.id,
        name="User B Daily Task",
        workflow_request="User B private task",
        schedule_type=ScheduleType.DAILY,
        timezone="UTC",
        schedule_configuration={"time": "14:00"},
        next_run_at=datetime.now(UTC) + timedelta(days=1),
        is_active=True,
    )
    db_session.add(sched_b)
    await db_session.commit()

    # User A sees 0 active schedules
    res_a = client.get("/api/v1/monitoring/health", headers=auth_headers)
    assert res_a.json()["active_schedules"] == 0

    # User B sees 1 active schedule
    res_b = client.get("/api/v1/monitoring/health", headers=second_auth_headers)
    assert res_b.json()["active_schedules"] == 1


@pytest.mark.asyncio
async def test_repeated_scheduler_polling_does_not_create_duplicates(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """9. Repeated scheduler polling does not create duplicate executions for one-time schedules."""
    now_utc = datetime.now(UTC)
    past_time = now_utc - timedelta(minutes=5)

    sched = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Strict Single Trigger Job",
        workflow_request="Execute single operation",
        schedule_type=ScheduleType.ONE_TIME,
        timezone="UTC",
        schedule_configuration={"run_at": past_time.isoformat()},
        next_run_at=past_time,
        is_active=True,
    )
    db_session.add(sched)
    await db_session.commit()

    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        # First poll claims and dispatches
        count_1 = await SchedulerService.process_due_schedules(db=db_session)
        assert count_1 == 1

        # Second poll immediately afterwards finds 0 due
        count_2 = await SchedulerService.process_due_schedules(db=db_session)
        assert count_2 == 0

    # Exactly 1 run created
    runs_stmt = select(AgentRun).where(AgentRun.schedule_id == sched.id)
    runs = (await db_session.execute(runs_stmt)).scalars().all()
    assert len(runs) == 1
