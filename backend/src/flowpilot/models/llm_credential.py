"""LLM credential database model for Bring Your Own API Key (BYOK)."""

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from flowpilot.db.base import Base

if TYPE_CHECKING:
    from flowpilot.models.llm_preference import LLMPreference
    from flowpilot.models.llm_usage import LLMUsage
    from flowpilot.models.user import User


def get_utc_now() -> datetime:
    """Return current timezone-aware UTC datetime."""
    return datetime.now(UTC)


class LLMCredential(Base):
    """Encrypted LLM provider credentials configured by individual platform users."""

    __tablename__ = "llm_credentials"

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
    )
    encrypted_api_key: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    key_fingerprint: Mapped[str] = mapped_column(
        String(100),
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
    last_validated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Relationships
    user: Mapped["User"] = relationship(
        "User",
        back_populates="llm_credentials",
    )
    preference: Mapped["LLMPreference | None"] = relationship(
        "LLMPreference",
        back_populates="credential",
        cascade="all, delete-orphan",
        uselist=False,
    )
    usage_records: Mapped[list["LLMUsage"]] = relationship(
        "LLMUsage",
        back_populates="credential",
    )

    __table_args__ = (
        UniqueConstraint("user_id", "provider", name="uq_llm_credentials_user_provider"),
    )

    def __repr__(self) -> str:
        return (
            f"<LLMCredential(id={self.id}, user_id={self.user_id}, "
            f"provider='{self.provider}', fingerprint='{self.key_fingerprint}')>"
        )
