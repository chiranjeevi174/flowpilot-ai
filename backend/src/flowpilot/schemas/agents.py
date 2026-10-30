"""Pydantic schemas for agent orchestration, plan validation, and API interactions."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# ==============================================================================
# Agent Internal Schemas (Validation & Structured Outputs)
# ==============================================================================


class IntentAnalysisResult(BaseModel):
    """Structured output produced by the Intent Analysis Agent."""

    model_config = ConfigDict(extra="ignore")

    intent: str = Field(
        ...,
        description="High-level category of intent (e.g., customer_support, extraction).",
    )
    action: str = Field(
        ...,
        description="Specific action to execute (e.g., prepare_response, extract_data).",
    )
    requires_clarification: bool = Field(
        default=False,
        description="Whether the request is ambiguous or lacks necessary details.",
    )
    is_actionable: bool = Field(
        default=True,
        description="Whether the request can be enacted by the platform's supported tools.",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Extracted key-value parameters relevant to the request.",
    )
    clarification_message: str | None = Field(
        default=None,
        description="Explanation when clarification is needed.",
    )


class PlanStep(BaseModel):
    """An individual execution step in a validated plan."""

    model_config = ConfigDict(extra="ignore")

    step_id: str = Field(
        ...,
        description="Unique step identifier within the plan (e.g., 'step_1').",
    )
    operation: str = Field(
        ...,
        description="Allowed operation name (must be in SUPPORTED_CAPABILITIES).",
    )
    parameters: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution arguments for the operation.",
    )
    required_capability: str = Field(
        ...,
        description="Capability category needed for the operation.",
    )
    approval_required: bool = Field(
        default=False,
        description="Whether this step requires human approval before execution.",
    )
    expected_outcome: str = Field(
        ...,
        description="Description of the expected result produced by this step.",
    )


class ExecutionPlan(BaseModel):
    """Full execution plan produced by the Planning Agent."""

    model_config = ConfigDict(extra="ignore")

    steps: list[PlanStep] = Field(
        default_factory=list,
        description="Ordered sequence of operations to perform.",
    )
    unsupported_capability: bool = Field(
        default=False,
        description="Flag indicating the request demands unavailable external integrations.",
    )
    unsupported_reason: str | None = Field(
        default=None,
        description="Explanation of why the capability is unsupported.",
    )


class VerificationResult(BaseModel):
    """Structured output produced by the Verification Agent."""

    model_config = ConfigDict(extra="ignore")

    passed: bool = Field(
        ...,
        description="Whether all execution steps completed successfully and satisfied the request.",
    )
    critique: str = Field(
        ...,
        description="Evaluation reasoning or details regarding missing outputs.",
    )
    missing_outputs: list[str] = Field(
        default_factory=list,
        description="List of required deliverables not found in execution outputs.",
    )
    needs_correction: bool = Field(
        default=False,
        description="Whether a bounded correction cycle should be triggered.",
    )


# ==============================================================================
# API Request & Response Schemas
# ==============================================================================


class AgentRunCreateRequest(BaseModel):
    """Payload to initiate a new multi-agent workflow execution."""

    request: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Natural language instruction for the multi-agent system.",
    )
    provider: str | None = Field(
        default=None,
        description="Optional LLM provider override (e.g., 'gemini', 'openai').",
    )
    model: str | None = Field(
        default=None,
        description="Optional model override (e.g., 'gemini-2.5-flash', 'gpt-4o').",
    )


class ApprovalDecisionRequest(BaseModel):
    """Payload to approve or reject a pending execution step."""

    comment: str | None = Field(
        default=None,
        max_length=1000,
        description="Optional human reviewer comment explaining the decision.",
    )


class AgentEventResponse(BaseModel):
    """Telemetry event recorded during agent execution."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    run_id: uuid.UUID
    agent_name: str
    event_type: str
    event_payload: dict[str, Any]
    timestamp: datetime


class AgentRunResponse(BaseModel):
    """Full view of an agent execution run."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    thread_id: str
    original_request: str
    status: str
    current_step: int
    detected_intent: dict[str, Any] | None = None
    execution_plan: list[dict[str, Any]] | None = None
    final_result: Any | None = None
    error_message: str | None = None
    location: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AgentRunListResponse(BaseModel):
    """Paginated list of user agent runs."""

    items: list[AgentRunResponse]
    total: int
    limit: int
    offset: int
