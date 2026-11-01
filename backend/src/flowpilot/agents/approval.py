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

    executed_step_ids = set(state.get("executed_step_ids") or [])
    unexecuted_steps = [s for s in execution_plan if s.get("step_id") not in executed_step_ids]

    # If all planned operations have already executed, no approval is needed
    if not unexecuted_steps:
        logger.info("No unexecuted operations remaining in plan [run_id=%s]", run_id)
        return {
            "approval_status": "not_required",
            "execution_status": "running",
        }

    # Identify the next step to execute
    next_step = unexecuted_steps[0]
    next_is_sensitive = next_step.get("approval_required") or is_operation_sensitive(
        next_step.get("operation", ""), next_step.get("parameters")
    )

    # If the upcoming step is not sensitive, proceed directly to executor
    if not next_is_sensitive:
        logger.info(
            "Next operation '%s' (%s) is not sensitive; proceeding to execution [run_id=%s]",
            next_step.get("step_id"),
            next_step.get("operation"),
            run_id,
        )
        return {
            "approval_status": "not_required",
            "execution_status": "running",
        }

    # If the sensitive step was already approved or rejected in a previous turn
    if current_approval_status == "approved":
        return {
            "approval_status": "approved",
            "execution_status": "running",
        }
    if current_approval_status == "rejected":
        return {
            "approval_status": "rejected",
            "execution_status": "rejected",
        }

    # The upcoming step requires human approval.
    # Preceding non-sensitive steps have already succeeded; resolve any placeholders
    # (e.g. output_from_step_X) and missing fields using real execution outputs:
    from flowpilot.agents.resolution import resolve_step_placeholders
    from flowpilot.integrations.security import compute_parameter_digest
    from flowpilot.models.user import User

    user_uuid = uuid.UUID(state["user_id"])
    session_maker = async_session_factory()
    user_email = None
    async with session_maker() as db:
        user_record = await db.get(User, user_uuid)
        if user_record:
            user_email = user_record.email

    step_params = resolve_step_placeholders(
        parameters=dict(next_step.get("parameters") or {}),
        step_results=state.get("step_results") or [],
        user_email=user_email,
        operation=next_step.get("operation", ""),
    )

    # Ensure proposed email body is strictly verified against numerical inaccuracies & currency
    if step_params.get("body") and isinstance(step_params["body"], str):
        from flowpilot.agents.analysis import (
            TabularAnalysis,
            clean_numerical_contradictions,
            find_numerical_contradictions,
            rectify_text_numbers,
            validate_summary_accuracy,
        )

        # Build active analysis from preceding step results if available
        active_analysis = None
        for r in state.get("step_results") or []:
            res = r.get("result") or {}
            if (
                isinstance(res, dict)
                and "rows" in res
                and isinstance(res["rows"], list)
                and res["rows"]
            ):
                from flowpilot.agents.analysis import analyze_tabular_dataset

                active_analysis = analyze_tabular_dataset(
                    res["rows"], sheet_title=res.get("range", "Dataset")
                )
                break

        if active_analysis is None:
            active_analysis = TabularAnalysis(
                sheet_title="Dataset",
                total_rows_retrieved=0,
                data_row_count=0,
                is_truncated=False,
                headers=[],
                columns={},
                currency_detected=None,
                currency_note="No currency established.",
                date_range_note="",
            )

        step_params["body"] = rectify_text_numbers(step_params["body"], active_analysis)

        # Strict safety invariant: contradictory statements cannot reach the approval gate
        contradictions = find_numerical_contradictions(step_params["body"], active_analysis)
        if contradictions:
            logger.warning(
                "Contradictory numerical claims detected before approval gate: %s", contradictions
            )
            step_params["body"] = clean_numerical_contradictions(
                step_params["body"], active_analysis
            )

        # Pre-send validation: ensure no unresolved errors remain before gate
        val_errors = validate_summary_accuracy(step_params["body"], active_analysis)
        if val_errors:
            logger.warning("Pre-approval validation detected issues: %s", val_errors)
            step_params["body"] = rectify_text_numbers(step_params["body"], active_analysis)

    # Update next_step parameters in execution_plan so state and digests stay in sync
    next_step["parameters"] = step_params

    param_digest = compute_parameter_digest(step_params)

    # Prepare interrupt payload describing proposed action to reviewer
    approval_payload = {
        "run_id": run_id,
        "step_id": next_step.get("step_id"),
        "operation": next_step.get("operation"),
        "parameters": step_params,
        "parameter_digest": param_digest,
        "expected_outcome": next_step.get("expected_outcome", ""),
        "message": (
            f"Operation '{next_step.get('operation')}' is classified as sensitive and "
            "requires human authorization before execution."
        ),
        "recipient": step_params.get("recipient") or step_params.get("to"),
        "subject": step_params.get("subject"),
        "body": step_params.get("body"),
    }

    # Update database state to awaiting_approval and log audit event before pausing
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

                op_label = next_step.get("operation", "action")
                await NotificationService.create_or_update_notification(
                    db=db,
                    user_id=agent_run.user_id,
                    type=NotificationType.APPROVAL_REQUIRED,
                    title="Approval Required",
                    message=(
                        f"Workflow execution is waiting for authorization to execute {op_label}."
                    ),
                    dedup_key=f"approval_requested_{run_id}_{next_step.get('step_id')}",
                    category="approval",
                    link_url=f"/approvals?run_id={run_id}",
                    meta_data={
                        "run_id": str(run_id),
                        "operation": next_step.get("operation"),
                        "step_id": next_step.get("step_id"),
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
        next_step.get("step_id"),
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
            current_step_params = dict(next_step.get("parameters") or {})
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
                    "step_id": next_step.get("step_id"),
                    "operation": next_step.get("operation"),
                    "comment": comment,
                },
            )
            return {
                "approval_status": "approved",
                "execution_status": "running",
                "execution_plan": execution_plan,
            }
        else:
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="approval_gate",
                event_type="approval_rejected",
                event_payload={
                    "step_id": next_step.get("step_id"),
                    "operation": next_step.get("operation"),
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
                    "rejected_step": next_step,
                },
            }
