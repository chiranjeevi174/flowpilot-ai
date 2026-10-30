"""Automated tests for Unified LLM Gateway, invocation routing, retry logic, and usage tracking."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.llm.gateway import (
    CredentialNotFoundError,
    NoPreferenceConfiguredError,
    gateway,
)
from flowpilot.llm.providers.base import (
    LLMGenerationResponse,
    LLMMessage,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    TokenUsage,
)
from flowpilot.models.llm_usage import LLMUsage
from flowpilot.models.user import User


@pytest.mark.asyncio
async def test_gateway_generate_with_default_preference(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify gateway resolves user default preference, executes generation, and tracks usage."""
    # 1. Setup user credential and preference
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

        cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="gemini",
            api_key="AIzaSyTestGeminiKey1234567890",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gemini-2.5-flash",
        )
        await db_session.commit()

    # 2. Mock provider generation response
    mock_gen_response = LLMGenerationResponse(
        content="Automated workflows empower business operations.",
        model="gemini-2.5-flash",
        provider="gemini",
        usage=TokenUsage(prompt_tokens=25, completion_tokens=10, total_tokens=35),
    )

    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.generate",
        new_callable=AsyncMock,
        return_value=mock_gen_response,
    ):
        messages = [
            LLMMessage(role="system", content="You are FlowPilot assistant."),
            LLMMessage(role="user", content="Briefly describe workflow automation."),
        ]
        result = await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=messages,
        )

    # 3. Assert normalized result
    assert result.content == "Automated workflows empower business operations."
    assert result.provider == "gemini"
    assert result.model == "gemini-2.5-flash"
    assert result.input_tokens == 25
    assert result.output_tokens == 10
    assert result.total_tokens == 35
    assert result.latency_ms >= 0
    assert result.estimated_cost_usd is not None

    # 4. Verify usage record was saved in database
    records = (
        (await db_session.execute(select(LLMUsage).where(LLMUsage.user_id == registered_user.id)))
        .scalars()
        .all()
    )
    assert len(records) == 1
    rec = records[0]
    assert rec.provider == "gemini"
    assert rec.model_id == "gemini-2.5-flash"
    assert rec.input_tokens == 25
    assert rec.output_tokens == 10
    assert rec.total_tokens == 35
    assert rec.status == "success"
    assert rec.estimated_cost is not None
    assert rec.currency == "USD"


@pytest.mark.asyncio
async def test_gateway_explicit_override_routing(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify explicit provider and model overrides bypass default preference."""
    with (
        patch(
            "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
            new_callable=AsyncMock,
            return_value=True,
        ),
        patch(
            "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
            new_callable=AsyncMock,
            return_value=True,
        ),
    ):
        from flowpilot.services.llm import LLMService

        gemini_cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="gemini",
            api_key="AIzaSyDefaultGeminiKey111",
        )
        await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="openai",
            api_key="sk-proj-OverrideOpenAIKey222",
        )
        # Set default to Gemini
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=gemini_cred.id,
            model_id="gemini-2.5-flash",
        )
        await db_session.commit()

    # Invoke with explicit OpenAI override
    mock_openai_response = LLMGenerationResponse(
        content="OpenAI generated text.",
        model="gpt-4o",
        provider="openai",
        usage=TokenUsage(prompt_tokens=40, completion_tokens=15, total_tokens=55),
    )

    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.generate",
        new_callable=AsyncMock,
        return_value=mock_openai_response,
    ):
        result = await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=[LLMMessage(role="user", content="Hello OpenAI")],
            provider="openai",
            model="gpt-4o",
        )

    assert result.provider == "openai"
    assert result.model == "gpt-4o"
    assert result.content == "OpenAI generated text."
    assert result.input_tokens == 40


@pytest.mark.asyncio
async def test_gateway_retry_transient_failure_then_succeed(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify gateway retries on transient ProviderRateLimitError with exponential backoff."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

        cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="gemini",
            api_key="AIzaSyRetryKey333333",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gemini-2.5-flash",
        )
        await db_session.commit()

    # Provider fails on first attempt with RateLimit, then succeeds on retry
    mock_success = LLMGenerationResponse(
        content="Success after retry.",
        model="gemini-2.5-flash",
        provider="gemini",
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
    )

    mock_generate = AsyncMock(
        side_effect=[
            ProviderRateLimitError("Transient rate limit 429"),
            mock_success,
        ]
    )

    with (
        patch(
            "flowpilot.llm.providers.gemini.GeminiProvider.generate",
            mock_generate,
        ),
        patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep,
    ):
        result = await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=[LLMMessage(role="user", content="Test retry")],
        )

    assert result.content == "Success after retry."
    assert mock_generate.call_count == 2
    assert mock_sleep.call_count == 1


@pytest.mark.asyncio
async def test_gateway_non_retryable_error_fails_immediately(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify non-retryable ProviderAuthenticationError fails immediately without retrying."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

        cred = await LLMService.connect_credential(
            db=db_session,
            user_id=registered_user.id,
            provider_name="openai",
            api_key="sk-proj-AuthFailKey4444",
        )
        await LLMService.set_preference(
            db=db_session,
            user_id=registered_user.id,
            credential_id=cred.id,
            model_id="gpt-4o",
        )
        await db_session.commit()

    mock_generate = AsyncMock(
        side_effect=ProviderAuthenticationError("API key revoked during generation")
    )

    with (
        patch("flowpilot.llm.providers.openai.OpenAIProvider.generate", mock_generate),
        pytest.raises(ProviderAuthenticationError),
    ):
        await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=[LLMMessage(role="user", content="Will fail auth")],
        )

    assert mock_generate.call_count == 1

    # Verify failure recorded in usage table without invented tokens
    records = (
        (await db_session.execute(select(LLMUsage).where(LLMUsage.user_id == registered_user.id)))
        .scalars()
        .all()
    )
    assert len(records) == 1
    assert records[0].status.startswith("error")
    assert records[0].input_tokens == 0
    assert records[0].output_tokens == 0


@pytest.mark.asyncio
async def test_gateway_no_preference_configured_error(
    db_session: AsyncSession,
    registered_user: User,
) -> None:
    """Verify gateway raises NoPreferenceConfiguredError when no default preference exists."""
    with pytest.raises(NoPreferenceConfiguredError):
        await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=[LLMMessage(role="user", content="No preference")],
        )


@pytest.mark.asyncio
async def test_gateway_no_unauthorized_fallback(
    db_session: AsyncSession,
    registered_user: User,
    second_user: User,
) -> None:
    """Verify gateway never silently falls back to another user's credential or provider."""
    # User B has a working OpenAI credential
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        from flowpilot.services.llm import LLMService

        await LLMService.connect_credential(
            db=db_session,
            user_id=second_user.id,
            provider_name="openai",
            api_key="sk-proj-UserBSecretKey555",
        )
        await db_session.commit()

    # User A has no credentials connected; attempts to invoke OpenAI
    with pytest.raises(CredentialNotFoundError) as exc_info:
        await gateway.generate(
            db=db_session,
            user_id=registered_user.id,
            messages=[LLMMessage(role="user", content="Should not access User B")],
            provider="openai",
            model="gpt-4o",
        )
    assert "no api key connected" in str(exc_info.value).lower()


# -----------------------------------------------------------------------------
# Integration Tests: /api/v1/llm/generate & /api/v1/llm/usage Endpoints
# -----------------------------------------------------------------------------


def test_api_generate_and_usage_history(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify end-to-end HTTP generation and usage retrieval through REST API."""
    # 1. Connect credential
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        cred_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyValidGeminiKeyE2E999"},
        )
        assert cred_res.status_code == 201
        cred_id = cred_res.json()["id"]

    # 2. Set default preference
    pref_res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={"credential_id": cred_id, "model_id": "gemini-2.5-flash"},
    )
    assert pref_res.status_code == 200

    # 3. Call generation endpoint
    mock_response = LLMGenerationResponse(
        content="FlowPilot orchestrates multi-agent tasks seamlessly.",
        model="gemini-2.5-flash",
        provider="gemini",
        usage=TokenUsage(prompt_tokens=15, completion_tokens=8, total_tokens=23),
    )

    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.generate",
        new_callable=AsyncMock,
        return_value=mock_response,
    ):
        gen_res = client.post(
            "/api/v1/llm/generate",
            headers=auth_headers,
            json={
                "messages": [{"role": "user", "content": "How does FlowPilot work?"}],
                "temperature": 0.5,
            },
        )

    assert gen_res.status_code == 200
    gen_data = gen_res.json()
    assert gen_data["content"] == "FlowPilot orchestrates multi-agent tasks seamlessly."
    assert gen_data["provider"] == "gemini"
    assert gen_data["model"] == "gemini-2.5-flash"
    assert gen_data["usage"]["prompt_tokens"] == 15
    assert gen_data["usage"]["completion_tokens"] == 8
    assert gen_data["usage"]["total_tokens"] == 23

    # 4. Check usage history endpoint
    usage_res = client.get("/api/v1/llm/usage", headers=auth_headers)
    assert usage_res.status_code == 200
    usage_list = usage_res.json()
    assert len(usage_list) == 1
    record = usage_list[0]
    assert record["provider"] == "gemini"
    assert record["model_id"] == "gemini-2.5-flash"
    assert record["total_tokens"] == 23
    assert record["status"] == "success"
