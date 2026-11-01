"""Intent Analysis Agent: Evaluates user requests and extracts structured intent."""

import uuid
from typing import Any

from langchain_core.runnables import RunnableConfig

from flowpilot.agents.events import extract_json_payload, record_event
from flowpilot.agents.prompts import (
    INTENT_ANALYZER_SYSTEM_PROMPT,
    INTENT_ANALYZER_USER_TEMPLATE,
)
from flowpilot.agents.state import AgentState
from flowpilot.core.logging import get_logger
from flowpilot.db.session import async_session_factory
from flowpilot.llm.gateway import CredentialNotFoundError, NoPreferenceConfiguredError, gateway
from flowpilot.llm.providers import LLMMessage
from flowpilot.schemas.agents import IntentAnalysisResult
from flowpilot.workflows.tools import SUPPORTED_CAPABILITIES

logger = get_logger("agents.intent")


def _is_supported_or_integration_intent(
    intent_result: IntentAnalysisResult, original_request: str
) -> bool:
    """Check if the user request or extracted intent targets supported capabilities."""
    action = (intent_result.action or "").strip().lower()
    if action in SUPPORTED_CAPABILITIES:
        return True

    params = intent_result.parameters or {}
    tool = str(params.get("tool") or params.get("tool_name") or "").strip().lower()
    if tool in SUPPORTED_CAPABILITIES:
        return True

    req_lower = original_request.lower()
    for cap in SUPPORTED_CAPABILITIES:
        if cap in req_lower:
            return True

    supported_services = ("gmail", "whatsapp", "slack", "sheets", "spreadsheet")
    return bool(any(svc in req_lower or svc in action for svc in supported_services))


async def analyze_intent_node(
    state: AgentState, config: RunnableConfig | None = None
) -> dict[str, Any]:
    """LangGraph node: Analyzes natural-language request and extracts structured intent."""
    run_id = state["run_id"]
    user_id = uuid.UUID(state["user_id"])
    original_request = state["original_request"]
    provider = state.get("provider")
    model = state.get("model")

    logger.info("Executing intent analysis [run_id=%s, user_id=%s]", run_id, user_id)

    # Resolve database session for gateway and event recording
    session_maker = async_session_factory()
    async with session_maker() as db:
        try:
            # Build messages for LLM Gateway
            messages = [
                LLMMessage(role="system", content=INTENT_ANALYZER_SYSTEM_PROMPT),
                LLMMessage(
                    role="user",
                    content=INTENT_ANALYZER_USER_TEMPLATE.format(user_request=original_request),
                ),
            ]

            # Invoke unified gateway
            generation_result = await gateway.generate(
                db=db,
                user_id=user_id,
                messages=messages,
                provider=provider,
                model=model,
                temperature=0.1,
            )

            raw_dict = extract_json_payload(generation_result.content)
            intent_result = IntentAnalysisResult.model_validate(raw_dict)

            # If request targets supported internal or external integration capabilities,
            # ensure is_actionable is not falsely set to False by LLM provider text-only bias
            if not intent_result.is_actionable and _is_supported_or_integration_intent(
                intent_result, original_request
            ):
                intent_result.is_actionable = True

            # If clarification was requested solely for missing email recipient,
            # but this is an analytical/data workflow (e.g. Google Sheets summary),
            # recipient defaults to the authenticated user for review at the approval gate
            if intent_result.requires_clarification and _is_supported_or_integration_intent(
                intent_result, original_request
            ):
                req_lower = original_request.lower()
                is_analysis_flow = any(
                    k in req_lower
                    for k in (
                        "sheet",
                        "spreadsheet",
                        "data",
                        "dataset",
                        "summary",
                        "report",
                        "analyz",
                        "calculate",
                    )
                )
                msg = (intent_result.clarification_message or "").lower()
                if is_analysis_flow and ("recipient" in msg or "email address" in msg):
                    logger.info(
                        "Overriding clarification: recipient defaults to user for analysis workflow"
                    )
                    intent_result.requires_clarification = False
                    intent_result.clarification_message = None

            # Record telemetry event
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="intent_analyzer",
                event_type="intent_detected",
                event_payload=intent_result.model_dump(),
            )

            # 1. Genuine ambiguity or lack of critical details
            if intent_result.requires_clarification:
                clarification = (
                    intent_result.clarification_message
                    or "Request could not be processed because it is ambiguous or lacks details."
                )
                return {
                    "detected_intent": intent_result.model_dump(),
                    "current_step": 1,
                    "execution_status": "failed",
                    "final_response": {"message": clarification, "status": "clarification_needed"},
                    "error_details": clarification,
                }

            # 2. Unsupported capability outside platform scope
            if not intent_result.is_actionable:
                reason = intent_result.clarification_message or (
                    "The requested capability is not supported by FlowPilot. "
                    "Supported capabilities include text operations and Gmail, "
                    "WhatsApp, Slack, and Google Sheets integrations."
                )
                return {
                    "detected_intent": intent_result.model_dump(),
                    "current_step": 1,
                    "execution_status": "failed",
                    "final_response": {"message": reason, "status": "unsupported_capability"},
                    "error_details": reason,
                }

            return {
                "detected_intent": intent_result.model_dump(),
                "current_step": 1,
                "execution_status": "running",
            }

        except (NoPreferenceConfiguredError, CredentialNotFoundError) as exc:
            error_msg = str(exc)
            logger.error("Intent analysis configuration error: %s", error_msg)
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="intent_analyzer",
                event_type="intent_failed",
                event_payload={"error": error_msg, "error_type": type(exc).__name__},
            )
            return {
                "execution_status": "failed",
                "error_details": error_msg,
                "final_response": {"error": error_msg},
            }
        except Exception as exc:
            error_msg = f"Intent analysis failed: {exc}"
            logger.exception(error_msg)
            await record_event(
                db=db,
                run_id=run_id,
                agent_name="intent_analyzer",
                event_type="intent_failed",
                event_payload={"error": str(exc)},
            )
            return {
                "execution_status": "failed",
                "error_details": error_msg,
                "final_response": {"error": error_msg},
            }
