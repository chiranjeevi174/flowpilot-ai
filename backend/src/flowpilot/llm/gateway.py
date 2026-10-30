"""Unified LLM Invocation Gateway with retry, timeout, and usage tracking."""

import asyncio
import time
import uuid
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.encryption import decrypt_api_key
from flowpilot.core.logging import get_logger
from flowpilot.llm.pricing import calculate_cost
from flowpilot.llm.providers import (
    LLMGenerationRequest,
    LLMMessage,
    LLMProviderError,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    TokenUsage,
    get_provider,
)
from flowpilot.models.llm_credential import LLMCredential
from flowpilot.models.llm_preference import LLMPreference
from flowpilot.models.llm_usage import LLMUsage

logger = get_logger("llm.gateway")


class GatewayError(Exception):
    """Base exception for gateway failures."""


class NoPreferenceConfiguredError(GatewayError):
    """Raised when no default provider/model preference is set for the user."""


class CredentialNotFoundError(GatewayError):
    """Raised when the user has not connected credentials for the required provider."""


class GatewayGenerationResult(BaseModel):
    """Normalized output from the Unified LLM Gateway."""

    model_config = ConfigDict(extra="ignore")

    content: str
    provider: str
    model: str
    usage: TokenUsage | None = None
    estimated_cost: Decimal | None = None
    currency: str | None = None
    latency_ms: int = Field(ge=0)
    raw_response: dict[str, Any] | None = None

    @property
    def input_tokens(self) -> int:
        return self.usage.prompt_tokens if self.usage else 0

    @property
    def output_tokens(self) -> int:
        return self.usage.completion_tokens if self.usage else 0

    @property
    def total_tokens(self) -> int:
        return self.usage.total_tokens if self.usage else 0

    @property
    def estimated_cost_usd(self) -> Decimal | None:
        return self.estimated_cost


class LLMGateway:
    """Unified asynchronous gateway orchestrating multi-provider LLM invocations."""

    async def generate(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        messages: list[LLMMessage],
        model: str | None = None,
        provider: str | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> GatewayGenerationResult:
        """Execute text generation through the user's connected BYOK credentials.

        Args:
            db: Active AsyncSession.
            user_id: Authenticated user's unique identifier.
            messages: List of chat messages.
            model: Optional model override. Defaults to user's saved preference.
            provider: Optional provider override. Defaults to user's saved preference.
            temperature: Sampling temperature (0.0 to 2.0).
            max_tokens: Optional token generation limit.

        Returns:
            Normalized GatewayGenerationResult.
        """
        settings = get_settings()

        # 1. Resolve Provider and Model
        target_provider = provider
        target_model = model

        if not target_provider or not target_model:
            pref_result = await db.execute(
                select(LLMPreference).where(LLMPreference.user_id == user_id)
            )
            pref = pref_result.scalar_one_or_none()
            if pref is None:
                raise NoPreferenceConfiguredError(
                    "No default LLM provider or model configured. Please set your preference "
                    "or specify 'provider' and 'model' in your request."
                )
            target_provider = target_provider or pref.provider
            target_model = target_model or pref.model_id

        # 2. Retrieve User Credential
        cred_result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider == target_provider,
            )
        )
        cred = cred_result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(
                f"No API key connected for provider '{target_provider}'. "
                f"Please add your {target_provider.title()} credentials first."
            )

        # 3. Decrypt API Key
        plain_api_key = decrypt_api_key(cred.encrypted_api_key)

        # 4. Resolve Provider Adapter
        provider_adapter = get_provider(target_provider)
        request_payload = LLMGenerationRequest(
            messages=messages,
            model=target_model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        # 5. Execute with Timeout & Transient Backoff Retries
        start_time = time.perf_counter()
        retries = 0
        max_retries = settings.LLM_MAX_RETRIES
        backoff = settings.LLM_RETRY_BACKOFF_FACTOR
        last_exception: Exception | None = None
        response = None

        while retries <= max_retries:
            try:
                response = await asyncio.wait_for(
                    provider_adapter.generate(plain_api_key, request_payload),
                    timeout=settings.LLM_REQUEST_TIMEOUT_SECONDS,
                )
                break
            except (ProviderRateLimitError, ProviderUnavailableError, ProviderTimeoutError) as exc:
                last_exception = exc
                retries += 1
                if retries > max_retries:
                    break
                sleep_duration = backoff**retries
                logger.warning(
                    "Transient error from %s (%s). Retrying in %.2fs (attempt %d/%d)",
                    target_provider,
                    exc,
                    sleep_duration,
                    retries,
                    max_retries,
                )
                await asyncio.sleep(sleep_duration)
            except (ProviderAuthenticationError, Exception) as exc:
                # Non-transient errors: do not retry
                last_exception = exc
                break

        latency_ms = int((time.perf_counter() - start_time) * 1000)

        # 6. Handle Outcome & Persist Usage Records
        if response is None:
            # Persist failure record
            usage_rec = LLMUsage(
                user_id=user_id,
                credential_id=cred.id,
                provider=target_provider,
                model_id=target_model,
                input_tokens=0,
                output_tokens=0,
                total_tokens=0,
                estimated_cost=None,
                currency="USD",
                status=f"error: {type(last_exception).__name__}",
                latency_ms=latency_ms,
            )
            db.add(usage_rec)
            await db.flush()

            if isinstance(last_exception, LLMProviderError):
                raise last_exception
            raise GatewayError(
                f"LLM gateway generation failed: {last_exception}"
            ) from last_exception

        # Calculate estimated cost
        input_tokens = response.usage.prompt_tokens if response.usage else 0
        output_tokens = response.usage.completion_tokens if response.usage else 0
        total_tokens = response.usage.total_tokens if response.usage else 0

        cost, currency = calculate_cost(
            provider=target_provider,
            model=target_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

        # Persist success record
        usage_rec = LLMUsage(
            user_id=user_id,
            credential_id=cred.id,
            provider=target_provider,
            model_id=target_model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
            estimated_cost=cost,
            currency=currency,
            status="success",
            latency_ms=latency_ms,
        )
        db.add(usage_rec)
        await db.flush()

        return GatewayGenerationResult(
            content=response.content,
            provider=target_provider,
            model=target_model,
            usage=response.usage,
            estimated_cost=cost,
            currency=currency,
            latency_ms=latency_ms,
            raw_response=response.raw_response,
        )


# Global gateway instance
gateway = LLMGateway()
