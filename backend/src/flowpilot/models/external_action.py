"""ExternalAction database model tracking real-world side effects and idempotency safeguards."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.agent_run import AgentRun
    from flowpilot.models.integration_connection import IntegrationConnection
    from flowpilot.models.user import User


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ExternalActionStatus:
    """Lifecycle states for external real-world actions."""

    PENDING = "pending"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    INDETERMINATE = "indeterminate"

    ALL = {PENDING, EXECUTING, SUCCEEDED, FAILED, INDETERMINATE}


class ExternalAction(Base):
    """Audit and idempotency record of an external API operation executed on behalf of a user."""

    __tablename__ = "external_actions"
    __table_args__ = (Index("ix_external_actions_user_operation", "user_id", "operation"),)

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
    run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("agent_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    operation: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Operation name, e.g. 'gmail_send_email', 'slack_send_message'",
    )
    parameter_digest: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="SHA-256 digest of normalized parameters for approval integrity validation",
    )
    idempotency_key: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        unique=True,
        index=True,
        comment="Unique idempotency token preventing duplicate external execution",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ExternalActionStatus.PENDING,
        index=True,
    )
    approval_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Reference to user approval decision if sensitive operation",
    )
    provider_action_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="External provider entity ID, e.g. message_id or row range",
    )
    provider_response: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Sanitized external response metadata without secrets",
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
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship("User", back_populates="external_actions")
    run: Mapped["AgentRun | None"] = relationship("AgentRun")
    connection: Mapped["IntegrationConnection | None"] = relationship(
        "IntegrationConnection", back_populates="external_actions"
    )

    def __repr__(self) -> str:
        return (
            f"<ExternalAction(id={self.id}, user_id={self.user_id}, "
            f"operation='{self.operation}', status='{self.status}', "
            f"idempotency_key='{self.idempotency_key}')>"
        )
