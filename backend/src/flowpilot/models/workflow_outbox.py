"""WorkflowOutbox model providing transactional outbox persistence for durable workflow dispatch."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.agent_run import AgentRun


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class OutboxStatus:
    """Status lifecycle for transactional outbox dispatch records."""

    PENDING = "pending"
    DISPATCHED = "dispatched"
    FAILED = "failed"

    ALL = {PENDING, DISPATCHED, FAILED}


class WorkflowOutbox(Base):
    """Transactional outbox record ensuring guaranteed, recoverable task dispatch to Celery."""

    __tablename__ = "workflow_outbox"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_type: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=OutboxStatus.PENDING,
        nullable=False,
        index=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    last_error: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
        index=True,
    )
    dispatched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    agent_run: Mapped["AgentRun"] = relationship(
        "AgentRun",
        back_populates="outbox_entries",
    )

    def __repr__(self) -> str:
        return (
            f"<WorkflowOutbox(id={self.id}, task_type='{self.task_type}', status='{self.status}')>"
        )
