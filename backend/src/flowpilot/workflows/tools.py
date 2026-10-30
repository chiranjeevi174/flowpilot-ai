"""Internal safe tool registry and capability allowlist for FlowPilot multi-agent execution."""

import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.llm.gateway import gateway
from flowpilot.llm.providers import LLMMessage

logger = get_logger("workflows.tools")

# Allowlist of strictly permitted operations (internal + authorized external integrations)
INTERNAL_CAPABILITIES: frozenset[str] = frozenset(
    {
        "text_categorization",
        "information_extraction",
        "response_drafting",
        "task_summary_generation",
    }
)

EXTERNAL_INTEGRATION_CAPABILITIES: frozenset[str] = frozenset(
    {
        "gmail_list_messages",
        "gmail_get_message",
        "gmail_prepare_response",
        "gmail_create_draft",
        "gmail_send_email",
        "slack_list_channels",
        "slack_prepare_message",
        "slack_send_message",
        "sheets_read_range",
        "sheets_append_rows",
        "whatsapp_send_message",
        "whatsapp_send_template",
    }
)

SUPPORTED_CAPABILITIES: frozenset[str] = INTERNAL_CAPABILITIES | EXTERNAL_INTEGRATION_CAPABILITIES

# Backend policy designating sensitive operations that MANDATE human approval
SENSITIVE_OPERATIONS: frozenset[str] = frozenset(
    {
        "response_drafting",
        "gmail_send_email",
        "slack_send_message",
        "sheets_append_rows",
        "whatsapp_send_message",
        "whatsapp_send_template",
    }
)


def is_capability_supported(capability: str) -> bool:
    """Check if a capability is in the explicit allowlist."""
    return capability.strip().lower() in SUPPORTED_CAPABILITIES


def is_operation_sensitive(operation: str, parameters: dict[str, Any] | None = None) -> bool:
    """Determine if an operation requires human-in-the-loop approval per backend policy.

    Backend policy strictly overrides any LLM proposal:
    1. Any operation in SENSITIVE_OPERATIONS mandates approval.
    2. Any operation explicitly flagged with 'is_sensitive' mandates approval.
    """
    op = operation.strip().lower()
    if op in SENSITIVE_OPERATIONS:
        return True
    if parameters:
        if parameters.get("is_sensitive") is True:
            return True
        if parameters.get("requires_approval") is True:
            return True
    return False


# ==============================================================================
# Tool Implementations (Using Unified LLMGateway)
# ==============================================================================


async def execute_text_categorization(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Categorize text into sentiment, topic, urgency, or custom categories."""
    text = parameters.get("text") or parameters.get("input") or ""
    categories = parameters.get("categories") or ["sentiment", "urgency", "topic"]

    prompt = (
        "You are an analytical categorization assistant. Analyze text and assign categories.\n"
        f"Categories to evaluate: {json.dumps(categories)}\n"
        "Return strictly valid JSON with evaluated categories and 'confidence' (0.0 to 1.0).\n\n"
        f"Text to analyze:\n---\n{text}\n---"
    )

    messages = [
        LLMMessage(role="system", content="You are a precise JSON-only categorization engine."),
        LLMMessage(role="user", content=prompt),
    ]

    result = await gateway.generate(
        db=db,
        user_id=user_id,
        messages=messages,
        provider=provider,
        model=model,
        temperature=0.1,
    )

    try:
        parsed = json.loads(result.content.strip())
    except Exception:
        parsed = {"raw_output": result.content, "categories": categories}

    return {
        "operation": "text_categorization",
        "result": parsed,
        "model_used": result.model,
        "provider_used": result.provider,
    }


async def execute_information_extraction(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Extract structured data entities, key fields, and action items from text."""
    text = parameters.get("text") or parameters.get("input") or ""
    schema_fields = parameters.get("fields") or [
        "customer_name",
        "complaint_topic",
        "urgency_level",
        "specific_issues",
        "requested_remedy",
    ]

    prompt = (
        "Extract structured information from the text below.\n"
        f"Fields to extract: {json.dumps(schema_fields)}\n"
        "Return strictly valid JSON with extracted fields. Set missing fields to null.\n\n"
        f"Text:\n---\n{text}\n---"
    )

    messages = [
        LLMMessage(
            role="system", content="You are a structured data extraction engine. Output JSON only."
        ),
        LLMMessage(role="user", content=prompt),
    ]

    result = await gateway.generate(
        db=db,
        user_id=user_id,
        messages=messages,
        provider=provider,
        model=model,
        temperature=0.1,
    )

    try:
        parsed = json.loads(result.content.strip())
    except Exception:
        parsed = {"extracted_data": result.content}

    return {
        "operation": "information_extraction",
        "result": parsed,
        "model_used": result.model,
        "provider_used": result.provider,
    }


async def execute_response_drafting(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Draft a professional, tailored response based on analysis and contextual parameters."""
    context = parameters.get("context") or parameters.get("text") or ""
    tone = parameters.get("tone") or "empathetic, professional, and solution-oriented"
    key_points = parameters.get("key_points") or []

    prompt = (
        "Draft a formal, high-quality business response addressing the context provided below.\n"
        f"Tone: {tone}\n"
        f"Key points to cover: {json.dumps(key_points)}\n"
        "Return strictly valid JSON with keys: 'subject', 'body', 'suggested_action_items'.\n\n"
        f"Context:\n---\n{context}\n---"
    )

    messages = [
        LLMMessage(
            role="system",
            content="You are an executive communications specialist. Output strictly valid JSON.",
        ),
        LLMMessage(role="user", content=prompt),
    ]

    result = await gateway.generate(
        db=db,
        user_id=user_id,
        messages=messages,
        provider=provider,
        model=model,
        temperature=0.3,
    )

    try:
        parsed = json.loads(result.content.strip())
    except Exception:
        parsed = {"subject": "Customer Communication", "body": result.content}

    return {
        "operation": "response_drafting",
        "result": parsed,
        "model_used": result.model,
        "provider_used": result.provider,
    }


async def execute_task_summary_generation(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Synthesize an executive summary with key findings and next steps."""
    text = parameters.get("text") or parameters.get("input") or ""
    previous_results = parameters.get("previous_results")

    prompt = (
        "Generate a concise executive summary based on the following information.\n"
        "Return strictly valid JSON with keys: 'summary', 'key_highlights', 'next_steps'.\n\n"
        f"Source data:\n---\n{text}\n"
        f"Prior results: {json.dumps(previous_results) if previous_results else 'None'}\n---"
    )

    messages = [
        LLMMessage(
            role="system", content="You are a senior workflow analyst. Output strictly valid JSON."
        ),
        LLMMessage(role="user", content=prompt),
    ]

    result = await gateway.generate(
        db=db,
        user_id=user_id,
        messages=messages,
        provider=provider,
        model=model,
        temperature=0.2,
    )

    try:
        parsed = json.loads(result.content.strip())
    except Exception:
        parsed = {"summary": result.content, "key_highlights": []}

    return {
        "operation": "task_summary_generation",
        "result": parsed,
        "model_used": result.model,
        "provider_used": result.provider,
    }


ToolFunction = Callable[
    [AsyncSession, uuid.UUID, dict[str, Any], str | None, str | None],
    Awaitable[dict[str, Any]],
]

TOOL_REGISTRY: dict[str, ToolFunction] = {
    "text_categorization": execute_text_categorization,
    "information_extraction": execute_information_extraction,
    "response_drafting": execute_response_drafting,
    "task_summary_generation": execute_task_summary_generation,
}


def get_tool_handler(operation: str) -> ToolFunction | None:
    """Retrieve the registered execution handler for an internal or external operation."""
    op_clean = operation.strip().lower()
    if op_clean in TOOL_REGISTRY:
        return TOOL_REGISTRY[op_clean]

    from flowpilot.integrations.registry import EXTERNAL_CAPABILITIES

    if op_clean in EXTERNAL_CAPABILITIES:
        return EXTERNAL_CAPABILITIES[op_clean].handler

    return None
