"""IntegrationEvent database model tracking inbound webhooks and preventing event replay."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.integration_connection import IntegrationConnection


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class IntegrationEventStatus:
    """Processing statuses for inbound integration events."""

    RECEIVED = "received"
    PROCESSING = "processing"
    PROCESSED = "processed"
    IGNORED = "ignored"
    FAILED = "failed"

    ALL = {RECEIVED, PROCESSING, PROCESSED, IGNORED, FAILED}


class IntegrationEvent(Base):
    """Audit and deduplication record for inbound webhooks and integration event deliveries."""

    __tablename__ = "integration_events"
    __table_args__ = (
        UniqueConstraint(
            "provider",
            "external_event_id",
            name="uq_integration_events_provider_external_id",
        ),
        Index("ix_integration_events_provider_type", "provider", "event_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
        comment="Provider identifier, e.g. 'slack'",
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("integration_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    external_event_id: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
        comment="Unique identifier issued by external provider to prevent duplicate replay",
    )
    event_type: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
        comment="Event classification, e.g. 'app_mention', 'message'",
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default=IntegrationEventStatus.RECEIVED,
        index=True,
    )
    payload_summary: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        comment="Sanitized event metadata, excluding raw sensitive body content",
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    connection: Mapped["IntegrationConnection | None"] = relationship("IntegrationConnection")

    def __repr__(self) -> str:
        return (
            f"<IntegrationEvent(id={self.id}, provider='{self.provider}', "
            f"external_id='{self.external_event_id}', type='{self.event_type}', "
            f"status='{self.status}')>"
        )
