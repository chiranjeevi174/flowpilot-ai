"""OpenAI LLM provider adapter using official AsyncOpenAI SDK."""

import asyncio
from typing import Any

import openai
from openai import AsyncOpenAI

from flowpilot.core.logging import get_logger
from flowpilot.llm.providers.base import (
    BaseLLMProvider,
    LLMGenerationRequest,
    LLMGenerationResponse,
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
)

logger = get_logger("llm.providers.openai")

FALLBACK_OPENAI_MODELS = [
    ModelInfo(
        id="gpt-4o",
        name="GPT-4o",
        provider=ProviderType.OPENAI.value,
        description="High-intelligence flagship model for complex, multi-step tasks.",
        context_window=128000,
    ),
    ModelInfo(
        id="gpt-4o-mini",
        name="GPT-4o Mini",
        provider=ProviderType.OPENAI.value,
        description="Affordable, fast intelligent model for lightweight tasks.",
        context_window=128000,
    ),
    ModelInfo(
        id="o1-mini",
        name="o1-mini",
        provider=ProviderType.OPENAI.value,
        description="Fast reasoning model optimized for coding, math, and logic.",
        context_window=128000,
    ),
]


class OpenAIProvider(BaseLLMProvider):
    """Provider implementation for OpenAI chat completion models."""

    @property
    def provider_name(self) -> str:
        return ProviderType.OPENAI.value

    def _get_client(self, api_key: str) -> AsyncOpenAI:
        """Instantiate official AsyncOpenAI client with user-supplied API key."""
        return AsyncOpenAI(api_key=api_key.strip())

    def _map_error(self, exc: Exception) -> LLMProviderError:
        """Map OpenAI SDK exceptions to standardized LLMProviderError hierarchy."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, openai.APITimeoutError)):
            return ProviderTimeoutError("OpenAI request timed out.")

        if isinstance(exc, openai.AuthenticationError):
            return ProviderAuthenticationError(
                "Invalid OpenAI API key or unauthorized organization."
            )

        if isinstance(exc, openai.PermissionDeniedError):
            return ProviderAuthenticationError(f"OpenAI permission denied: {exc.message}")

        if isinstance(exc, openai.RateLimitError):
            msg = str(exc).lower()
            if "quota" in msg or "insufficient" in msg:
                return ProviderQuotaExceededError("OpenAI quota or account balance exhausted.")
            return ProviderRateLimitError(f"OpenAI rate limit exceeded: {exc.message}")

        if isinstance(exc, openai.NotFoundError):
            return ModelNotFoundError(f"Requested OpenAI model not found: {exc.message}")

        if isinstance(exc, (openai.APIConnectionError, openai.InternalServerError)):
            return ProviderUnavailableError(f"OpenAI service unavailable: {exc}")

        if isinstance(exc, openai.APIError):
            return LLMProviderError(f"OpenAI API error ({exc.code}): {exc.message}")

        return LLMProviderError(f"OpenAI provider error: {exc!s}")

    async def validate_credentials(self, api_key: str) -> bool:
        """Validate API key via non-billable model listing check."""
        client = self._get_client(api_key)
        try:
            # Query models endpoint without generating tokens
            await client.models.list()
            return True
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        """Discover available text generation models for this OpenAI API key."""
        client = self._get_client(api_key)
        discovered: list[ModelInfo] = []

        try:
            models_page = await client.models.list()
            raw_models = getattr(models_page, "data", models_page)
            for m in raw_models:
                model_id = m.id.lower()

                # Filter: Exclude embeddings, audio, image, moderation, and legacy completions
                if any(
                    non_chat in model_id
                    for non_chat in (
                        "embedding",
                        "whisper",
                        "tts",
                        "dall-e",
                        "moderation",
                        "davinci",
                        "babbage",
                        "curie",
                        "ada",
                        "realtime",
                    )
                ):
                    continue

                # Filter: Include known text generation model families
                if any(prefix in model_id for prefix in ("gpt-", "o1", "o3", "chatgpt")):
                    # Context window estimation based on known model families
                    context = 128000
                    if "gpt-4o" in model_id or "o1" in model_id or "o3" in model_id:
                        context = 128000
                    elif "gpt-3.5-turbo-16k" in model_id:
                        context = 16384
                    elif "gpt-3.5-turbo" in model_id:
                        context = 4096

                    display_name = m.id
                    discovered.append(
                        ModelInfo(
                            id=m.id,
                            name=display_name,
                            provider=self.provider_name,
                            description=f"OpenAI {display_name} model",
                            context_window=context,
                            supports_streaming=True,
                            supports_tools=True,
                        )
                    )
        except Exception as exc:
            mapped = self._map_error(exc)
            logger.error("Dynamic OpenAI model discovery failed: %s", mapped)
            raise mapped from exc

        return discovered

    async def generate(
        self,
        api_key: str,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        """Execute text generation through OpenAI chat completions."""
        client = self._get_client(api_key)

        formatted_messages: list[dict[str, Any]] = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": formatted_messages,
        }

        # Reasoning models (like o1, o3) use max_completion_tokens
        # and do not accept custom temperature
        is_reasoning_model = request.model.startswith(("o1", "o3"))
        if not is_reasoning_model:
            if request.temperature is not None:
                kwargs["temperature"] = request.temperature
            if request.max_tokens is not None:
                kwargs["max_tokens"] = request.max_tokens
        else:
            if request.max_tokens is not None:
                kwargs["max_completion_tokens"] = request.max_tokens

        try:
            response = await client.chat.completions.create(**kwargs)
        except Exception as exc:
            raise self._map_error(exc) from exc

        # Extract text content
        output_text = ""
        if response.choices and response.choices[0].message:
            output_text = response.choices[0].message.content or ""

        # Extract token usage
        usage: TokenUsage | None = None
        if response.usage:
            usage = TokenUsage(
                prompt_tokens=response.usage.prompt_tokens or 0,
                completion_tokens=response.usage.completion_tokens or 0,
                total_tokens=response.usage.total_tokens or 0,
            )

        return LLMGenerationResponse(
            content=output_text,
            model=request.model,
            provider=self.provider_name,
            usage=usage,
        )
