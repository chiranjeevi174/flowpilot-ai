"""Background recovery service for stranded outbox tasks and abandoned worker runs."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.workflow_outbox import OutboxStatus, WorkflowOutbox
from flowpilot.workflows.dispatch import WorkflowDispatcher

logger = get_logger("workers.recovery")
settings = get_settings()


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class RecoveryService:
    """Detects and repairs orphaned outbox dispatches and abandoned running workflow jobs."""

    @classmethod
    async def recover_stuck_outbox(
        cls,
        db: AsyncSession,
        max_age_seconds: int = 5,
    ) -> int:
        """Sweep and re-dispatch pending outbox records that were not sent immediately."""
        cutoff = get_utc_now() - timedelta(seconds=max_age_seconds)
        stmt = (
            select(WorkflowOutbox)
            .where(
                WorkflowOutbox.status == OutboxStatus.PENDING,
                WorkflowOutbox.created_at <= cutoff,
            )
            .order_by(WorkflowOutbox.created_at.asc())
            .limit(50)
        )
        result = await db.execute(stmt)
        entries = list(result.scalars().all())

        recovered_count = 0
        for entry in entries:
            if entry.retry_count >= settings.OUTBOX_MAX_RETRIES:
                logger.error(
                    "Outbox entry %s exceeded max retries (%d). Marking as failed.",
                    entry.id,
                    settings.OUTBOX_MAX_RETRIES,
                )
                entry.status = OutboxStatus.FAILED
                entry.last_error = f"Exceeded max retries ({settings.OUTBOX_MAX_RETRIES})"
                if entry.run_id:
                    run = await db.get(AgentRun, entry.run_id)
                    if run and run.status not in AgentRunStatus.TERMINAL:
                        run.status = AgentRunStatus.FAILED
                        run.completed_at = get_utc_now()
                        run.error_message = (
                            f"Outbox dispatch permanently failed: {entry.last_error}"
                        )
                        await record_event(
                            db=db,
                            run_id=run.id,
                            agent_name="outbox_recovery",
                            event_type="run_failed",
                            event_payload={"error": run.error_message, "outbox_id": str(entry.id)},
                        )
                await db.commit()
                continue

            success = await WorkflowDispatcher.try_dispatch_outbox_entry(db, entry)
            if success:
                recovered_count += 1

        if entries:
            logger.info(
                "Outbox recovery checked %d entries; %d dispatched", len(entries), recovered_count
            )
        return recovered_count

    @classmethod
    async def recover_abandoned_runs(
        cls,
        db: AsyncSession,
        heartbeat_timeout_seconds: int | None = None,
    ) -> int:
        """Detect worker crashes by identifying runs whose heartbeat has expired."""
        timeout = heartbeat_timeout_seconds or settings.WORKFLOW_HEARTBEAT_TIMEOUT_SECONDS
        cutoff = get_utc_now() - timedelta(seconds=timeout)

        stmt = (
            select(AgentRun)
            .where(
                AgentRun.status == AgentRunStatus.RUNNING,
                AgentRun.heartbeat_at.is_not(None),
                AgentRun.heartbeat_at <= cutoff,
            )
            .limit(50)
        )
        result = await db.execute(stmt)
        abandoned_runs = list(result.scalars().all())

        recovered_count = 0
        for run in abandoned_runs:
            if run.retry_count < 2:
                # Bounded retry: reset to QUEUED and re-dispatch
                logger.warning(
                    "Run %s abandoned by worker %s (last heartbeat: %s). Retrying (attempt %d/2).",
                    run.id,
                    run.locked_by,
                    run.heartbeat_at,
                    run.retry_count + 1,
                )
                run.status = AgentRunStatus.QUEUED
                run.locked_by = None
                run.locked_at = None
                run.retry_count += 1

                await record_event(
                    db=db,
                    run_id=run.id,
                    agent_name="recovery",
                    event_type="run_retried",
                    event_payload={
                        "reason": f"Worker heartbeat timed out after {timeout}s",
                        "retry_count": run.retry_count,
                    },
                )
                # Dispatch new start_run task
                outbox_entry = WorkflowOutbox(
                    run_id=run.id,
                    task_type="start_run",
                    payload={"run_id": str(run.id), "user_id": str(run.user_id)},
                    status=OutboxStatus.PENDING,
                )
                db.add(outbox_entry)
                await db.commit()
                await WorkflowDispatcher.try_dispatch_outbox_entry(db, outbox_entry)
                recovered_count += 1
            else:
                # Max retries exhausted: mark as FAILED
                logger.error("Run %s abandoned and retries exhausted. Marking as FAILED.", run.id)
                run.status = AgentRunStatus.FAILED
                run.completed_at = get_utc_now()
                run.error_message = (
                    f"Execution abandoned: worker heartbeat timed out after {timeout} seconds."
                )
                await record_event(
                    db=db,
                    run_id=run.id,
                    agent_name="recovery",
                    event_type="run_failed",
                    event_payload={"error": run.error_message},
                )
                await db.commit()
                recovered_count += 1

        return recovered_count
