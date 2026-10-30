"""Business logic service for multi-agent runs, execution history, and approvals."""

import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy import and_, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.agents.orchestrator import Orchestrator
from flowpilot.core.logging import get_logger
from flowpilot.models.agent_event import AgentEvent
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.schemas.agents import AgentRunCreateRequest
from flowpilot.workflows.dispatch import WorkflowDispatcher

logger = get_logger("services.agents")


class AgentServiceError(Exception):
    """Base exception for agent service failures."""


class RunNotFoundError(AgentServiceError):
    """Raised when the requested execution run is not found."""


class RunAccessDeniedError(AgentServiceError):
    """Raised when a user attempts to access an agent run owned by another user."""


class InvalidRunStateError(AgentServiceError):
    """Raised when an action is invalid for the run's current lifecycle state."""


class AgentService:
    """Service orchestrating agent run lifecycles, user authorization, and event audits."""

    @classmethod
    async def start_run(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request_data: AgentRunCreateRequest,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Initiate execution request, persisting outbox record and dispatching to worker."""
        if checkpointer is not None:
            # Synchronous execution if custom checkpointer is provided (e.g. in unit tests)
            return await Orchestrator.execute_request(
                db=db,
                user_id=user_id,
                request=request_data.request,
                provider=request_data.provider,
                model=request_data.model,
                checkpointer=checkpointer,
            )

        return await WorkflowDispatcher.create_and_dispatch_run(
            db=db,
            user_id=user_id,
            request=request_data.request,
            provider=request_data.provider,
            model=request_data.model,
        )

    @classmethod
    async def get_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentRun:
        """Retrieve an agent run with strict ownership verification."""
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise RunNotFoundError(f"Agent run '{run_id}' not found.")

        if run.user_id != user_id:
            raise RunAccessDeniedError(f"You do not have permission to view agent run '{run_id}'.")

        return run

    @classmethod
    def actionable_approvals_filter(cls, user_id: uuid.UUID | None = None):
        """Build SQLAlchemy expression for genuine actionable pending approval runs.

        Criteria:
        1. status is 'awaiting_approval'
        2. completed_at is None (not completed or failed)
        3. cancellation_requested is False (not cancelled)
        4. execution_plan is not None (not broken/aborted prior to plan generation)
        5. Owned by user_id if specified
        """
        cond = and_(
            AgentRun.status == AgentRunStatus.AWAITING_APPROVAL,
            AgentRun.completed_at.is_(None),
            AgentRun.cancellation_requested.is_(False),
            AgentRun.execution_plan.is_not(None),
            func.jsonb_typeof(AgentRun.execution_plan) == "array",
        )
        if user_id is not None:
            cond = and_(cond, AgentRun.user_id == user_id)
        return cond

    @classmethod
    async def count_pending_approvals(
        cls, db: AsyncSession, user_id: uuid.UUID | None = None
    ) -> int:
        """Count actionable pending approval runs matching the shared domain lifecycle."""
        stmt = select(func.count(AgentRun.id)).where(cls.actionable_approvals_filter(user_id))
        return (await db.scalar(stmt)) or 0

    @classmethod
    async def list_runs(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 20,
        offset: int = 0,
        status: str | None = None,
    ) -> tuple[list[AgentRun], int]:
        """List paginated agent runs belonging strictly to the authenticated user."""
        query = select(AgentRun).where(AgentRun.user_id == user_id)
        count_query = select(func.count(AgentRun.id)).where(AgentRun.user_id == user_id)

        if status:
            norm_status = status.strip().lower()
            if norm_status == AgentRunStatus.AWAITING_APPROVAL:
                approval_cond = cls.actionable_approvals_filter(user_id=None)
                query = query.where(approval_cond)
                count_query = count_query.where(approval_cond)
            else:
                query = query.where(AgentRun.status == norm_status)
                count_query = count_query.where(AgentRun.status == norm_status)

        query = query.order_by(desc(AgentRun.created_at)).limit(limit).offset(offset)

        total_res = await db.execute(count_query)
        total = total_res.scalar_one() or 0

        runs_res = await db.execute(query)
        runs = list(runs_res.scalars().all())

        return runs, total

    @classmethod
    async def get_run_events(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> list[AgentEvent]:
        """Retrieve the chronological event audit trail for an owned run."""
        # Enforce run ownership before returning events
        await cls.get_run(db, run_id, user_id)

        query = (
            select(AgentEvent)
            .where(AgentEvent.run_id == run_id)
            .order_by(AgentEvent.timestamp.asc(), AgentEvent.id.asc())
        )
        res = await db.execute(query)
        return list(res.scalars().all())

    @classmethod
    async def approve_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        comment: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Approve a pending operation and resume execution."""
        run = await cls.get_run(db, run_id, user_id)

        if run.status != AgentRunStatus.AWAITING_APPROVAL:
            raise InvalidRunStateError(
                f"Agent run '{run_id}' is in status '{run.status}', not 'awaiting_approval'."
            )

        try:
            from flowpilot.services.notifications import NotificationService

            await NotificationService.resolve_approval_notification(
                db=db, run_id=run_id, decision="approved"
            )
        except Exception as notif_err:
            logger.warning("Failed to resolve approval notification on approve: %s", notif_err)

        if checkpointer is not None:
            return await Orchestrator.handle_approval(
                db=db,
                run_id=run_id,
                user_id=user_id,
                decision="approve",
                comment=comment,
                checkpointer=checkpointer,
            )

        return await WorkflowDispatcher.create_and_dispatch_resume(
            db=db,
            agent_run=run,
            user_id=user_id,
            decision="approve",
            comment=comment,
        )

    @classmethod
    async def reject_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        comment: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Reject a pending operation and terminate execution."""
        run = await cls.get_run(db, run_id, user_id)

        if run.status != AgentRunStatus.AWAITING_APPROVAL:
            raise InvalidRunStateError(
                f"Agent run '{run_id}' is in status '{run.status}', not 'awaiting_approval'."
            )

        try:
            from flowpilot.services.notifications import NotificationService

            await NotificationService.resolve_approval_notification(
                db=db, run_id=run_id, decision="rejected"
            )
        except Exception as notif_err:
            logger.warning("Failed to resolve approval notification on reject: %s", notif_err)

        if checkpointer is not None:
            return await Orchestrator.handle_approval(
                db=db,
                run_id=run_id,
                user_id=user_id,
                decision="reject",
                comment=comment,
                checkpointer=checkpointer,
            )

        return await WorkflowDispatcher.create_and_dispatch_resume(
            db=db,
            agent_run=run,
            user_id=user_id,
            decision="reject",
            comment=comment,
        )

    @classmethod
    async def cancel_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
    ) -> AgentRun:
        """Cooperatively cancel an active or queued workflow run."""
        from datetime import UTC, datetime

        run = await cls.get_run(db, run_id, user_id)

        if run.status in AgentRunStatus.TERMINAL:
            return run

        run.cancellation_requested = True

        if run.status in (
            AgentRunStatus.PENDING,
            AgentRunStatus.QUEUED,
            AgentRunStatus.AWAITING_APPROVAL,
        ):
            run.status = AgentRunStatus.CANCELLED
            run.completed_at = datetime.now(UTC)
            await record_event(
                db=db,
                run_id=run.id,
                agent_name="service",
                event_type="run_cancelled",
                event_payload={"reason": "User requested run cancellation."},
            )

        await db.commit()
        await db.refresh(run)
        return run
