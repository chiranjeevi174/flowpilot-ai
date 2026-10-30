"""Schemas for LLM credentials, preferences, model discovery, and usage."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from flowpilot.llm.providers.base import LLMMessage, TokenUsage


class ProviderResponse(BaseModel):
    """Supported provider catalog item."""

    model_config = ConfigDict(extra="ignore")

    id: str
    name: str
    description: str


class CredentialCreateRequest(BaseModel):
    """Payload to connect a new LLM provider with a personal API key."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(description="Target provider name ('gemini', 'openai', or 'groq')")
    api_key: str = Field(min_length=10, max_length=512, description="User's secret API key")


class CredentialUpdateRequest(BaseModel):
    """Payload to replace an existing provider's API key."""

    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=10, max_length=512, description="New secret API key")


class CredentialResponse(BaseModel):
    """Safe public representation of a connected LLM credential (API key never exposed)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    key_fingerprint: str
    created_at: datetime
    updated_at: datetime
    last_validated_at: datetime | None = None


class ConnectionTestResponse(BaseModel):
    """Result of an on-demand provider connection test."""

    model_config = ConfigDict(extra="ignore")

    provider: str
    status: str
    message: str
    tested_at: datetime


class PreferenceRequest(BaseModel):
    """Request to update the user's default LLM provider and model."""

    model_config = ConfigDict(extra="forbid")

    credential_id: uuid.UUID = Field(description="ID of the user's connected credential")
    model_id: str = Field(min_length=1, max_length=100, description="Selected model identifier")


class PreferenceResponse(BaseModel):
    """User's active default LLM configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    credential_id: uuid.UUID
    provider: str
    model_id: str
    updated_at: datetime


class GenerationRequest(BaseModel):
    """Request to generate text through the Unified LLM Gateway."""

    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage] = Field(min_length=1, description="Chat messages sequence")
    model: str | None = Field(default=None, description="Optional model override")
    provider: str | None = Field(default=None, description="Optional provider override")
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class GenerationResponse(BaseModel):
    """Unified text generation response with metrics."""

    model_config = ConfigDict(extra="ignore")

    content: str
    model: str
    provider: str
    usage: TokenUsage | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None
    latency_ms: int


class UsageRecordResponse(BaseModel):
    """Single historical LLM usage entry."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    model_id: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost: Decimal | None = None
    currency: str | None = None
    status: str
    latency_ms: int
    created_at: datetime
