"""LLM providers package and provider registry."""

from flowpilot.llm.providers.base import (
    BaseLLMProvider,
    LLMGenerationRequest,
    LLMGenerationResponse,
    LLMMessage,
    LLMProviderError,
    ModelInfo,
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderType,
    ProviderUnavailableError,
    TokenUsage,
    UnsupportedModelError,
)
from flowpilot.llm.providers.gemini import GeminiProvider
from flowpilot.llm.providers.groq import GroqProvider
from flowpilot.llm.providers.openai import OpenAIProvider


class UnsupportedProviderError(LLMProviderError):
    """Raised when an unknown or unsupported provider is requested."""


# Singleton provider instances
_PROVIDERS: dict[str, BaseLLMProvider] = {
    ProviderType.GEMINI.value: GeminiProvider(),
    ProviderType.OPENAI.value: OpenAIProvider(),
    ProviderType.GROQ.value: GroqProvider(),
}


def get_provider(provider_name: str) -> BaseLLMProvider:
    """Retrieve provider implementation by name ('gemini', 'openai', 'groq')."""
    normalized = provider_name.strip().lower()
    provider = _PROVIDERS.get(normalized)
    if provider is None:
        supported = ", ".join(f"'{p}'" for p in _PROVIDERS)
        msg = f"Unsupported provider '{provider_name}'. Supported providers: {supported}."
        raise UnsupportedProviderError(msg)
    return provider


def list_supported_providers() -> list[dict[str, str]]:
    """Return catalog of supported LLM providers."""
    return [
        {
            "id": ProviderType.GEMINI.value,
            "name": "Google Gemini",
            "description": "Google Gemini multimodal and reasoning models",
        },
        {
            "id": ProviderType.OPENAI.value,
            "name": "OpenAI",
            "description": "OpenAI GPT-4o, o1, and ChatGPT models",
        },
        {
            "id": ProviderType.GROQ.value,
            "name": "Groq",
            "description": "Ultra-low latency Llama 3.3, Mixtral, and DeepSeek inference via LPU",
        },
    ]


__all__ = [
    "BaseLLMProvider",
    "GeminiProvider",
    "GroqProvider",
    "LLMGenerationRequest",
    "LLMGenerationResponse",
    "LLMMessage",
    "LLMProviderError",
    "ModelInfo",
    "ModelNotFoundError",
    "OpenAIProvider",
    "ProviderAuthenticationError",
    "ProviderQuotaExceededError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderType",
    "ProviderUnavailableError",
    "TokenUsage",
    "UnsupportedModelError",
    "UnsupportedProviderError",
    "get_provider",
    "list_supported_providers",
]
