"""LangGraph typed execution state for FlowPilot multi-agent orchestration."""

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    """Serializable graph execution state scoped to an authenticated user and run."""

    # Run identification and ownership
    run_id: str
    user_id: str
    thread_id: str

    # Original request and optional LLM routing overrides
    original_request: str
    provider: str | None
    model: str | None

    # Intent analysis output
    detected_intent: dict[str, Any] | None

    # Validated execution plan
    execution_plan: list[dict[str, Any]] | None

    # Execution tracking and results
    current_step: int
    step_results: list[dict[str, Any]]
    executed_step_ids: list[str]  # Replay-safe step identifier set to prevent duplicate execution

    # Human-in-the-loop approval state
    approval_status: str  # "not_required" | "pending" | "approved" | "rejected"
    pending_approval_payload: dict[str, Any] | None

    # Verification and bounded correction
    verification_result: dict[str, Any] | None
    correction_attempts: int

    # Overall execution lifecycle status and outputs
    execution_status: (
        str  # "pending" | "running" | "awaiting_approval" | "completed" | "failed" | "rejected"
    )
    final_response: Any | None
    error_details: str | None
