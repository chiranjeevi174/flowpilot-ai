"""Planning Agent: Translates structured intent into validated, policy-compliant execution plans."""

import json
import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from flowpilot.agents.events import extract_json_payload, record_event
from flowpilot.agents.prompts import (
    PLANNER_SYSTEM_PROMPT,
    PLANNER_USER_TEMPLATE,
)
from flowpilot.agents.state import AgentState
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.llm.gateway import CredentialNotFoundError, NoPreferenceConfiguredError, gateway
from flowpilot.llm.providers import LLMMessage
from flowpilot.schemas.agents import ExecutionPlan, PlanStep
from flowpilot.workflows.tools import (
    SUPPORTED_CAPABILITIES,
    is_capability_supported,
    is_operation_sensitive,
)

logger = get_logger("agents.planner")


async def plan_workflow_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """LangGraph node: Generates and validates an execution plan against allowed capabilities."""
    run_id = state["run_id"]
    user_id = uuid.UUID(state["user_id"])
    original_request = state["original_request"]
    detected_intent = state.get("detected_intent") or {}
    provider = state.get("provider")
    model = state.get("model")

    logger.info("Executing plan generation [run_id=%s, user_id=%s]", run_id, user_id)

    session_maker = async_session_factory()
    async with session_maker() as db:
        try:
            messages = [
                LLMMessage(role="system", content=PLANNER_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=PLANNER_USER_TEMPLATE.format(
                        user_request=original_request,
                        intent_json=json.dumps(detected_intent, indent=2),
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
            plan = ExecutionPlan.model_validate(raw_dict)

            # 1. Handle explicit unsupported capability flag from model
            if plan.unsupported_capability:
                reason = (
                    plan.unsupported_reason
                    or "The requested capability requires unsupported external integrations."
                )
                logger.warning("Unsupported capability requested: %s", reason)
                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="planning_agent",
                    event_type="plan_unsupported_capability",
                    event_payload={"reason": reason},
                )
                return {
                    "execution_plan": [],
                    "execution_status": "failed",
                    "error_details": reason,
                    "final_response": {
                        "error": "UnsupportedCapabilityError",
                        "message": reason,
                        "supported_capabilities": sorted(SUPPORTED_CAPABILITIES),
                    },
                }

            # 2. Strict Allowlist & Security Validation of Proposed Steps
            validated_steps: list[PlanStep] = []
            for step in plan.steps:
                op_name = step.operation.strip().lower()

                # Validate against explicit allowlist of registered capabilities
                if not is_capability_supported(op_name):
                    reason = (
                        f"Proposed operation '{step.operation}' is not an authorized capability. "
                        f"Allowed capabilities: {sorted(SUPPORTED_CAPABILITIES)}."
                    )
                    logger.warning("Disallowed operation rejected: %s", reason)
                    await record_event(
                        db=db,
                        run_id=run_id,
                        agent_name="planning_agent",
                        event_type="plan_validation_failed",
                        event_payload={"disallowed_operation": step.operation, "reason": reason},
                    )
                    return {
                        "execution_plan": [],
                        "execution_status": "failed",
                        "error_details": reason,
                        "final_response": {
                            "error": "DisallowedCapabilityError",
                            "message": reason,
                        },
                    }

                # Preserve parameters extracted during intent analysis
                # that were omitted by the planner
                intent_params = detected_intent.get("parameters") or {}
                for k, v in intent_params.items():
                    if k not in step.parameters and v is not None:
                        step.parameters[k] = v

                # Normalize integration parameter aliases to match handler contracts
                if "to" in step.parameters and "recipient" not in step.parameters:
                    step.parameters["recipient"] = step.parameters["to"]
                if "phone_number" in step.parameters and "recipient" not in step.parameters:
                    step.parameters["recipient"] = step.parameters["phone_number"]
                if "template" in step.parameters and "template_name" not in step.parameters:
                    step.parameters["template_name"] = step.parameters["template"]
                if "language" in step.parameters and "language_code" not in step.parameters:
                    step.parameters["language_code"] = step.parameters["language"]
                if (
                    "message" in step.parameters
                    and "body" not in step.parameters
                    and op_name.startswith("gmail_")
                ):
                    step.parameters["body"] = step.parameters["message"]
                if (
                    "content" in step.parameters
                    and "body" not in step.parameters
                    and op_name.startswith("gmail_")
                ):
                    step.parameters["body"] = step.parameters["content"]

                # Ensure parameters contain the user's input/context if missing
                if not step.parameters.get("text") and not step.parameters.get("context"):
                    step.parameters["text"] = original_request

                # Enforce backend approval policy:
                # Backend policy overrides LLM proposal: LLM cannot bypass approval requirement
                if is_operation_sensitive(op_name, step.parameters):
                    step.approval_required = True

                validated_steps.append(step)

            if not validated_steps:
                reason = "No valid operational steps could be formulated for this request."
                await record_event(
                    db=db,
                    run_id=run_id,
                    agent_name="planning_agent",
                    event_type="plan_validation_failed",
                    event_payload={"reason": reason},
                )
                return {
                    "execution_plan": [],
                    "execution_status": "failed",
                    "error_details": reason,
                    "final_response": {"error": reason},
                }

            plan_dicts = [s.model_dump() for s in validated_steps]

            # Record telemetry event
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="planning_agent",
                event_type="plan_generated",
                event_payload={"step_count": len(plan_dicts), "steps": plan_dicts},
            )

            return {
                "execution_plan": plan_dicts,
                "current_step": 2,
                "execution_status": "running",
            }

        except (NoPreferenceConfiguredError, CredentialNotFoundError) as exc:
            error_msg = str(exc)
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="planning_agent",
                event_type="plan_failed",
                event_payload={"error": error_msg, "error_type": type(exc).__name__},
            )
            return {
                "execution_status": "failed",
                "error_details": error_msg,
                "final_response": {"error": error_msg},
            }
        except Exception as exc:
            error_msg = f"Planning failed: {exc}"
            logger.exception(error_msg)
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="planning_agent",
                event_type="plan_failed",
                event_payload={"error": str(exc)},
            )
            return {
                "execution_status": "failed",
                "error_details": error_msg,
                "final_response": {"error": error_msg},
            }
