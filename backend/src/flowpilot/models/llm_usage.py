"""LLM invocation usage and estimated cost tracking model."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.llm_credential import LLMCredential
    from flowpilot.models.user import User


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class LLMUsage(Base):
    """Tracks token consumption, latency, and estimated cost for all LLM gateway calls."""

    __tablename__ = "llm_usage"

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
    credential_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("llm_credentials.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    model_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    input_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    output_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    total_tokens: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    estimated_cost: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 6),
        nullable=True,
    )
    currency: Mapped[str | None] = mapped_column(
        String(10),
        default="USD",
        nullable=True,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default="success",
        nullable=False,
    )
    latency_ms: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=get_utc_now,
        nullable=False,
        index=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="llm_usage",
    )
    credential: Mapped["LLMCredential | None"] = relationship(
        "LLMCredential",
        back_populates="usage_records",
    )

    def __repr__(self) -> str:
        return (
            f"<LLMUsage(id={self.id}, user_id={self.user_id}, "
            f"provider='{self.provider}', model='{self.model_id}', "
            f"total_tokens={self.total_tokens}, cost={self.estimated_cost})>"
        )
