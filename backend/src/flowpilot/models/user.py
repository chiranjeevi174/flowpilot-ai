"""User database model."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.agent_run import AgentRun
    from flowpilot.models.external_action import ExternalAction
    from flowpilot.models.integration_connection import IntegrationConnection
    from flowpilot.models.llm_credential import LLMCredential
    from flowpilot.models.llm_preference import LLMPreference
    from flowpilot.models.llm_usage import LLMUsage
    from flowpilot.models.notification import Notification
    from flowpilot.models.password_reset_token import PasswordResetToken
    from flowpilot.models.refresh_token import RefreshToken
    from flowpilot.models.scheduled_workflow import ScheduledWorkflow


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class User(Base):
    """User account entity representing a registered platform user."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    full_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
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

    # Relationships
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        "RefreshToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    password_reset_tokens: Mapped[list["PasswordResetToken"]] = relationship(
        "PasswordResetToken",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    llm_credentials: Mapped[list["LLMCredential"]] = relationship(
        "LLMCredential",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    llm_preference: Mapped["LLMPreference | None"] = relationship(
        "LLMPreference",
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False,
        passive_deletes=True,
    )
    llm_usage: Mapped[list["LLMUsage"]] = relationship(
        "LLMUsage",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    agent_runs: Mapped[list["AgentRun"]] = relationship(
        "AgentRun",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    scheduled_workflows: Mapped[list["ScheduledWorkflow"]] = relationship(
        "ScheduledWorkflow",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    integration_connections: Mapped[list["IntegrationConnection"]] = relationship(
        "IntegrationConnection",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    external_actions: Mapped[list["ExternalAction"]] = relationship(
        "ExternalAction",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    notifications: Mapped[list["Notification"]] = relationship(
        "Notification",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Notification.created_at.desc()",
    )

    def __repr__(self) -> str:
        return f"<User(id={self.id}, email='{self.email}', is_active={self.is_active})>"
