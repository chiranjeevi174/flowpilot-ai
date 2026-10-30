"""Groq LLM provider adapter using official AsyncGroq SDK."""

import asyncio
from typing import Any

import groq
from groq import AsyncGroq

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

logger = get_logger("llm.providers.groq")


class GroqProvider(BaseLLMProvider):
    """Provider implementation for Groq LPU inference models."""

    @property
    def provider_name(self) -> str:
        return ProviderType.GROQ.value

    def _get_client(self, api_key: str) -> AsyncGroq:
        """Instantiate official AsyncGroq client with user-supplied API key."""
        return AsyncGroq(api_key=api_key.strip())

    def _map_error(self, exc: Exception) -> LLMProviderError:
        """Map Groq SDK exceptions to standardized LLMProviderError hierarchy."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError, groq.APITimeoutError)):
            return ProviderTimeoutError("Groq request timed out.")

        if isinstance(exc, groq.AuthenticationError):
            return ProviderAuthenticationError("Invalid Groq API key or unauthorized access.")

        if isinstance(exc, groq.PermissionDeniedError):
            return ProviderAuthenticationError(
                f"Groq permission denied: {getattr(exc, 'message', str(exc))}"
            )

        if isinstance(exc, groq.RateLimitError):
            msg = str(exc).lower()
            if any(term in msg for term in ("quota", "balance", "insufficient", "exhausted")):
                return ProviderQuotaExceededError("Groq quota or account balance exhausted.")
            return ProviderRateLimitError(
                f"Groq rate limit exceeded: {getattr(exc, 'message', str(exc))}"
            )

        if isinstance(exc, groq.NotFoundError):
            return ModelNotFoundError(
                f"Requested Groq model not found: {getattr(exc, 'message', str(exc))}"
            )

        if isinstance(exc, (groq.APIConnectionError, groq.InternalServerError)):
            return ProviderUnavailableError(f"Groq service unavailable: {exc}")

        if isinstance(exc, groq.APIError):
            code = getattr(exc, "code", "unknown")
            message = getattr(exc, "message", str(exc))
            return LLMProviderError(f"Groq API error ({code}): {message}")

        return LLMProviderError(f"Groq provider error: {exc!s}")

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
        """Discover available text generation models for this Groq API key."""
        client = self._get_client(api_key)
        discovered: list[ModelInfo] = []

        try:
            models_page = await client.models.list()
            raw_models = getattr(models_page, "data", models_page)

            # Known non-text / audio / guard models to filter out
            excluded_patterns = (
                "whisper",
                "distil-whisper",
                "tts",
                "embedding",
                "guard",
                "safeguard",
                "moderation",
                "clip",
                "vision-preview",
            )

            # Known context window sizes for Groq model families
            for m in raw_models:
                model_id = m.id.lower()

                # Filter: Exclude non-text, speech-to-text, and moderation models
                if any(pat in model_id for pat in excluded_patterns):
                    continue

                # Filter: Include known text generation model families
                if any(
                    fam in model_id
                    for fam in (
                        "llama",
                        "mixtral",
                        "gemma",
                        "deepseek",
                        "qwen",
                    )
                ):
                    context = 128000
                    if "mixtral" in model_id:
                        context = 32768
                    elif "8192" in model_id or "gemma" in model_id:
                        context = 8192
                    elif any(
                        fam in model_id for fam in ("llama-3.3", "llama-3.1", "deepseek", "qwen")
                    ):
                        context = 128000

                    # Clean model name for display
                    display_name = m.id
                    if hasattr(m, "owned_by") and m.owned_by:
                        desc = f"Groq {display_name} model (by {m.owned_by})"
                    else:
                        desc = f"Groq {display_name} model"

                    discovered.append(
                        ModelInfo(
                            id=m.id,
                            name=display_name,
                            provider=self.provider_name,
                            description=desc,
                            context_window=context,
                            supports_streaming=True,
                            supports_tools=True,
                        )
                    )
        except Exception as exc:
            mapped = self._map_error(exc)
            logger.error("Dynamic Groq model discovery failed: %s", mapped)
            raise mapped from exc

        return discovered

    async def generate(
        self,
        api_key: str,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        """Execute text generation through Groq chat completions."""
        client = self._get_client(api_key)

        formatted_messages: list[dict[str, Any]] = [
            {"role": msg.role, "content": msg.content} for msg in request.messages
        ]

        kwargs: dict[str, Any] = {
            "model": request.model,
            "messages": formatted_messages,
        }

        if request.temperature is not None:
            kwargs["temperature"] = request.temperature
        if request.max_tokens is not None:
            kwargs["max_tokens"] = request.max_tokens

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
