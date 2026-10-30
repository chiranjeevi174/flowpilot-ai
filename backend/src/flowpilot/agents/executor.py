"""Execution Agent: Dispatches and executes validated plan steps using registered internal tools."""

import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from flowpilot.agents.events import record_event
from flowpilot.agents.state import AgentState
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.workflows.tools import get_tool_handler

logger = get_logger("agents.executor")


async def execute_plan_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """LangGraph node: Safely executes planned steps sequentially with idempotency safeguards."""
    run_id = state["run_id"]
    user_id = uuid.UUID(state["user_id"])
    execution_plan = state.get("execution_plan") or []
    provider = state.get("provider")
    model = state.get("model")

    # Replay protection: skip steps that were already completed in a prior invocation
    executed_step_ids = list(state.get("executed_step_ids") or [])
    step_results = list(state.get("step_results") or [])

    logger.info(
        "Executing plan [run_id=%s, total_steps=%d, already_executed=%d]",
        run_id,
        len(execution_plan),
        len(executed_step_ids),
    )

    session_maker = async_session_factory()
    async with session_maker() as db:
        for step in execution_plan:
            step_id = step.get("step_id")
            operation = step.get("operation", "")

            # Idempotency check: Skip already-executed steps
            if step_id in executed_step_ids:
                logger.debug("Skipping already executed step '%s' [run_id=%s]", step_id, run_id)
                continue

            handler = get_tool_handler(operation)
            if handler is None:
                err_msg = f"No executable handler registered for capability '{operation}'."
                logger.error(err_msg)
                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="execution_agent",
                    event_type="step_failed",
                    event_payload={"step_id": step_id, "operation": operation, "error": err_msg},
                )
                return {
                    "step_results": step_results,
                    "executed_step_ids": executed_step_ids,
                    "execution_status": "failed",
                    "error_details": err_msg,
                    "final_response": {"error": err_msg},
                }

            logger.info("Executing step '%s' (%s) [run_id=%s]", step_id, operation, run_id)
            parameters = dict(step.get("parameters") or {})

            # Feed forward context or prior step outputs if available
            if step_results and not parameters.get("previous_results"):
                parameters["previous_results"] = [r.get("result") for r in step_results]

            # Bind run_id, step_id, and approval decision for external audit and idempotency
            parameters["run_id"] = str(run_id)
            parameters["step_id"] = str(step_id)
            if state.get("approval_status") == "approved":
                from flowpilot.integrations.security import compute_parameter_digest

                parameters["approved"] = True
                parameters["approval_reference"] = "approved_by_user"
                parameters["approval_parameter_digest"] = compute_parameter_digest(
                    dict(step.get("parameters") or {})
                )

            try:
                outcome = await handler(
                    db=db,
                    user_id=user_id,
                    parameters=parameters,
                    provider=provider,
                    model=model,
                )

                step_record = {
                    "step_id": step_id,
                    "operation": operation,
                    "status": "success",
                    "result": outcome.get("result"),
                    "provider": outcome.get("provider_used"),
                    "model": outcome.get("model_used"),
                }

                step_results.append(step_record)
                executed_step_ids.append(step_id)

                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="execution_agent",
                    event_type="step_executed",
                    event_payload={
                        "step_id": step_id,
                        "operation": operation,
                        "status": "success",
                    },
                )

            except Exception as exc:
                err_msg = f"Step '{step_id}' ({operation}) execution failed: {exc}"
                logger.exception(err_msg)
                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="execution_agent",
                    event_type="step_failed",
                    event_payload={
                        "step_id": step_id,
                        "operation": operation,
                        "error": str(exc),
                    },
                )
                return {
                    "step_results": step_results,
                    "executed_step_ids": executed_step_ids,
                    "execution_status": "failed",
                    "error_details": err_msg,
                    "final_response": {"error": err_msg, "failed_step": step_id},
                }

    return {
        "step_results": step_results,
        "executed_step_ids": executed_step_ids,
        "current_step": len(executed_step_ids) + 2,
        "execution_status": "running",
    }
