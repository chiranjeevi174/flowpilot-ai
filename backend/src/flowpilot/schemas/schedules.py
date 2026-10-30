"""Pydantic v2 schemas for workflow scheduling requests and responses."""

import uuid
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator

from flowpilot.models.scheduled_workflow import ScheduleType


class ScheduledWorkflowCreateRequest(BaseModel):
    """Payload to create a new scheduled or recurring workflow automation."""

    name: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description="User-friendly name for this scheduled automation.",
    )
    workflow_request: str = Field(
        ...,
        min_length=1,
        max_length=10000,
        description="Natural language instruction to be executed by the multi-agent system.",
    )
    schedule_type: str = Field(
        ...,
        description="Recurrence type: 'one_time', 'daily', or 'weekly'.",
    )
    timezone: str = Field(
        default="UTC",
        description="IANA timezone identifier (e.g. 'UTC', 'America/New_York', 'Asia/Kolkata').",
    )
    schedule_configuration: dict[str, Any] = Field(
        default_factory=dict,
        description="Configuration for schedule: e.g. {'time': '09:00'} or days_of_week list.",
    )

    @field_validator("schedule_type")
    @classmethod
    def validate_type(cls, v: str) -> str:
        val = v.strip().lower()
        if val not in ScheduleType.ALL:
            raise ValueError(f"schedule_type must be one of: {sorted(ScheduleType.ALL)}")
        return val

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: str) -> str:
        val = v.strip()
        try:
            ZoneInfo(val)
        except (ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError(f"Invalid IANA timezone identifier: '{val}'") from exc
        return val


class ScheduledWorkflowUpdateRequest(BaseModel):
    """Payload to partially update a scheduled workflow."""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    workflow_request: str | None = Field(default=None, min_length=1, max_length=10000)
    schedule_type: str | None = Field(default=None)
    timezone: str | None = Field(default=None)
    schedule_configuration: dict[str, Any] | None = Field(default=None)
    is_active: bool | None = Field(default=None)

    @field_validator("schedule_type")
    @classmethod
    def validate_type(cls, v: str | None) -> str | None:
        if v is None:
            return None
        val = v.strip().lower()
        if val not in ScheduleType.ALL:
            raise ValueError(f"schedule_type must be one of: {sorted(ScheduleType.ALL)}")
        return val

    @field_validator("timezone")
    @classmethod
    def validate_tz(cls, v: str | None) -> str | None:
        if v is None:
            return None
        val = v.strip()
        try:
            ZoneInfo(val)
        except (ZoneInfoNotFoundError, KeyError) as exc:
            raise ValueError(f"Invalid IANA timezone identifier: '{val}'") from exc
        return val


class ScheduledWorkflowResponse(BaseModel):
    """Full detail view of a scheduled workflow."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    user_id: uuid.UUID
    name: str
    workflow_request: str
    schedule_type: str
    timezone: str
    schedule_configuration: dict[str, Any]
    next_run_at: datetime
    last_run_at: datetime | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime
    latest_run_id: uuid.UUID | None = None
    latest_run_status: str | None = None


class ScheduledWorkflowListResponse(BaseModel):
    """List of user-owned scheduled workflows."""

    items: list[ScheduledWorkflowResponse]
    total: int
