"""Durable workflow dispatch using PostgreSQL Transactional Outbox and Celery task publishing."""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.core.logging import get_logger
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.models.workflow_outbox import OutboxStatus, WorkflowOutbox

logger = get_logger("workflows.dispatch")


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class WorkflowDispatcher:
    """Orchestrates durable execution request persistence and safe Celery task dispatch."""

    @classmethod
    async def create_and_dispatch_run(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: str,
        provider: str | None = None,
        model: str | None = None,
        schedule_id: uuid.UUID | None = None,
    ) -> AgentRun:
        """Atomically persist AgentRun and outbox record, then dispatch to background worker."""
        run_id = uuid.uuid4()
        thread_id = f"flowpilot_run_{run_id}"

        # 1. Create AgentRun in QUEUED state
        agent_run = AgentRun(
            id=run_id,
            user_id=user_id,
            thread_id=thread_id,
            original_request=request,
            status=AgentRunStatus.QUEUED,
            schedule_id=schedule_id,
        )
        db.add(agent_run)

        # 2. Create durable outbox record within the same transaction
        outbox_payload = {
            "run_id": str(run_id),
            "user_id": str(user_id),
            "provider": provider,
            "model": model,
        }
        outbox_entry = WorkflowOutbox(
            run_id=run_id,
            task_type="start_run",
            payload=outbox_payload,
            status=OutboxStatus.PENDING,
        )
        db.add(outbox_entry)

        # 3. Record audit event for run queuing
        await record_event(
            db=db,
            run_id=str(run_id),
            agent_name="dispatcher",
            event_type="run_queued",
            event_payload={
                "run_id": str(run_id),
                "user_id": str(user_id),
                "schedule_id": str(schedule_id) if schedule_id else None,
            },
        )

        # 4. Commit transaction so run and outbox are durably persisted in PostgreSQL
        await db.commit()
        await db.refresh(agent_run)
        await db.refresh(outbox_entry)

        # 5. Attempt immediate Celery dispatch (safe against broker failure)
        await cls.try_dispatch_outbox_entry(db, outbox_entry)
        await db.refresh(agent_run)

        return agent_run

    @classmethod
    async def create_and_dispatch_resume(
        cls,
        db: AsyncSession,
        agent_run: AgentRun,
        user_id: uuid.UUID,
        decision: str,
        comment: str | None = None,
    ) -> AgentRun:
        """Atomically persist resume outbox record and dispatch to background worker."""
        agent_run.status = AgentRunStatus.QUEUED
        agent_run.error_message = None

        outbox_payload = {
            "run_id": str(agent_run.id),
            "user_id": str(user_id),
            "decision": decision,
            "comment": comment,
        }
        outbox_entry = WorkflowOutbox(
            run_id=agent_run.id,
            task_type="resume_run",
            payload=outbox_payload,
            status=OutboxStatus.PENDING,
        )
        db.add(outbox_entry)

        await record_event(
            db=db,
            run_id=str(agent_run.id),
            agent_name="dispatcher",
            event_type="approval_queued",
            event_payload={
                "decision": decision,
                "comment": comment,
            },
        )

        await db.commit()
        await db.refresh(agent_run)
        await db.refresh(outbox_entry)

        await cls.try_dispatch_outbox_entry(db, outbox_entry)
        await db.refresh(agent_run)

        return agent_run

    @classmethod
    async def try_dispatch_outbox_entry(
        cls,
        db: AsyncSession,
        outbox_entry: WorkflowOutbox,
    ) -> bool:
        """Attempt dispatching an outbox entry to Celery. Marks dispatched or records failure."""
        from flowpilot.workers.tasks import execute_workflow_task, resume_workflow_task

        payload = outbox_entry.payload
        run_id = payload.get("run_id")
        user_id = payload.get("user_id")

        try:
            if outbox_entry.task_type == "start_run":
                execute_workflow_task.delay(
                    run_id_str=run_id,
                    user_id_str=user_id,
                    provider=payload.get("provider"),
                    model=payload.get("model"),
                )
            elif outbox_entry.task_type == "resume_run":
                resume_workflow_task.delay(
                    run_id_str=run_id,
                    user_id_str=user_id,
                    decision=payload.get("decision", "reject"),
                    comment=payload.get("comment"),
                )
            else:
                logger.error("Unknown outbox task_type: %s", outbox_entry.task_type)
                return False

            outbox_entry.status = OutboxStatus.DISPATCHED
            outbox_entry.dispatched_at = get_utc_now()
            outbox_entry.last_error = None
            await db.commit()
            logger.info(
                "Successfully dispatched outbox task %s for run %s",
                outbox_entry.task_type,
                run_id,
            )
            return True

        except Exception as exc:
            logger.warning(
                "Failed to dispatch outbox task %s for run %s (will be recovered): %s",
                outbox_entry.task_type,
                run_id,
                exc,
            )
            outbox_entry.status = OutboxStatus.PENDING
            outbox_entry.retry_count += 1
            outbox_entry.last_error = str(exc)
            await db.commit()
            return False
