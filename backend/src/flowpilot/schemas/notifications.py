"""Pydantic v2 schemas for in-app notifications requests and responses."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NotificationCreateRequest(BaseModel):
    """Payload to create or record an in-app notification."""

    type: str = Field(
        ...,
        max_length=50,
        description="Type: schedule_countdown, workflow_started, approval_required, system.",
    )
    category: str = Field(
        default="general",
        max_length=50,
        description="Category: schedule, approval, system, general.",
    )
    title: str = Field(..., max_length=255, description="Brief notification title.")
    message: str = Field(..., description="Notification body content.")
    link_url: str | None = Field(
        default=None,
        max_length=255,
        description="Direct target URL for action click.",
    )
    meta_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Contextual payload (schedule_id, run_id, etc.).",
    )
    dedup_key: str = Field(
        ...,
        max_length=255,
        description="Unique key for deduplication within user scope.",
    )


class NotificationResponse(BaseModel):
    """Detailed view of an in-app notification."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    type: str
    category: str
    title: str
    message: str
    link_url: str | None = None
    meta_data: dict[str, Any]
    dedup_key: str
    is_read: bool
    is_dismissed: bool
    created_at: datetime
    updated_at: datetime


class NotificationListResponse(BaseModel):
    """List response of user notifications with unread counter."""

    items: list[NotificationResponse]
    unread_count: int
    total: int
