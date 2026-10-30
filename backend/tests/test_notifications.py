"""Unit and integration tests for in-app notifications and schedule latest-run tracking."""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.notification import NotificationType
from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.models.user import User
from flowpilot.services.notifications import NotificationService
from flowpilot.services.scheduling import SchedulingService


@pytest.mark.asyncio
async def test_notification_create_and_deduplication(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify notification creation and that duplicate dedup_keys update in place."""
    notif1 = await NotificationService.create_or_update_notification(
        db=db_session,
        user_id=registered_user.id,
        type=NotificationType.SCHEDULE_COUNTDOWN,
        title="Upcoming Workflow",
        message="Your scheduled workflow is approaching execution in 15 seconds.",
        dedup_key="countdown_test_schedule_1",
        category="schedule",
        link_url="/schedules",
        meta_data={"schedule_id": "test-123"},
    )
    assert notif1.id is not None
    assert notif1.title == "Upcoming Workflow"
    assert notif1.is_read is False

    # Second call with the same dedup_key should update the existing record
    notif2 = await NotificationService.create_or_update_notification(
        db=db_session,
        user_id=registered_user.id,
        type=NotificationType.WORKFLOW_STARTED,
        title="Workflow Started",
        message="Workflow execution has commenced.",
        dedup_key="countdown_test_schedule_1",
        category="schedule",
        link_url="/executions/run-123",
        meta_data={"run_id": "run-123"},
    )
    assert notif2.id == notif1.id
    assert notif2.title == "Workflow Started"
    assert notif2.type == NotificationType.WORKFLOW_STARTED


@pytest.mark.asyncio
async def test_notification_user_isolation(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify that notifications are strictly scoped to the owner."""
    other_user_id = uuid.uuid4()

    await NotificationService.create_or_update_notification(
        db=db_session,
        user_id=registered_user.id,
        type=NotificationType.SYSTEM,
        title="User 1 Alert",
        message="Scoped to user 1",
        dedup_key="alert_user_1",
    )

    items = await NotificationService.list_notifications(
        db=db_session,
        user_id=other_user_id,
    )
    assert len(items) == 0

    unread = await NotificationService.get_unread_count(
        db=db_session,
        user_id=registered_user.id,
    )
    assert unread >= 1


@pytest.mark.asyncio
async def test_notification_read_and_dismiss_lifecycle(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify mark_as_read, mark_all_read, and dismiss_notification operations."""
    notif = await NotificationService.create_or_update_notification(
        db=db_session,
        user_id=registered_user.id,
        type=NotificationType.APPROVAL_REQUIRED,
        title="Approval Required",
        message="Human authorization gate triggered.",
        dedup_key="approval_cycle_test",
        category="approval",
    )
    assert notif.is_read is False

    read_notif = await NotificationService.mark_as_read(
        db=db_session,
        notification_id=notif.id,
        user_id=registered_user.id,
    )
    assert read_notif is not None
    assert read_notif.is_read is True

    # Dismiss notification
    dismissed = await NotificationService.dismiss_notification(
        db=db_session,
        notification_id=notif.id,
        user_id=registered_user.id,
    )
    assert dismissed is True

    # Active list should not include dismissed
    active_items = await NotificationService.list_notifications(
        db=db_session,
        user_id=registered_user.id,
        include_dismissed=False,
    )
    assert not any(n.id == notif.id for n in active_items)


@pytest.mark.asyncio
async def test_resolve_approval_notification(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify resolve_approval_notification updates approval status on human decision."""
    run_id = str(uuid.uuid4())
    await NotificationService.create_or_update_notification(
        db=db_session,
        user_id=registered_user.id,
        type=NotificationType.APPROVAL_REQUIRED,
        title="Approval Required",
        message="Sensitive email step awaits authorization.",
        dedup_key=f"approval_test_{run_id}",
        category="approval",
        link_url=f"/approvals?run_id={run_id}",
        meta_data={"run_id": run_id},
    )

    await NotificationService.resolve_approval_notification(
        db=db_session,
        run_id=run_id,
        decision="approved",
    )

    items = await NotificationService.list_notifications(
        db=db_session,
        user_id=registered_user.id,
    )
    matching = [n for n in items if n.meta_data.get("run_id") == run_id]
    assert len(matching) == 1
    assert matching[0].is_read is True
    assert "Approved" in matching[0].title


def test_notifications_api_endpoints(
    client: TestClient,
    auth_headers: dict[str, str],
):
    """Verify HTTP API endpoints for notifications."""
    # 1. Create via API
    create_res = client.post(
        "/api/v1/notifications",
        json={
            "type": "schedule_countdown",
            "category": "schedule",
            "title": "Upcoming Workflow",
            "message": "Scheduled to begin in 15 seconds.",
            "link_url": "/schedules",
            "meta_data": {"schedule_id": "test-uuid"},
            "dedup_key": "api_test_dedup_1",
        },
        headers=auth_headers,
    )
    assert create_res.status_code == 201
    created_data = create_res.json()
    notif_id = created_data["id"]

    # 2. List notifications
    list_res = client.get("/api/v1/notifications", headers=auth_headers)
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] >= 1
    assert any(n["id"] == notif_id for n in list_data["items"])

    # 3. Mark read
    patch_res = client.patch(f"/api/v1/notifications/{notif_id}/read", headers=auth_headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["is_read"] is True

    # 4. Mark all read
    mark_all_res = client.post("/api/v1/notifications/mark-all-read", headers=auth_headers)
    assert mark_all_res.status_code == 200

    # 5. Dismiss
    dismiss_res = client.post(f"/api/v1/notifications/{notif_id}/dismiss", headers=auth_headers)
    assert dismiss_res.status_code == 200
    assert dismiss_res.json()["dismissed"] is True


@pytest.mark.asyncio
async def test_schedule_latest_run_tracking(
    db_session: AsyncSession,
    registered_user: User,
):
    """Verify that ScheduledWorkflow query populates latest_run_id and latest_run_status."""
    from datetime import UTC, datetime

    schedule = ScheduledWorkflow(
        user_id=registered_user.id,
        name="Scheduled Task With Runs",
        workflow_request="Send daily status report",
        schedule_type=ScheduleType.DAILY,
        timezone="UTC",
        schedule_configuration={"time": "09:00"},
        next_run_at=datetime.now(UTC),
        is_active=True,
    )
    db_session.add(schedule)
    await db_session.commit()
    await db_session.refresh(schedule)

    # Attach an AgentRun
    run = AgentRun(
        user_id=registered_user.id,
        thread_id=f"thread_{schedule.id}",
        original_request=schedule.workflow_request,
        status=AgentRunStatus.COMPLETED,
        schedule_id=schedule.id,
    )
    db_session.add(run)
    await db_session.commit()

    # Query schedule via SchedulingService
    fetched = await SchedulingService.get_schedule(
        db=db_session,
        schedule_id=schedule.id,
        user_id=registered_user.id,
    )
    assert fetched.latest_run_id == run.id
    assert fetched.latest_run_status == AgentRunStatus.COMPLETED
