"""Human-in-the-Loop Approval Gate using LangGraph interrupt and Command(resume=...)."""

import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt
from sqlalchemy import select

from flowpilot.agents.events import record_event
from flowpilot.agents.state import AgentState
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.models.agent_run import AgentRun, AgentRunStatus
from flowpilot.workflows.tools import is_operation_sensitive

logger = get_logger("agents.approval")


async def approval_gate_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """LangGraph node: Evaluates plan sensitivity and triggers interrupt when approval is needed."""
    run_id = state["run_id"]
    execution_plan = state.get("execution_plan") or []
    current_approval_status = state.get("approval_status", "pending")

    # If already decided in previous turn (e.g., during resume replay), respect it
    if current_approval_status in ("approved", "rejected", "not_required"):
        logger.info(
            "Approval gate skipped; already in state '%s' [run_id=%s]",
            current_approval_status,
            run_id,
        )
        return {
            "approval_status": current_approval_status,
        }

    # Find the first step that requires approval (either per plan or backend policy)
    sensitive_step: dict[str, Any] | None = None
    for step in execution_plan:
        if step.get("approval_required") or is_operation_sensitive(
            step.get("operation", ""), step.get("parameters")
        ):
            sensitive_step = step
            break

    # If no step requires approval, proceed directly
    if not sensitive_step:
        logger.info("No sensitive operations found in plan [run_id=%s]", run_id)
        return {
            "approval_status": "not_required",
            "execution_status": "running",
        }

    from flowpilot.integrations.security import compute_parameter_digest

    step_params = dict(sensitive_step.get("parameters") or {})
    param_digest = compute_parameter_digest(step_params)

    # Prepare interrupt payload describing proposed action to reviewer
    approval_payload = {
        "run_id": run_id,
        "step_id": sensitive_step.get("step_id"),
        "operation": sensitive_step.get("operation"),
        "parameters": step_params,
        "parameter_digest": param_digest,
        "expected_outcome": sensitive_step.get("expected_outcome", ""),
        "message": (
            f"Operation '{sensitive_step.get('operation')}' is classified as sensitive and "
            "requires human authorization before execution."
        ),
    }

    # Update database state to awaiting_approval and log audit event before pausing
    session_maker = async_session_factory()
    async with session_maker() as db:
        run_uuid = uuid.UUID(run_id)
        result = await db.execute(select(AgentRun).where(AgentRun.id == run_uuid))
        agent_run = result.scalar_one_or_none()
        if agent_run:
            agent_run.status = AgentRunStatus.AWAITING_APPROVAL
            await db.commit()

            try:
                from flowpilot.models.notification import NotificationType
                from flowpilot.services.notifications import NotificationService

                op_label = sensitive_step.get("operation", "action")
                await NotificationService.create_or_update_notification(
                    db=db,
                    user_id=agent_run.user_id,
                    type=NotificationType.APPROVAL_REQUIRED,
                    title="Approval Required",
                    message=(
                        f"Workflow execution is waiting for authorization to execute {op_label}."
                    ),
                    dedup_key=f"approval_requested_{run_id}_{sensitive_step.get('step_id')}",
                    category="approval",
                    link_url=f"/approvals?run_id={run_id}",
                    meta_data={
                        "run_id": str(run_id),
                        "operation": sensitive_step.get("operation"),
                        "step_id": sensitive_step.get("step_id"),
                        "parameters": step_params,
                    },
                )
            except Exception as notif_err:
                logger.warning("Failed to create approval notification: %s", notif_err)

        await record_event(
            db=db,
            run_id=run_id,
            agent_name="approval_gate",
            event_type="approval_requested",
            event_payload=approval_payload,
        )

    logger.info(
        "Pausing execution for human approval on step '%s' [run_id=%s]",
        sensitive_step.get("step_id"),
        run_id,
    )

    # Trigger durable LangGraph interrupt - execution pauses here until resume Command is submitted
    resume_data = interrupt(approval_payload)

    # --- Resumed from Human Decision ---
    logger.info("Resumed approval gate with decision: %s [run_id=%s]", resume_data, run_id)

    decision = "reject"
    comment = None
    if isinstance(resume_data, dict):
        decision = str(resume_data.get("decision", "reject")).strip().lower()
        comment = resume_data.get("comment")

    async with session_maker() as db:
        try:
            from flowpilot.services.notifications import NotificationService

            await NotificationService.resolve_approval_notification(
                db=db,
                run_id=run_id,
                decision=decision,
            )
        except Exception as notif_err:
            logger.warning("Failed to resolve approval notification: %s", notif_err)

        if decision == "approve":
            current_step_params = dict(sensitive_step.get("parameters") or {})
            if compute_parameter_digest(current_step_params) != param_digest:
                logger.error(
                    "Security violation: step parameters modified post-approval! [run_id=%s]",
                    run_id,
                )
                decision = "reject"
                comment = "Approval invalidated: parameters were modified after approval review."

        if decision == "approve":
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="approval_gate",
                event_type="approval_granted",
                event_payload={
                    "step_id": sensitive_step.get("step_id"),
                    "operation": sensitive_step.get("operation"),
                    "comment": comment,
                },
            )
            return {
                "approval_status": "approved",
                "execution_status": "running",
            }
        else:
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="approval_gate",
                event_type="approval_rejected",
                event_payload={
                    "step_id": sensitive_step.get("step_id"),
                    "operation": sensitive_step.get("operation"),
                    "comment": comment,
                },
            )
            rejection_reason = (
                f"Operation rejected by reviewer: {comment}"
                if comment
                else "Operation was rejected by the reviewer."
            )
            return {
                "approval_status": "rejected",
                "execution_status": "rejected",
                "error_details": rejection_reason,
                "final_response": {
                    "status": "rejected",
                    "reason": rejection_reason,
                    "rejected_step": sensitive_step,
                },
            }
