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
        final_payload = {
            "status": "completed",
            "summary": "Workflow completed and verified successfully.",
            "results": {r["operation"]: r.get("result") for r in step_results},
            "step_records": step_results,
            "verification": verification.model_dump(),
        }
        return {
            "verification_result": verification.model_dump(),
            "execution_status": "completed",
            "final_response": final_payload,
        }

    # 2. Verification failed but can correct within bounds
    if verification.needs_correction and correction_attempts < MAX_CORRECTION_ATTEMPTS:
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
