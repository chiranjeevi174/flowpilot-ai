"""Central Orchestrator Agent interface coordinating LangGraph agents and workflows."""

import uuid

from langgraph.checkpoint.base import BaseCheckpointSaver
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.models.agent_run import AgentRun

logger = get_logger("agents.orchestrator")


class Orchestrator:
    """High-level Orchestrator mediating between API services and multi-agent execution."""

    @classmethod
    async def execute_request(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        request: str,
        provider: str | None = None,
        model: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Initialize and run an end-to-end multi-agent workflow for the authenticated user."""
        from flowpilot.workflows.engine import WorkflowEngine

        logger.info("Orchestrator received user request [user_id=%s]", user_id)
        return await WorkflowEngine.start_run(
            db=db,
            user_id=user_id,
            request=request,
            provider=provider,
            model=model,
            checkpointer=checkpointer,
        )

    @classmethod
    async def handle_approval(
        cls,
        db: AsyncSession,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        decision: str,
        comment: str | None = None,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> AgentRun:
        """Handle human approval decision and resume the paused agent graph."""
        from flowpilot.workflows.engine import WorkflowEngine

        logger.info(
            "Orchestrator resuming run with decision '%s' [run_id=%s, user_id=%s]",
            decision,
            run_id,
            user_id,
        )
        return await WorkflowEngine.resume_run(
            db=db,
            run_id=run_id,
            user_id=user_id,
            decision=decision,
            comment=comment,
            checkpointer=checkpointer,
        )
