"""IntegrationConnection model storing encrypted OAuth tokens and external connection state."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.external_action import ExternalAction
    from flowpilot.models.user import User


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class ConnectionStatus:
    """Allowed operational statuses for integration connections."""

    ACTIVE = "active"
    CONFIGURED = "configured"
    AUTHORIZATION_REQUIRED = "authorization_required"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"
    RESTRICTED = "restricted"

    ALL = {
        ACTIVE,
        CONFIGURED,
        AUTHORIZATION_REQUIRED,
        EXPIRED,
        REVOKED,
        ERROR,
        RESTRICTED,
    }


class IntegrationConnection(Base):
    """Database entity representing an authorized external service connection scoped to a user."""

    __tablename__ = "integration_connections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "provider",
            "external_account_id",
            name="uq_integration_connection_user_provider_account",
        ),
        Index("ix_integration_connections_user_provider", "user_id", "provider"),
        Index(
            "ix_integration_connections_user_provider_default", "user_id", "provider", "is_default"
        ),
    )

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
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Provider identifier, e.g. 'google' or 'slack'",
    )
    service: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        index=True,
        comment="Specific capability/service, e.g. 'gmail', 'sheets', 'slack'",
    )
    external_account_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        index=True,
        comment="Provider-issued account ID (e.g., email or team/workspace ID)",
    )
    external_account_name: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Human-readable external identity (e.g. workspace name or user email)",
    )
    config_method: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="custom_credentials",
        comment="Connection method: 'oauth' or 'custom_credentials'",
    )
    client_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="Provider OAuth client_id or app_id entered by user",
    )
    encrypted_client_secret: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="MultiFernet encrypted OAuth client_secret or app_secret",
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
        comment="Whether this is the user's primary connection for this provider",
    )
    encrypted_access_token: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="MultiFernet encrypted OAuth 2.0 access token",
    )
    encrypted_refresh_token: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="MultiFernet encrypted OAuth 2.0 refresh token",
    )
    granted_scopes: Mapped[list[str]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        comment="Array of authorized OAuth permission scopes",
    )
    token_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
        comment="UTC timestamp when current access token expires",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=ConnectionStatus.ACTIVE,
        index=True,
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Non-sensitive provider metadata (e.g., bot_user_id, team_name)",
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
    user: Mapped["User"] = relationship("User", back_populates="integration_connections")
    external_actions: Mapped[list["ExternalAction"]] = relationship(
        "ExternalAction",
        back_populates="connection",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<IntegrationConnection(id={self.id}, user_id={self.user_id}, "
            f"provider='{self.provider}', account='{self.external_account_id}', "
            f"status='{self.status}')>"
        )
