"""Scheduler logic for computing recurrence cadences and claiming due scheduled workflows."""

from datetime import UTC, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.workflows.dispatch import WorkflowDispatcher

logger = get_logger("workers.scheduler")


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


def validate_timezone(tz_name: str) -> ZoneInfo:
    """Validate and return IANA ZoneInfo instance, raising ValueError on invalid timezone."""
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError) as exc:
        raise ValueError(f"Invalid IANA timezone identifier: '{tz_name}'") from exc


def parse_time_string(time_str: str) -> time:
    """Parse 'HH:MM' string into a datetime.time object."""
    parts = time_str.strip().split(":")
    if len(parts) != 2:
        raise ValueError(f"Time format must be 'HH:MM', got '{time_str}'")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid hour ({hour}) or minute ({minute}) in '{time_str}'")
    return time(hour=hour, minute=minute)


def calculate_next_run_at(
    schedule_type: str,
    tz_str: str,
    config: dict[str, Any],
    from_time: datetime | None = None,
) -> datetime:
    """Compute the next UTC execution datetime according to the recurrence specification."""
    tz = validate_timezone(tz_str)
    base_utc = from_time or get_utc_now()
    base_local = base_utc.astimezone(tz)

    if schedule_type == ScheduleType.ONE_TIME:
        run_at_str = config.get("run_at")
        if not run_at_str:
            raise ValueError("One-time schedule requires 'run_at' ISO timestamp in configuration.")
        dt = datetime.fromisoformat(str(run_at_str).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(UTC)

    elif schedule_type == ScheduleType.DAILY:
        time_str = config.get("time", "00:00")
        target_time = parse_time_string(time_str)

        # Candidate for today in local timezone
        candidate_local = base_local.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )
        # If candidate already passed, advance to tomorrow
        if candidate_local <= base_local:
            candidate_local += timedelta(days=1)
        return candidate_local.astimezone(UTC)

    elif schedule_type == ScheduleType.WEEKLY:
        time_str = config.get("time", "00:00")
        target_time = parse_time_string(time_str)
        # days_of_week: list of integers where 0=Monday, 6=Sunday
        days_of_week = config.get("days_of_week", [0])
        if not isinstance(days_of_week, list) or not days_of_week:
            raise ValueError(
                "Weekly schedule requires non-empty 'days_of_week' list in configuration."
            )

        # Check the next 7 days in local time for the earliest matching day
        candidate_local = base_local.replace(
            hour=target_time.hour,
            minute=target_time.minute,
            second=0,
            microsecond=0,
        )

        for day_offset in range(8):
            candidate = candidate_local + timedelta(days=day_offset)
            if candidate.weekday() in days_of_week and candidate > base_local:
                return candidate.astimezone(UTC)

        # Fallback to 7 days later
        return (candidate_local + timedelta(days=7)).astimezone(UTC)

    raise ValueError(f"Unsupported schedule_type: '{schedule_type}'")


class SchedulerService:
    """Service that processes due scheduled workflows with atomic claiming."""

    @classmethod
    async def process_due_schedules(cls, db: AsyncSession) -> int:
        """Find and claim all active workflows due for execution, triggering runs via outbox."""
        now_utc = get_utc_now()

        # Atomically select due schedules with row locking
        stmt = (
            select(ScheduledWorkflow)
            .where(
                ScheduledWorkflow.is_active.is_(True),
                ScheduledWorkflow.next_run_at <= now_utc,
                or_(
                    ScheduledWorkflow.schedule_type != ScheduleType.ONE_TIME,
                    ScheduledWorkflow.last_run_at.is_(None),
                ),
            )
            .with_for_update(skip_locked=True)
            .limit(50)
        )
        result = await db.execute(stmt)
        due_schedules = list(result.scalars().all())

        if not due_schedules:
            return 0

        dispatched_count = 0
        for schedule in due_schedules:
            try:
                logger.info(
                    "Claiming and triggering scheduled workflow '%s' (id=%s, user=%s)",
                    schedule.name,
                    schedule.id,
                    schedule.user_id,
                )

                # Dispatch new workflow run
                agent_run = await WorkflowDispatcher.create_and_dispatch_run(
                    db=db,
                    user_id=schedule.user_id,
                    request=schedule.workflow_request,
                    schedule_id=schedule.id,
                )

                # Record workflow_started notification
                try:
                    from flowpilot.models.notification import NotificationType
                    from flowpilot.services.notifications import NotificationService

                    await NotificationService.create_or_update_notification(
                        db=db,
                        user_id=schedule.user_id,
                        type=NotificationType.WORKFLOW_STARTED,
                        title="Workflow Started",
                        message=f"Scheduled workflow '{schedule.name}' has started execution.",
                        dedup_key=f"run_started_{agent_run.id}",
                        category="schedule",
                        link_url=f"/executions/{agent_run.id}",
                        meta_data={
                            "run_id": str(agent_run.id),
                            "schedule_id": str(schedule.id),
                            "schedule_name": schedule.name,
                        },
                    )
                except Exception as notif_err:
                    logger.warning("Failed to record workflow_started notification: %s", notif_err)

                # Update schedule tracking
                schedule.last_run_at = now_utc
                if schedule.schedule_type == ScheduleType.ONE_TIME:
                    schedule.is_active = False
                else:
                    schedule.next_run_at = calculate_next_run_at(
                        schedule_type=schedule.schedule_type,
                        tz_str=schedule.timezone,
                        config=schedule.schedule_configuration,
                        from_time=now_utc,
                    )

                await db.commit()
                dispatched_count += 1

            except Exception as exc:
                logger.exception(
                    "Error processing scheduled workflow %s: %s",
                    schedule.id,
                    exc,
                )
                await db.rollback()

        return dispatched_count
