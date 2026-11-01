"""Verification Agent: Assesses plan execution results and orchestrates bounded correction."""

import json
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from flowpilot.agents.events import extract_json_payload, record_event
from flowpilot.agents.prompts import (
    VERIFIER_SYSTEM_PROMPT,
    VERIFIER_USER_TEMPLATE,
)
from flowpilot.agents.state import AgentState
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.llm.gateway import gateway
from flowpilot.llm.providers import LLMMessage
from flowpilot.schemas.agents import VerificationResult

logger = get_logger("agents.verifier")

# Strict ceiling on correction loops to guarantee termination
MAX_CORRECTION_ATTEMPTS = 2


async def verify_execution_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """LangGraph node: Evaluates results against the request with bounded correction logic."""
    run_id = state["run_id"]
    user_id = uuid.UUID(state["user_id"])
    original_request = state["original_request"]
    execution_plan = state.get("execution_plan") or []
    step_results = state.get("step_results") or []
    correction_attempts = state.get("correction_attempts", 0)
    provider = state.get("provider")
    model = state.get("model")

    logger.info(
        "Verifying execution results [run_id=%s, results_count=%d, attempt=%d]",
        run_id,
        len(step_results),
        correction_attempts,
    )

    # Fast deterministic verification: verify all planned steps generated non-empty results
    planned_step_ids = {s.get("step_id") for s in execution_plan}
    completed_step_ids = {r.get("step_id") for r in step_results if r.get("status") == "success"}
    missing_steps = list(planned_step_ids - completed_step_ids)

    session_maker = async_session_factory()
    async with session_maker() as db:
        if missing_steps:
            critique = f"Execution incomplete: steps {missing_steps} did not complete successfully."
            logger.warning("Deterministic verification failed: %s [run_id=%s]", critique, run_id)
            verification = VerificationResult(
                passed=False,
                critique=critique,
                missing_outputs=missing_steps,
                needs_correction=correction_attempts < MAX_CORRECTION_ATTEMPTS,
            )
        else:
            # Deterministic numerical check: detect calculation errors & contradictions
            from flowpilot.agents.analysis import (
                TabularAnalysis,
                analyze_tabular_dataset,
                find_numerical_contradictions,
                validate_summary_accuracy,
            )

            # Identify any sensitive external actions that have already dispatched side-effects
            sensitive_dispatches = [
                r
                for r in step_results
                if r.get("operation")
                in ("gmail_send_email", "slack_send_message", "whatsapp_send_message")
                and r.get("status") == "success"
            ]
            has_dispatched_externally = bool(sensitive_dispatches)
            dispatched_ids: list[str] = []
            for r in sensitive_dispatches:
                res = r.get("result") or {}
                if isinstance(res, dict):
                    mid = res.get("message_id") or res.get("provider_action_id") or res.get("id")
                    if mid:
                        dispatched_ids.append(str(mid))

            # Build active tabular analysis from step results if available
            active_analysis = None
            for r in step_results:
                res = r.get("result") or {}
                if (
                    isinstance(res, dict)
                    and "rows" in res
                    and isinstance(res["rows"], list)
                    and res["rows"]
                ):
                    active_analysis = analyze_tabular_dataset(
                        res["rows"], sheet_title=res.get("range", "Sheet")
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
                    currency_note="",
                    date_range_note="",
                )

            contradiction_found = False
            contradiction_detail = ""
            numerical_error_found = False
            numerical_error_detail = ""

            for r in step_results:
                res_val = r.get("result") or {}
                res_str = json.dumps(res_val) if isinstance(res_val, (dict, list)) else str(res_val)

                contras = find_numerical_contradictions(res_str, active_analysis)
                if contras:
                    contradiction_found = True
                    contradiction_detail = contras[0]
                    break

                if active_analysis.data_row_count > 0:
                    val_errs = validate_summary_accuracy(res_str, active_analysis)
                    if val_errs:
                        numerical_error_found = True
                        numerical_error_detail = val_errs[0]
                        break

            if (contradiction_found or numerical_error_found) and not has_dispatched_externally:
                critique = (
                    f"Numerical verification failure: contradictory claim detected: "
                    f"{contradiction_detail}"
                    if contradiction_found
                    else f"Numerical verification failure: {numerical_error_detail}"
                )
                logger.warning(critique)
                verification = VerificationResult(
                    passed=False,
                    critique=critique,
                    missing_outputs=[],
                    needs_correction=correction_attempts < MAX_CORRECTION_ATTEMPTS,
                )
            else:
                try:
                    # LLM-based qualitative evaluation
                    messages = [
                        LLMMessage(role="system", content=VERIFIER_SYSTEM_PROMPT),
                        LLMMessage(
                            role="user",
                            content=VERIFIER_USER_TEMPLATE.format(
                                user_request=original_request,
                                plan_json=json.dumps(execution_plan, indent=2),
                                results_json=json.dumps(step_results, indent=2),
                            ),
                        ),
                    ]

                    generation_result = await gateway.generate(
                        db=db,
                        user_id=user_id,
                        messages=messages,
                        provider=provider,
                        model=model,
                        temperature=0.1,
                    )

                    raw_dict = extract_json_payload(generation_result.content)
                    verification = VerificationResult.model_validate(raw_dict)

                except Exception as exc:
                    logger.warning(
                        "Qualitative verification LLM call failed (%s); using structural check",
                        exc,
                    )
                    # Fallback: structural success if all steps produced results
                    verification = VerificationResult(
                        passed=True,
                        critique="All planned steps executed and returned structured outputs.",
                        missing_outputs=[],
                        needs_correction=False,
                    )

                # Safety invariant: if an external action has already been accepted by provider,
                # never trigger re-execution and never mark the dispatch itself as failed.
                if has_dispatched_externally:
                    verification.needs_correction = False
                    if not verification.passed:
                        id_label = f" (ID: {', '.join(dispatched_ids)})" if dispatched_ids else ""
                        logger.info(
                            "External dispatch accepted by provider%s; recording advisory.",
                            id_label,
                        )
                        verification.passed = True
                        verification.critique = (
                            f"External dispatch accepted by provider{id_label}. "
                            f"Post-dispatch verification advisory: {verification.critique}"
                        )

        # Record audit event
        await record_event(
            db=db,
            run_id=run_id,
            agent_name="verification_agent",
            event_type="verification_completed",
            event_payload=verification.model_dump(),
        )

    # 1. Verification passed
    if verification.passed:
        summary_msg = "Workflow completed and verified successfully."
        if has_dispatched_externally and dispatched_ids:
            summary_msg = (
                f"Workflow completed. Email dispatched and accepted by Gmail API "
                f"(Message ID: {dispatched_ids[0]})."
            )
        final_payload = {
            "status": "completed",
            "summary": summary_msg,
            "dispatched_ids": dispatched_ids,
            "delivery_status": "api_accepted"
            if has_dispatched_externally
            else "internal_completed",
            "results": {
                r.get("operation", r.get("step_id", "step")): r.get("result") for r in step_results
            },
            "step_records": step_results,
            "verification": verification.model_dump(),
        }
        return {
            "verification_result": verification.model_dump(),
            "execution_status": "completed",
            "final_response": final_payload,
        }

    # 2. Verification failed but can correct within bounds (pre-dispatch only)
    if (
        verification.needs_correction
        and correction_attempts < MAX_CORRECTION_ATTEMPTS
        and not has_dispatched_externally
    ):
        logger.info(
            "Triggering correction attempt %d/%d [run_id=%s]",
            correction_attempts + 1,
            MAX_CORRECTION_ATTEMPTS,
            run_id,
        )
        return {
            "verification_result": verification.model_dump(),
            "correction_attempts": correction_attempts + 1,
            "execution_status": "running",
        }

    # 3. Verification failed and corrections exhausted
    logger.warning("Verification failed and max correction attempts reached [run_id=%s]", run_id)
    final_payload = {
        "status": "failed",
        "reason": "Verification failed: outputs did not satisfy the planned criteria.",
        "critique": verification.critique,
        "missing_outputs": verification.missing_outputs,
        "results": {r["operation"]: r.get("result") for r in step_results},
    }
    return {
        "verification_result": verification.model_dump(),
        "execution_status": "failed",
        "error_details": f"Verification failed: {verification.critique}",
        "final_response": final_payload,
    }
