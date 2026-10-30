"""Business logic service for scheduled workflow management and authorization."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.models.scheduled_workflow import ScheduledWorkflow, ScheduleType
from flowpilot.schemas.schedules import (
    ScheduledWorkflowCreateRequest,
    ScheduledWorkflowUpdateRequest,
)
from flowpilot.workers.scheduler import calculate_next_run_at

logger = get_logger("services.scheduling")
settings = get_settings()


class ScheduleServiceError(Exception):
    """Base exception for schedule service errors."""


class ScheduleNotFoundError(ScheduleServiceError):
    """Raised when the specified schedule is not found."""


class ScheduleAccessDeniedError(ScheduleServiceError):
    """Raised when an unauthorized user attempts to access or modify a schedule."""


class ScheduleLimitExceededError(ScheduleServiceError):
    """Raised when a user attempts to create more active schedules than permitted."""


class SchedulingService:
    """Provides user-isolated CRUD operations and state transitions for scheduled workflows."""

    @classmethod
    def active_schedules_filter(cls, user_id: uuid.UUID | None = None):
        """Build SQLAlchemy expression for active, unconsumed scheduled workflows.

        A schedule is active if:
        1. is_active is True (enabled, not paused or cancelled)
        2. For one-time schedules: last_run_at is None (not yet triggered/consumed)
        3. Owned by user_id if specified
        """
        cond = and_(
            ScheduledWorkflow.is_active.is_(True),
            or_(
                ScheduledWorkflow.schedule_type != ScheduleType.ONE_TIME,
                ScheduledWorkflow.last_run_at.is_(None),
            ),
        )
        if user_id is not None:
            cond = and_(cond, ScheduledWorkflow.user_id == user_id)
        return cond

    @classmethod
    async def count_active_schedules(
        cls, db: AsyncSession, user_id: uuid.UUID | None = None
    ) -> int:
        """Count active, unconsumed schedules matching the shared domain lifecycle."""
        stmt = select(func.count(ScheduledWorkflow.id)).where(cls.active_schedules_filter(user_id))
        return (await db.scalar(stmt)) or 0

    @classmethod
    async def create_schedule(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request_data: ScheduledWorkflowCreateRequest,
    ) -> ScheduledWorkflow:
        """Create and calculate the initial next_run_at timestamp for a new scheduled workflow."""
        active_count = await cls.count_active_schedules(db, user_id=user_id)
        if active_count >= settings.MAX_ACTIVE_SCHEDULES_PER_USER:
            msg = f"Limit of {settings.MAX_ACTIVE_SCHEDULES_PER_USER} active schedules reached."
            raise ScheduleLimitExceededError(msg)

        # Calculate initial execution time
        next_run_at = calculate_next_run_at(
            schedule_type=request_data.schedule_type,
            tz_str=request_data.timezone,
            config=request_data.schedule_configuration,
        )

        schedule = ScheduledWorkflow(
            user_id=user_id,
            name=request_data.name,
            workflow_request=request_data.workflow_request,
            schedule_type=request_data.schedule_type,
            timezone=request_data.timezone,
            schedule_configuration=request_data.schedule_configuration,
            next_run_at=next_run_at,
            is_active=True,
        )
        db.add(schedule)
        await db.commit()
        await db.refresh(schedule)
        logger.info(
            "Created scheduled workflow '%s' (id=%s) for user %s",
            schedule.name,
            schedule.id,
            user_id,
        )
        return schedule

    @classmethod
    async def get_schedule(
        cls,
        db: AsyncSession,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ScheduledWorkflow:
        """Retrieve a scheduled workflow with strict ownership verification."""
        stmt = (
            select(ScheduledWorkflow)
            .where(ScheduledWorkflow.id == schedule_id)
            .options(selectinload(ScheduledWorkflow.agent_runs))
        )
        result = await db.execute(stmt)
        schedule = result.scalar_one_or_none()
        if not schedule:
            raise ScheduleNotFoundError(f"Scheduled workflow '{schedule_id}' not found.")
        if schedule.user_id != user_id:
            raise ScheduleAccessDeniedError(
                f"You do not have permission to access schedule '{schedule_id}'."
            )
        cls._populate_latest_run(schedule)
        return schedule

    @classmethod
    def _populate_latest_run(cls, schedule: ScheduledWorkflow) -> None:
        """Helper to attach latest_run_id and latest_run_status to a schedule object."""
        runs = getattr(schedule, "agent_runs", []) or []
        if runs:
            sorted_runs = sorted(runs, key=lambda r: r.created_at, reverse=True)
            schedule.latest_run_id = sorted_runs[0].id
            schedule.latest_run_status = sorted_runs[0].status
        else:
            schedule.latest_run_id = None
            schedule.latest_run_status = None

    @classmethod
    async def list_schedules(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[ScheduledWorkflow]:
        """List all scheduled workflows belonging to the user."""
        stmt = (
            select(ScheduledWorkflow)
            .where(ScheduledWorkflow.user_id == user_id)
            .options(selectinload(ScheduledWorkflow.agent_runs))
            .order_by(ScheduledWorkflow.created_at.desc())
        )
        result = await db.execute(stmt)
        schedules = list(result.scalars().all())
        for s in schedules:
            cls._populate_latest_run(s)
        return schedules

    @classmethod
    async def update_schedule(
        cls,
        db: AsyncSession,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
        update_data: ScheduledWorkflowUpdateRequest,
    ) -> ScheduledWorkflow:
        """Update scheduled workflow configuration.

        Recalculates next_run_at if timing fields changed.
        """
        schedule = await cls.get_schedule(db, schedule_id, user_id)

        timing_changed = False
        if update_data.name is not None:
            schedule.name = update_data.name
        if update_data.workflow_request is not None:
            schedule.workflow_request = update_data.workflow_request
        if update_data.schedule_type is not None:
            schedule.schedule_type = update_data.schedule_type
            timing_changed = True
        if update_data.timezone is not None:
            schedule.timezone = update_data.timezone
            timing_changed = True
        if update_data.schedule_configuration is not None:
            schedule.schedule_configuration = update_data.schedule_configuration
            timing_changed = True
        if update_data.is_active is not None:
            schedule.is_active = update_data.is_active

        if timing_changed and schedule.is_active:
            schedule.next_run_at = calculate_next_run_at(
                schedule_type=schedule.schedule_type,
                tz_str=schedule.timezone,
                config=schedule.schedule_configuration,
            )

        schedule.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(schedule)
        return schedule

    @classmethod
    async def delete_schedule(
        cls,
        db: AsyncSession,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> None:
        """Delete an owned scheduled workflow."""
        schedule = await cls.get_schedule(db, schedule_id, user_id)
        await db.delete(schedule)
        await db.commit()

    @classmethod
    async def pause_schedule(
        cls,
        db: AsyncSession,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ScheduledWorkflow:
        """Pause a recurring scheduled workflow."""
        schedule = await cls.get_schedule(db, schedule_id, user_id)
        schedule.is_active = False
        schedule.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(schedule)
        return schedule

    @classmethod
    async def resume_schedule(
        cls,
        db: AsyncSession,
        schedule_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> ScheduledWorkflow:
        """Resume a paused scheduled workflow, re-evaluating its next execution time."""
        schedule = await cls.get_schedule(db, schedule_id, user_id)
        schedule.is_active = True
        schedule.next_run_at = calculate_next_run_at(
            schedule_type=schedule.schedule_type,
            tz_str=schedule.timezone,
            config=schedule.schedule_configuration,
        )
        schedule.updated_at = datetime.now(UTC)
        await db.commit()
        await db.refresh(schedule)
        return schedule
