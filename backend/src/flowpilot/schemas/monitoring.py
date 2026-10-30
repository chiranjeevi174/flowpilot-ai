"""Pydantic schemas for worker health and operational monitoring diagnostics."""

from datetime import datetime

from pydantic import BaseModel, Field


class MonitoringHealthResponse(BaseModel):
    """Operational metrics and diagnostic readiness report."""

    database_connected: bool = Field(..., description="PostgreSQL connection readiness status.")
    redis_connected: bool = Field(..., description="Redis message broker connection status.")
    celery_queue_depth: int = Field(
        default=0, description="Number of tasks currently enqueued in the primary Celery queue."
    )
    runs_by_status: dict[str, int] = Field(
        default_factory=dict, description="Distribution of agent runs by lifecycle state."
    )
    total_runs: int = Field(default=0, description="Total number of workflow runs processed.")
    active_schedules: int = Field(
        default=0, description="Total number of currently active workflow schedules."
    )
    average_duration_seconds: float | None = Field(
        default=None, description="Average execution runtime in seconds for completed workflows."
    )
    failed_outbox_count: int = Field(
        default=0,
        description="Permanently failed outbox delivery records requiring admin attention.",
    )
    pending_outbox_count: int = Field(
        default=0,
        description="Number of pending transactional outbox records awaiting worker dispatch.",
    )
    provider_failure_rates: dict[str, float] = Field(
        default_factory=dict,
        description="Calculated error rates per LLM provider (0.0 to 1.0).",
    )
    timestamp: datetime = Field(..., description="UTC timestamp of the monitoring check.")
