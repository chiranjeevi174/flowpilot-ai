"""Workflow execution engine managing checkpointer lifecycle, graph invocation, and state sync."""

import asyncio
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

import uuid
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph.state import CompiledStateGraph
from langgraph.types import Command
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.agents.events import record_event
from flowpilot.agents.graph import create_agent_graph
from flowpilot.agents.state import AgentState
from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.models.agent_run import AgentRun, AgentRunStatus

logger = get_logger("workflows.engine")

# Application-level checkpointer and connection pool singletons
_checkpointer_pool: AsyncConnectionPool | None = None
_checkpointer: AsyncPostgresSaver | None = None
_compiled_graph: CompiledStateGraph | None = None
_checkpointer_loop: asyncio.AbstractEventLoop | None = None


def _ensure_win32_selector_loop() -> None:
    """Ensure Windows uses SelectorEventLoop for psycopg compatibility."""
    if sys.platform == "win32":
        try:
            current_policy = asyncio.get_event_loop_policy()
            if not isinstance(current_policy, asyncio.WindowsSelectorEventLoopPolicy):
                asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
                logger.debug(
                    "Configured WindowsSelectorEventLoopPolicy for psycopg async compatibility"
                )
        except Exception as exc:
            logger.debug("Failed setting WindowsSelectorEventLoopPolicy: %s", exc)


def _to_psycopg_conninfo(sqlalchemy_url: str) -> str:
    """Convert an asyncpg SQLAlchemy URL to standard psycopg connection info string."""
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")


async def init_checkpointer(db_url: str | None = None) -> AsyncPostgresSaver:
    """Initialize application-wide persistent PostgreSQL checkpointer."""
    global _checkpointer_pool, _checkpointer, _compiled_graph, _checkpointer_loop

    _ensure_win32_selector_loop()

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    loop_compatible = (
        current_loop is None or _checkpointer_loop is None or _checkpointer_loop is current_loop
    )
    if (
        _checkpointer is not None
        and _checkpointer_pool is not None
        and not _checkpointer_pool.closed
        and loop_compatible
    ):
        return _checkpointer

    settings = get_settings()
    target_url = db_url or settings.DATABASE_URL
    conn_str = _to_psycopg_conninfo(target_url)

    # Clean up stale pool if opened on another or closed loop
    if _checkpointer_pool is not None and not _checkpointer_pool.closed:
        try:
            await _checkpointer_pool.close()
        except Exception as exc:
            logger.debug("Closing stale checkpointer pool: %s", exc)
        _checkpointer_pool = None
        _checkpointer = None
        _compiled_graph = None

    logger.info("Initializing LangGraph PostgreSQL checkpointer pool...")
    _checkpointer_pool = AsyncConnectionPool(
        conninfo=conn_str,
        min_size=1,
        max_size=10,
        open=False,
        kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
    )
    await _checkpointer_pool.open()
    _checkpointer_loop = current_loop

    _checkpointer = AsyncPostgresSaver(conn=_checkpointer_pool)
    await _checkpointer.setup()

    _compiled_graph = create_agent_graph(checkpointer=_checkpointer)
    logger.info("LangGraph checkpointer and compiled workflow graph initialized successfully")
    return _checkpointer


async def close_checkpointer() -> None:
    """Cleanly close checkpointer connection pool during application shutdown."""
    global _checkpointer_pool, _checkpointer, _compiled_graph
    global _test_memory_saver, _checkpointer_loop
    _test_memory_saver = None
    if _checkpointer_pool is not None:
        logger.info("Closing LangGraph checkpointer pool...")
        try:
            if not _checkpointer_pool.closed:
                await _checkpointer_pool.close()
        except Exception as exc:
            logger.warning("Error closing checkpointer pool: %s", exc)
        _checkpointer_pool = None
        _checkpointer = None
        _compiled_graph = None
        _checkpointer_loop = None
        logger.info("LangGraph checkpointer pool closed")


def get_checkpointer() -> AsyncPostgresSaver | None:
    """Retrieve global checkpointer instance if initialized."""
    return _checkpointer


_test_memory_saver: BaseCheckpointSaver | None = None


async def get_or_init_checkpointer(
    db_url: str | None = None,
) -> BaseCheckpointSaver:
    """Retrieve the active checkpointer or initialize it asynchronously if not ready."""
    global _checkpointer, _test_memory_saver
    settings = get_settings()

    if settings.is_testing:
        if _test_memory_saver is None:
            from langgraph.checkpoint.memory import MemorySaver

            _test_memory_saver = MemorySaver()
        return _test_memory_saver

    try:
        current_loop = asyncio.get_running_loop()
    except RuntimeError:
        current_loop = None

    loop_compatible = (
        current_loop is None or _checkpointer_loop is None or _checkpointer_loop is current_loop
    )
    if (
        _checkpointer is not None
        and _checkpointer_pool is not None
        and not _checkpointer_pool.closed
        and loop_compatible
    ):
        return _checkpointer

    return await init_checkpointer(db_url=db_url)


def get_compiled_graph(
    custom_checkpointer: BaseCheckpointSaver | None = None,
) -> CompiledStateGraph:
    """Retrieve compiled StateGraph bound to the global or custom checkpointer."""
    global _compiled_graph, _test_memory_saver
    if custom_checkpointer is not None:
        return create_agent_graph(checkpointer=custom_checkpointer)
    if _compiled_graph is not None:
        return _compiled_graph
    if _checkpointer is not None:
        _compiled_graph = create_agent_graph(checkpointer=_checkpointer)
        return _compiled_graph

    settings = get_settings()
    if settings.is_testing:
        if _test_memory_saver is None:
            from langgraph.checkpoint.memory import MemorySaver

            _test_memory_saver = MemorySaver()
        return create_agent_graph(checkpointer=_test_memory_saver)

    raise RuntimeError(
        "WorkflowEngine checkpointer is not initialized. Ensure 'init_checkpointer()' "
        "has been called or pass an active checkpointer."
    )


class WorkflowEngine:
    """Engine orchestrating execution runs, state recovery, and human approval resumption."""

    @staticmethod
    def generate_thread_id(run_id: uuid.UUID) -> str:
        """Derive a stable, deterministic thread identifier bound to the run."""
        return f"flowpilot_run_{run_id}"

    @classmethod
    async def start_run(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: str,
        provider: str | None = None,
        model: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
        existing_run_id: uuid.UUID | None = None,
    ) -> AgentRun:
        """Execute an agent run up to completion or approval interrupt.

        Supports new or pre-created runs.
        """
        if existing_run_id is not None:
            result = await db.execute(select(AgentRun).where(AgentRun.id == existing_run_id))
            agent_run = result.scalar_one_or_none()
            if not agent_run:
                raise ValueError(f"Run {existing_run_id} not found.")
            run_id = agent_run.id
            thread_id = agent_run.thread_id
            if agent_run.cancellation_requested:
                agent_run.status = AgentRunStatus.CANCELLED
                agent_run.completed_at = datetime.now(UTC)
                await db.commit()
                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="engine",
                    event_type="run_cancelled",
                    event_payload={"reason": "Workflow cancelled before execution began."},
                )
                return agent_run
            agent_run.status = AgentRunStatus.RUNNING
            agent_run.heartbeat_at = datetime.now(UTC)
            await db.commit()
            await db.refresh(agent_run)
        else:
            run_id = uuid.uuid4()
            thread_id = cls.generate_thread_id(run_id)
            agent_run = AgentRun(
                id=run_id,
                user_id=user_id,
                thread_id=thread_id,
                original_request=request,
                status=AgentRunStatus.RUNNING,
                current_step=0,
                heartbeat_at=datetime.now(UTC),
            )
            db.add(agent_run)
            await db.commit()
            await db.refresh(agent_run)

        # Build initial LangGraph state
        initial_state: AgentState = {
            "run_id": str(run_id),
            "user_id": str(user_id),
            "thread_id": thread_id,
            "original_request": request,
            "provider": provider,
            "model": model,
            "current_step": 0,
            "step_results": [],
            "executed_step_ids": [],
            "approval_status": "pending",
            "execution_status": "running",
            "correction_attempts": 0,
        }

        thread_config = {"configurable": {"thread_id": thread_id}}
        active_checkpointer = checkpointer or await get_or_init_checkpointer()
        graph = get_compiled_graph(custom_checkpointer=active_checkpointer)

        try:
            # Execute graph synchronously up to terminal state or interrupt
            output_state = await graph.ainvoke(initial_state, config=thread_config)
            await cls._sync_run_state(db, run_id, output_state, graph, thread_config)

        except Exception as exc:
            logger.exception("Unexpected error executing run %s: %s", run_id, exc)
            agent_run.status = AgentRunStatus.FAILED
            agent_run.error_message = str(exc)
            agent_run.completed_at = datetime.now(UTC)
            await db.commit()

        await db.refresh(agent_run)
        return agent_run

    @classmethod
    async def resume_run(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        decision: str,  # "approve" or "reject"
        comment: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Resume an interrupted agent run following a human reviewer decision."""
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        agent_run = result.scalar_one_or_none()

        if not agent_run:
            raise ValueError(f"Run {run_id} not found.")

        # Multi-user security check
        if agent_run.user_id != user_id:
            raise PermissionError("Access denied: You do not have permission to resume this run.")

        # Check for cancellation
        if agent_run.cancellation_requested:
            agent_run.status = AgentRunStatus.CANCELLED
            agent_run.completed_at = datetime.now(UTC)
            await db.commit()
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="engine",
                event_type="run_cancelled",
                event_payload={"reason": "Run cancelled prior to approval resumption."},
            )
            return agent_run

        # Concurrency / repeated approval protection (allows AWAITING_APPROVAL, QUEUED, and RUNNING)
        if agent_run.status not in (
            AgentRunStatus.AWAITING_APPROVAL,
            AgentRunStatus.QUEUED,
            AgentRunStatus.RUNNING,
        ):
            raise ValueError(
                f"Run {run_id} cannot be resumed because it is in '{agent_run.status}' state "
                "(expected 'awaiting_approval' or 'running')."
            )

        thread_id = agent_run.thread_id
        thread_config = {"configurable": {"thread_id": thread_id}}
        active_checkpointer = checkpointer or await get_or_init_checkpointer()
        graph = get_compiled_graph(custom_checkpointer=active_checkpointer)

        resume_command = Command(resume={"decision": decision, "comment": comment})

        try:
            output_state = await graph.ainvoke(resume_command, config=thread_config)
            await cls._sync_run_state(db, run_id, output_state, graph, thread_config)

        except Exception as exc:
            logger.exception("Error resuming run %s: %s", run_id, exc)
            agent_run.status = AgentRunStatus.FAILED
            agent_run.error_message = str(exc)
            agent_run.completed_at = datetime.now(UTC)
            await db.commit()

        await db.refresh(agent_run)
        return agent_run

    @classmethod
    async def _sync_run_state(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        output_state: dict[str, Any] | None,
        graph: CompiledStateGraph,
        thread_config: dict[str, Any],
    ) -> None:
        """Synchronize checkpointed state back into the relational AgentRun record."""
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_id))
        agent_run = result.scalar_one_or_none()
        if not agent_run:
            return

        # Check if the graph is currently halted on an interrupt
        state_snapshot = await graph.aget_state(thread_config)
        is_interrupted = bool(
            state_snapshot.tasks and any(t.interrupts for t in state_snapshot.tasks)
        )

        snapshot_values = state_snapshot.values or {}
        combined = {**snapshot_values, **(output_state or {})}

        agent_run.detected_intent = combined.get("detected_intent")
        agent_run.execution_plan = combined.get("execution_plan")
        agent_run.current_step = combined.get("current_step", agent_run.current_step)
        agent_run.final_result = combined.get("final_response")
        agent_run.error_message = combined.get("error_details")

        if (
            combined.get("approval_status") == "rejected"
            or combined.get("execution_status") == "rejected"
        ):
            agent_run.status = AgentRunStatus.REJECTED
            agent_run.completed_at = datetime.now(UTC)
        elif combined.get("execution_status") == "failed":
            agent_run.status = AgentRunStatus.FAILED
            agent_run.completed_at = datetime.now(UTC)
        elif is_interrupted:
            agent_run.status = AgentRunStatus.AWAITING_APPROVAL
        elif combined.get("execution_status") == "completed":
            agent_run.status = AgentRunStatus.COMPLETED
            agent_run.completed_at = datetime.now(UTC)
        elif combined.get("approval_status") == "pending":
            agent_run.status = AgentRunStatus.AWAITING_APPROVAL
        else:
            agent_run.status = AgentRunStatus.RUNNING

        await db.commit()
