"""AgentRun database model tracking multi-agent execution lifecycle."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.agent_event import AgentEvent
    from flowpilot.models.scheduled_workflow import ScheduledWorkflow
    from flowpilot.models.user import User
    from flowpilot.models.workflow_outbox import WorkflowOutbox


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class AgentRunStatus:
    """Allowed lifecycle states for an AgentRun."""

    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    AWAITING_APPROVAL = "awaiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"
    CANCELLED = "cancelled"

    ALL = {PENDING, QUEUED, RUNNING, AWAITING_APPROVAL, COMPLETED, FAILED, REJECTED, CANCELLED}
    TERMINAL = {COMPLETED, FAILED, REJECTED, CANCELLED}


class AgentRun(Base):
    """Database entity representing an orchestrated multi-agent execution run."""

    __tablename__ = "agent_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    thread_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    original_request: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=AgentRunStatus.PENDING,
        nullable=False,
        index=True,
    )
    current_step: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    detected_intent: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    execution_plan: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    final_result: Mapped[dict[str, Any] | str | None] = mapped_column(
        JSONB,
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        onupdate=get_utc_now,
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Background worker execution & scheduling metadata
    schedule_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("scheduled_workflows.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    locked_by: Mapped[str | None] = mapped_column(
        String(128),
        nullable=True,
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    cancellation_requested: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="agent_runs",
    )
    schedule: Mapped["ScheduledWorkflow | None"] = relationship(
        "ScheduledWorkflow",
        back_populates="agent_runs",
    )
    events: Mapped[list["AgentEvent"]] = relationship(
        "AgentEvent",
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="AgentEvent.timestamp",
    )
    outbox_entries: Mapped[list["WorkflowOutbox"]] = relationship(
        "WorkflowOutbox",
        back_populates="agent_run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<AgentRun(id={self.id}, user_id={self.user_id}, status='{self.status}')>"
