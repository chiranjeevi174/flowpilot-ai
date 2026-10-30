"""Celery task definitions for background workflow execution, resumption, and maintenance."""

import sys

if sys.platform == "win32":
    import asyncio

    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import asyncio
import concurrent.futures
import uuid
from datetime import UTC, datetime

from celery import Task
from celery.signals import worker_ready, worker_shutdown
from sqlalchemy import select, update

from flowpilot.agents.events import record_event
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.workers.celery_app import celery_app
from flowpilot.workers.recovery import RecoveryService
from flowpilot.workers.scheduler import SchedulerService
from flowpilot.workflows.engine import WorkflowEngine, close_checkpointer, init_checkpointer

logger = get_logger("workers.tasks")


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    """Return a persistent event loop for Celery worker task execution."""
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        if sys.platform == "win32":
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        _worker_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(_worker_loop)
    return _worker_loop


def _run_async(coro):
    """Run an async coroutine inside Celery, supporting both worker and eager test modes."""
    try:
        asyncio.get_running_loop()
        has_running_loop = True
    except RuntimeError:
        has_running_loop = False

    def _exec(c):
        loop = _get_worker_loop()
        return loop.run_until_complete(c)

    if not has_running_loop:
        return _exec(coro)

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(_exec, coro).result()


@worker_ready.connect
def on_worker_ready(**kwargs):
    """Pre-warm and verify PostgreSQL LangGraph checkpointer when Celery worker starts."""
    try:
        logger.info("Initializing LangGraph checkpointer on Celery worker startup...")
        _run_async(init_checkpointer())
    except Exception as exc:
        logger.warning("Checkpointer pre-warm warning on worker startup: %s", exc)


@worker_shutdown.connect
def on_worker_shutdown(**kwargs):
    """Cleanly close checkpointer connection pool during Celery worker shutdown."""
    try:
        logger.info("Closing LangGraph checkpointer pool on Celery worker shutdown...")
        _run_async(close_checkpointer())
    except Exception as exc:
        logger.warning("Error closing checkpointer on worker shutdown: %s", exc)


@celery_app.task(bind=True, name="flowpilot.workers.tasks.execute_workflow_task", max_retries=2)
def execute_workflow_task(
    self: Task,
    run_id_str: str,
    user_id_str: str,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, str]:
    """Execute a queued agent run workflow in the background with atomic claiming and recovery."""
    run_id = uuid.UUID(run_id_str)
    user_id = uuid.UUID(user_id_str)
    worker_id = (
        f"{getattr(self.request, 'hostname', 'local')}:{getattr(self.request, 'id', 'sync')}"
    )

    async def _execute() -> dict[str, str]:
        session_maker = async_session_factory()
        async with session_maker() as db:
            now_utc = get_utc_now()

            # 1. Atomic run claim: only claim if queued or pending and not cancelled
            claim_stmt = (
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status.in_([AgentRunStatus.PENDING, AgentRunStatus.QUEUED]),
                    AgentRun.cancellation_requested.is_(False),
                )
                .values(
                    status=AgentRunStatus.RUNNING,
                    locked_by=worker_id,
                    locked_at=now_utc,
                    heartbeat_at=now_utc,
                )
                .returning(AgentRun.id, AgentRun.original_request)
            )
            result = await db.execute(claim_stmt)
            claimed = result.fetchone()
            await db.commit()

            if not claimed:
                # Check why claim failed: was it cancelled or already claimed/terminal?
                check_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                run = check_res.scalar_one_or_none()
                if run:
                    if run.cancellation_requested:
                        logger.info(
                            "Run %s was cancelled before execution. Marking CANCELLED.", run_id
                        )
                        run.status = AgentRunStatus.CANCELLED
                        run.completed_at = get_utc_now()
                        await record_event(
                            db=db,
                            run_id=run_id,
                            agent_name="worker",
                            event_type="run_cancelled",
                            event_payload={"reason": "Cancelled while queued in worker queue."},
                        )
                        await db.commit()
                        return {"status": "cancelled", "run_id": run_id_str}
                    logger.info(
                        "Run %s already in '%s' (locked_by: %s). Skipping duplicate delivery.",
                        run_id,
                        run.status,
                        run.locked_by,
                    )
                    return {"status": run.status, "run_id": run_id_str}
                logger.error("Run %s not found in database.", run_id)
                return {"status": "not_found", "run_id": run_id_str}

            _, original_request = claimed

            # 2. Record run_started event
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="worker",
                event_type="run_started",
                event_payload={
                    "worker_id": worker_id,
                    "provider": provider,
                    "model": model,
                },
            )

            # 3. Execute WorkflowEngine
            try:
                run = await WorkflowEngine.start_run(
                    db=db,
                    user_id=user_id,
                    request=original_request,
                    provider=provider,
                    model=model,
                    existing_run_id=run_id,
                )
                logger.info(
                    "Worker completed execution for run %s with status '%s'", run_id, run.status
                )
                return {"status": run.status, "run_id": run_id_str}

            except Exception as exc:
                logger.exception("Worker failure during execution of run %s: %s", run_id, exc)
                # Check if retryable or retries exhausted
                check_run = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                active_run = check_run.scalar_one_or_none()
                if active_run:
                    active_run.status = AgentRunStatus.FAILED
                    active_run.completed_at = get_utc_now()
                    active_run.error_message = str(exc)
                    await record_event(
                        db=db,
                        run_id=run_id,
                        agent_name="worker",
                        event_type="run_failed",
                        event_payload={"error": str(exc)},
                    )
                    await db.commit()
                raise

    return _run_async(_execute())


@celery_app.task(bind=True, name="flowpilot.workers.tasks.resume_workflow_task", max_retries=2)
def resume_workflow_task(
    self: Task,
    run_id_str: str,
    user_id_str: str,
    decision: str,
    comment: str | None = None,
) -> dict[str, str]:
    """Resume an awaiting_approval agent run in the background."""
    run_id = uuid.UUID(run_id_str)
    user_id = uuid.UUID(user_id_str)
    worker_id = (
        f"{getattr(self.request, 'hostname', 'local')}:{getattr(self.request, 'id', 'sync')}"
    )

    async def _resume() -> dict[str, str]:
        session_maker = async_session_factory()
        async with session_maker() as db:
            now_utc = get_utc_now()

            # Atomic claim for resume
            claim_stmt = (
                update(AgentRun)
                .where(
                    AgentRun.id == run_id,
                    AgentRun.status == AgentRunStatus.QUEUED,
                    AgentRun.cancellation_requested.is_(False),
                )
                .values(
                    status=AgentRunStatus.RUNNING,
                    locked_by=worker_id,
                    locked_at=now_utc,
                    heartbeat_at=now_utc,
                )
                .returning(AgentRun.id)
            )
            res = await db.execute(claim_stmt)
            claimed = res.fetchone()
            await db.commit()

            if not claimed:
                check_res = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                run = check_res.scalar_one_or_none()
                if run and run.cancellation_requested:
                    run.status = AgentRunStatus.CANCELLED
                    run.completed_at = get_utc_now()
                    await db.commit()
                    return {"status": "cancelled", "run_id": run_id_str}
                logger.info("Resume claim skipped for run %s (already running or finished)", run_id)
                return {"status": run.status if run else "not_found", "run_id": run_id_str}

            try:
                run = await WorkflowEngine.resume_run(
                    db=db,
                    run_id=run_id,
                    user_id=user_id,
                    decision=decision,
                    comment=comment,
                )
                logger.info("Worker resumed run %s with status '%s'", run_id, run.status)
                return {"status": run.status, "run_id": run_id_str}

            except Exception as exc:
                logger.exception("Worker error resuming run %s: %s", run_id, exc)
                check_run = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
                active_run = check_run.scalar_one_or_none()
                if active_run:
                    active_run.status = AgentRunStatus.FAILED
                    active_run.completed_at = get_utc_now()
                    active_run.error_message = str(exc)
                    await record_event(
                        db=db,
                        run_id=run_id,
                        agent_name="worker",
                        event_type="run_failed",
                        event_payload={"error": str(exc)},
                    )
                    await db.commit()
                raise

    return _run_async(_resume())


@celery_app.task(name="flowpilot.workers.tasks.process_scheduled_workflows_task")
def process_scheduled_workflows_task() -> int:
    """Periodic Celery Beat task that evaluates and claims due recurring or one-time workflows."""

    async def _process() -> int:
        session_maker = async_session_factory()
        async with session_maker() as db:
            return await SchedulerService.process_due_schedules(db)

    return _run_async(_process())


@celery_app.task(name="flowpilot.workers.tasks.recover_outbox_task")
def recover_outbox_task() -> int:
    """Periodic Celery Beat task that recovers pending outbox records."""

    async def _recover() -> int:
        session_maker = async_session_factory()
        async with session_maker() as db:
            return await RecoveryService.recover_stuck_outbox(db)

    return _run_async(_recover())


@celery_app.task(name="flowpilot.workers.tasks.recover_abandoned_runs_task")
def recover_abandoned_runs_task() -> int:
    """Periodic Celery Beat task that sweeps and retries/fails abandoned running executions."""

    async def _recover() -> int:
        session_maker = async_session_factory()
        async with session_maker() as db:
            return await RecoveryService.recover_abandoned_runs(db)

    return _run_async(_recover())
