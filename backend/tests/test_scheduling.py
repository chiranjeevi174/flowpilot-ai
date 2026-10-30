"""Automated tests for workflow scheduling, recurrence calculations, atomic claiming, and APIs."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.models.user import User
from flowpilot.models.workflow_outbox import WorkflowOutbox
from flowpilot.workers.scheduler import SchedulerService, calculate_next_run_at


def test_compute_next_run_at_daily() -> None:
    """Verify daily recurrence calculates next run time in UTC based on specified timezone."""
    now_utc = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)
    config = {"time": "09:00"}  # 9:00 AM New York time is 13:00 or 14:00 UTC
    tz_str = "America/New_York"

    next_run = calculate_next_run_at(ScheduleType.DAILY, tz_str, config, from_time=now_utc)
    assert next_run is not None
    assert next_run > now_utc
    assert next_run.tzinfo is not None


def test_compute_next_run_at_weekly() -> None:
    """Verify weekly recurrence calculates next occurrence matching specified weekday."""
    now_utc = datetime(2026, 10, 24, 12, 0, 0, tzinfo=UTC)  # 2026-10-24 is a Saturday (iso 6)
    config = {"day_of_week": "monday", "time": "10:00"}
    tz_str = "UTC"

    next_run = calculate_next_run_at(ScheduleType.WEEKLY, tz_str, config, from_time=now_utc)
    assert next_run is not None
    assert next_run > now_utc
    # Next Monday is 2026-10-26
    assert next_run.weekday() == 0  # 0 is Monday


@pytest.mark.asyncio
async def test_scheduler_process_due_schedules_atomic(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify due schedules are processed atomically and advance next_run_at."""
    now_utc = datetime.now(UTC)
    past_run = now_utc - timedelta(minutes=5)

    sched = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Daily Compliance Report",
        workflow_request="Run daily compliance checks.",
        schedule_type=ScheduleType.DAILY,
        timezone="UTC",
        schedule_configuration={"time": "08:00"},
        next_run_at=past_run,
        is_active=True,
    )
    db_session.add(sched)
    await db_session.commit()

    with patch("flowpilot.workers.tasks.execute_workflow_task.delay"):
        processed_count = await SchedulerService.process_due_schedules(db=db_session)
        assert processed_count >= 1

    await db_session.refresh(sched)
    assert sched.last_run_at is not None
    assert sched.next_run_at > now_utc

    # Outbox record was created
    res = await db_session.execute(
        select(WorkflowOutbox).where(WorkflowOutbox.task_type == "start_run")
    )
    entries = res.scalars().all()
    assert len(entries) >= 1


def test_api_schedules_crud_and_lifecycle(
    client: TestClient,
    registered_user: User,
    auth_headers: dict[str, str],
) -> None:
    """Verify schedule creation, listing, pause, resume, and deletion via REST API."""
    future_time = (datetime.now(UTC) + timedelta(days=1)).isoformat()

    # 1. Create schedule
    create_payload = {
        "name": "Weekly Maintenance",
        "workflow_request": "Execute database vacuum and index re-alignment.",
        "schedule_type": "weekly",
        "timezone": "UTC",
        "schedule_configuration": {"day_of_week": "sunday", "time": "03:00"},
        "next_run_at": future_time,
    }
    create_res = client.post("/api/v1/schedules", json=create_payload, headers=auth_headers)
    assert create_res.status_code == 201
    sched_data = create_res.json()
    sched_id = sched_data["id"]
    assert sched_data["name"] == "Weekly Maintenance"
    assert sched_data["is_active"] is True

    # 2. List schedules
    list_res = client.get("/api/v1/schedules", headers=auth_headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 3. Pause schedule
    pause_res = client.post(f"/api/v1/schedules/{sched_id}/pause", headers=auth_headers)
    assert pause_res.status_code == 200
    assert pause_res.json()["is_active"] is False

    # 4. Resume schedule
    resume_res = client.post(f"/api/v1/schedules/{sched_id}/resume", headers=auth_headers)
    assert resume_res.status_code == 200
    assert resume_res.json()["is_active"] is True

    # 5. Delete schedule
    del_res = client.delete(f"/api/v1/schedules/{sched_id}", headers=auth_headers)
    assert del_res.status_code == 204


def test_api_cross_user_schedule_isolation(
    client: TestClient,
    registered_user: User,
    second_user: User,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify that User B cannot view, modify, pause, or delete User A's schedule."""
    # Create schedule as User A
    future_run_at = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    create_payload = {
        "name": "User A Private Task",
        "workflow_request": "Secret automated analysis.",
        "schedule_type": "one_time",
        "timezone": "UTC",
        "schedule_configuration": {"run_at": future_run_at},
    }
    create_res = client.post("/api/v1/schedules", json=create_payload, headers=auth_headers)
    assert create_res.status_code == 201
    sched_id = create_res.json()["id"]

    # User B attempts to access User A's schedule -> 404
    get_res = client.get(f"/api/v1/schedules/{sched_id}", headers=second_auth_headers)
    assert get_res.status_code == 404

    pause_res = client.post(f"/api/v1/schedules/{sched_id}/pause", headers=second_auth_headers)
    assert pause_res.status_code == 404

    del_res = client.delete(f"/api/v1/schedules/{sched_id}", headers=second_auth_headers)
    assert del_res.status_code == 404
