"""Base abstractions, data models, and exceptions for LLM providers."""

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderType(StrEnum):
    """Supported LLM providers."""

    GEMINI = "gemini"
    OPENAI = "openai"
    GROQ = "groq"


class LLMProviderError(Exception):
    """Base exception for all LLM provider operations."""


class ProviderAuthenticationError(LLMProviderError):
    """Raised when the provider rejects credentials (401/403)."""


class ProviderRateLimitError(LLMProviderError):
    """Raised when the provider rate limit is exceeded (429)."""


class ProviderQuotaExceededError(LLMProviderError):
    """Raised when provider balance or quota is exhausted."""


class ProviderUnavailableError(LLMProviderError):
    """Raised when the provider is temporarily unavailable or returning 5xx."""


class ProviderTimeoutError(LLMProviderError):
    """Raised when a request to the provider times out."""


class ModelNotFoundError(LLMProviderError):
    """Raised when the requested model is not found or inaccessible."""


UnsupportedModelError = ModelNotFoundError


class ModelInfo(BaseModel):
    """Metadata describing a supported text-generation model."""

    model_config = ConfigDict(extra="ignore")

    id: str = Field(description="Unique model identifier (e.g. 'gemini-1.5-flash', 'gpt-4o')")
    name: str = Field(description="Human-readable display name")
    provider: str = Field(description="Provider identifier ('gemini', 'openai', or 'groq')")
    description: str | None = Field(default=None, description="Model description")
    context_window: int | None = Field(default=None, description="Maximum context window tokens")
    supports_streaming: bool = Field(default=True)
    supports_tools: bool = Field(default=True)


class LLMMessage(BaseModel):
    """A single chat message in a conversation."""

    model_config = ConfigDict(extra="forbid")

    role: str = Field(description="Message role: 'system', 'user', or 'assistant'")
    content: str = Field(description="Message text content")


class TokenUsage(BaseModel):
    """Token consumption metrics for an LLM generation."""

    model_config = ConfigDict(extra="ignore")

    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)


class LLMGenerationRequest(BaseModel):
    """Normalized payload sent to an LLM provider."""

    model_config = ConfigDict(extra="forbid")

    messages: list[LLMMessage]
    model: str
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1)


class LLMGenerationResponse(BaseModel):
    """Standardized response returned from any LLM provider."""

    model_config = ConfigDict(extra="ignore")

    content: str
    model: str
    provider: str
    usage: TokenUsage | None = None
    raw_response: dict[str, Any] | None = None


class BaseLLMProvider(ABC):
    """Abstract base class defining the standard interface for LLM providers."""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Return the unique provider name (e.g. 'gemini', 'openai')."""

    @abstractmethod
    async def validate_credentials(self, api_key: str) -> bool:
        """Validate whether the provided API key is authentic without incurring costs.

        Returns:
            True if credentials are valid.

        Raises:
            ProviderAuthenticationError: If the key is invalid or rejected.
            LLMProviderError: If connection or server errors occur.
        """

    @abstractmethod
    async def list_models(self, api_key: str) -> list[ModelInfo]:
        """Dynamically list available text generation models for the provided key.

        Returns:
            List of supported ModelInfo objects.

        Raises:
            LLMProviderError: If model discovery fails.
        """

    @abstractmethod
    async def generate(
        self,
        api_key: str,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        """Execute text generation through the provider API.

        Returns:
            Normalized LLMGenerationResponse.

        Raises:
            LLMProviderError: On generation failure.
        """

    async def validate_model_support(self, api_key: str, model_id: str) -> bool:
        """Validate that a requested model is available and supported for this key.

        Returns:
            True if model is available.

        Raises:
            UnsupportedModelError: If the model is not found in the provider catalog.
        """
        models = await self.list_models(api_key)
        available_ids = {m.id.lower() for m in models}
        clean_target = model_id.strip().lower()
        if clean_target not in available_ids:
            msg = f"Model '{model_id}' is not supported or unavailable for {self.provider_name}."
            raise UnsupportedModelError(msg)
        return True
