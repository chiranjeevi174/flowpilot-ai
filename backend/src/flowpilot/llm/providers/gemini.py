"""Google Gemini LLM provider adapter using official google-genai SDK."""

import asyncio
from typing import Any

from google import genai
from google.genai import errors as genai_errors

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

logger = get_logger("llm.providers.gemini")

# Fallback known models if dynamic discovery is unavailable or offline
FALLBACK_GEMINI_MODELS = [
    ModelInfo(
        id="gemini-2.0-flash",
        name="Gemini 2.0 Flash",
        provider=ProviderType.GEMINI.value,
        description="Next-generation multimodal model with low latency and high quality.",
        context_window=1048576,
    ),
    ModelInfo(
        id="gemini-1.5-flash",
        name="Gemini 1.5 Flash",
        provider=ProviderType.GEMINI.value,
        description="Fast and cost-efficient model for general multimodal tasks.",
        context_window=1048576,
    ),
    ModelInfo(
        id="gemini-1.5-pro",
        name="Gemini 1.5 Pro",
        provider=ProviderType.GEMINI.value,
        description="Highly capable model designed for complex multi-step reasoning.",
        context_window=2097152,
    ),
]


class GeminiProvider(BaseLLMProvider):
    """Provider implementation for Google Gemini models via google-genai SDK."""

    @property
    def provider_name(self) -> str:
        return ProviderType.GEMINI.value

    def _get_client(self, api_key: str) -> genai.Client:
        """Instantiate Google GenAI Client with the provided API key."""
        return genai.Client(api_key=api_key.strip())

    def _map_error(self, exc: Exception) -> LLMProviderError:
        """Map SDK errors to standardized application LLMProviderError hierarchy."""
        if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
            return ProviderTimeoutError("Google Gemini request timed out.")

        if isinstance(exc, genai_errors.APIError):
            code = getattr(exc, "code", None)
            msg = getattr(exc, "message", str(exc))

            if code in (401, 403) or "API_KEY_INVALID" in msg or "PERMISSION_DENIED" in msg:
                return ProviderAuthenticationError("Invalid or unauthorized Google Gemini API key.")
            if code == 429 or "RESOURCE_EXHAUSTED" in msg:
                if "quota" in msg.lower():
                    return ProviderQuotaExceededError("Google Gemini quota or balance exhausted.")
                return ProviderRateLimitError("Google Gemini rate limit exceeded.")
            if code == 404 or "NOT_FOUND" in msg:
                return ModelNotFoundError(f"Requested Gemini model not found: {msg}")
            if code and code >= 500:
                return ProviderUnavailableError(f"Google Gemini service error ({code}): {msg}")

        return LLMProviderError(f"Google Gemini error: {exc!s}")

    async def validate_credentials(self, api_key: str) -> bool:
        """Validate API key via non-billable model listing check."""
        client = self._get_client(api_key)
        try:
            # Query models endpoint without generating tokens
            pager = await client.aio.models.list(config={"page_size": 1})
            # Trigger iterator evaluation
            async for _ in pager:
                break
            return True
        except Exception as exc:
            raise self._map_error(exc) from exc

    async def list_models(self, api_key: str) -> list[ModelInfo]:
        """Discover available text generation models for this API key."""
        client = self._get_client(api_key)
        discovered: list[ModelInfo] = []

        try:
            pager = await client.aio.models.list()
            raw_models = []
            if hasattr(pager, "__aiter__"):
                async for m in pager:
                    raw_models.append(m)
            elif hasattr(pager, "__iter__"):
                raw_models = list(pager)
            else:
                raw_models = [pager]

            for m in raw_models:
                model_id = getattr(m, "name", "")
                if model_id.startswith("models/"):
                    model_id = model_id[len("models/") :]

                # Filter: Exclude embeddings, audio-only, imagen, and non-gemini models
                lower_id = model_id.lower()
                if (
                    "embedding" in lower_id
                    or "imagen" in lower_id
                    or "veo" in lower_id
                    or "aqa" in lower_id
                    or "whisper" in lower_id
                ):
                    continue

                # Ensure it supports generateContent if actions are specified
                actions = getattr(m, "supported_actions", None)
                if actions and "generateContent" not in actions:
                    continue

                display_name = getattr(m, "display_name", None) or model_id
                desc = getattr(m, "description", None)
                context_window = getattr(m, "input_token_limit", None)

                discovered.append(
                    ModelInfo(
                        id=model_id,
                        name=display_name,
                        provider=self.provider_name,
                        description=desc,
                        context_window=context_window,
                        supports_streaming=True,
                        supports_tools=True,
                    )
                )
        except Exception as exc:
            mapped = self._map_error(exc)
            logger.error("Dynamic Gemini model discovery failed: %s", mapped)
            raise mapped from exc

        return discovered

    async def generate(
        self,
        api_key: str,
        request: LLMGenerationRequest,
    ) -> LLMGenerationResponse:
        """Execute text generation using Gemini models."""
        client = self._get_client(api_key)

        contents: list[dict[str, Any]] = []
        system_instruction: str | None = None

        for msg in request.messages:
            if msg.role == "system":
                system_instruction = msg.content
            elif msg.role in ("user", "human"):
                contents.append({"role": "user", "parts": [{"text": msg.content}]})
            elif msg.role in ("assistant", "model"):
                contents.append({"role": "model", "parts": [{"text": msg.content}]})

        config: dict[str, Any] = {}
        if system_instruction:
            config["system_instruction"] = system_instruction
        if request.temperature is not None:
            config["temperature"] = request.temperature
        if request.max_tokens is not None:
            config["max_output_tokens"] = request.max_tokens

        try:
            model_target = request.model
            if not model_target.startswith("models/") and "/" not in model_target:
                # google-genai accepts model name directly or with models/ prefix
                model_target = request.model

            response = await client.aio.models.generate_content(
                model=model_target,
                contents=contents,
                config=config if config else None,
            )
        except Exception as exc:
            raise self._map_error(exc) from exc

        # Extract text content
        output_text = getattr(response, "text", "") or ""

        # Extract usage metadata
        usage: TokenUsage | None = None
        usage_meta = getattr(response, "usage_metadata", None)
        if usage_meta:
            prompt_tokens = getattr(usage_meta, "prompt_token_count", 0) or 0
            candidate_tokens = getattr(usage_meta, "candidates_token_count", 0) or 0
            total_tokens = getattr(usage_meta, "total_token_count", 0) or (
                prompt_tokens + candidate_tokens
            )
            usage = TokenUsage(
                prompt_tokens=prompt_tokens,
                completion_tokens=candidate_tokens,
                total_tokens=total_tokens,
            )

        return LLMGenerationResponse(
            content=output_text,
            model=request.model,
            provider=self.provider_name,
            usage=usage,
        )
