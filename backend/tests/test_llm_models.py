"""Automated tests for LLM provider adapters and dynamic model discovery."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from flowpilot.llm.providers.base import (
    ModelInfo,
    ProviderAuthenticationError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
    UnsupportedModelError,
)
from flowpilot.llm.providers.gemini import GeminiProvider
from flowpilot.llm.providers.openai import OpenAIProvider

# -----------------------------------------------------------------------------
# Unit Tests: Gemini Provider Adapter
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gemini_model_discovery_filtering() -> None:
    """Verify Gemini provider dynamically filters models, including only text generation models."""
    provider = GeminiProvider()

    # Mock official Google GenAI model objects
    mock_model_text = MagicMock()
    mock_model_text.name = "models/gemini-2.5-flash"
    mock_model_text.display_name = "Gemini 2.5 Flash"
    mock_model_text.description = "Next generation fast multimodal model"
    mock_model_text.supported_actions = ["generateContent"]

    mock_model_embedding = MagicMock()
    mock_model_embedding.name = "models/text-embedding-004"
    mock_model_embedding.display_name = "Text Embedding"
    mock_model_embedding.description = "Embedding model"
    mock_model_embedding.supported_actions = ["embedContent"]

    mock_model_aqa = MagicMock()
    mock_model_aqa.name = "models/aqa"
    mock_model_aqa.display_name = "Attributed QA"
    mock_model_aqa.description = "AQA"
    mock_model_aqa.supported_actions = ["generateAnswer"]

    mock_pager = [mock_model_text, mock_model_embedding, mock_model_aqa]

    mock_client = MagicMock()
    mock_client.aio.models.list = AsyncMock(return_value=mock_pager)

    with patch.object(provider, "_get_client", return_value=mock_client):
        models = await provider.list_models("test-gemini-key")

    assert len(models) == 1
    assert models[0].id == "gemini-2.5-flash"
    assert models[0].provider == "gemini"
    assert models[0].supports_streaming is True


@pytest.mark.asyncio
async def test_gemini_unsupported_model_validation() -> None:
    """Verify Gemini provider rejects non-existent or unsupported models."""
    provider = GeminiProvider()

    mock_model = MagicMock()
    mock_model.name = "models/gemini-2.5-flash"
    mock_model.display_name = "Gemini 2.5 Flash"
    mock_model.description = "Fast model"
    mock_model.supported_actions = ["generateContent"]

    mock_client = MagicMock()
    mock_client.aio.models.list = AsyncMock(return_value=[mock_model])

    with patch.object(provider, "_get_client", return_value=mock_client):
        # Existing model validates
        await provider.validate_model_support("test-key", "gemini-2.5-flash")

        # Unsupported model raises UnsupportedModelError
        with pytest.raises(UnsupportedModelError) as exc_info:
            await provider.validate_model_support("test-key", "non-existent-gemini-model")
        assert "not supported or unavailable" in str(exc_info.value)


# -----------------------------------------------------------------------------
# Unit Tests: OpenAI Provider Adapter
# -----------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_openai_model_discovery_filtering() -> None:
    """Verify OpenAI provider dynamically filters out embeddings and non-text models."""
    provider = OpenAIProvider()

    # Create mock model objects
    def make_model(model_id: str) -> MagicMock:
        m = MagicMock()
        m.id = model_id
        m.owned_by = "openai"
        return m

    mock_models = [
        make_model("gpt-4o"),
        make_model("gpt-4o-mini"),
        make_model("o1-mini"),
        make_model("text-embedding-3-small"),  # Should be excluded
        make_model("whisper-1"),  # Should be excluded
        make_model("dall-e-3"),  # Should be excluded
        make_model("tts-1"),  # Should be excluded
        make_model("babbage-002"),  # Should be excluded
    ]

    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=mock_models)

    with patch.object(provider, "_get_client", return_value=mock_client):
        models = await provider.list_models("sk-test-openai-key")

    model_ids = [m.id for m in models]
    assert "gpt-4o" in model_ids
    assert "gpt-4o-mini" in model_ids
    assert "o1-mini" in model_ids
    assert "text-embedding-3-small" not in model_ids
    assert "whisper-1" not in model_ids
    assert "dall-e-3" not in model_ids
    assert "tts-1" not in model_ids
    assert "babbage-002" not in model_ids


@pytest.mark.asyncio
async def test_openai_error_mapping() -> None:
    """Verify OpenAI SDK errors map correctly to FlowPilot domain exceptions."""
    from openai import (
        APIConnectionError,
        APITimeoutError,
        AuthenticationError,
        RateLimitError,
    )

    provider = OpenAIProvider()
    mock_client = MagicMock()

    # 1. Authentication error
    mock_client.models.list = AsyncMock(
        side_effect=AuthenticationError(
            "Incorrect API key provided", response=MagicMock(status_code=401), body={}
        )
    )
    with (
        patch.object(provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderAuthenticationError),
    ):
        await provider.validate_credentials("bad-key")

    # 2. Rate limit error
    mock_client.models.list = AsyncMock(
        side_effect=RateLimitError(
            "Rate limit reached", response=MagicMock(status_code=429), body={}
        )
    )
    with (
        patch.object(provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderRateLimitError),
    ):
        await provider.list_models("test-key")

    # 3. Connection error -> ProviderUnavailableError
    mock_client.models.list = AsyncMock(side_effect=APIConnectionError(request=MagicMock()))
    with (
        patch.object(provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderUnavailableError),
    ):
        await provider.list_models("test-key")

    # 4. Timeout error -> ProviderTimeoutError
    mock_client.models.list = AsyncMock(side_effect=APITimeoutError(request=MagicMock()))
    with (
        patch.object(provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderTimeoutError),
    ):
        await provider.list_models("test-key")


# -----------------------------------------------------------------------------
# Integration Tests: /api/v1/llm/models Endpoint
# -----------------------------------------------------------------------------


def test_discover_models_endpoint_success(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify GET /api/v1/llm/models returns discovered models for a connected credential."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        # Connect Gemini credential
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyGeminiTestKeyDiscovery123"},
        )
        assert create_res.status_code == 201

    # Mock model listing
    fake_models = [
        ModelInfo(
            id="gemini-2.5-flash",
            name="Gemini 2.5 Flash",
            provider="gemini",
            description="Fast multimodal model",
            supports_streaming=True,
            context_window=1048576,
        ),
        ModelInfo(
            id="gemini-2.5-pro",
            name="Gemini 2.5 Pro",
            provider="gemini",
            description="High intelligence flagship model",
            supports_streaming=True,
            context_window=2097152,
        ),
    ]

    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.list_models",
        new_callable=AsyncMock,
        return_value=fake_models,
    ):
        response = client.get("/api/v1/llm/models?provider=gemini", headers=auth_headers)

    assert response.status_code == 200
    models_data = response.json()
    assert len(models_data) == 2
    assert models_data[0]["id"] == "gemini-2.5-flash"
    assert models_data[1]["id"] == "gemini-2.5-pro"
    assert "api_key" not in str(models_data)


def test_discover_models_without_connected_credential(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify requesting models for an unconnected provider returns 404."""
    response = client.get("/api/v1/llm/models?provider=openai", headers=auth_headers)
    assert response.status_code == 404
    assert "no connected credentials" in response.json()["detail"].lower()


def test_discover_models_provider_failure_returns_bad_gateway(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify provider failure during model listing returns appropriate error status."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-ValidOpenAIKey55555"},
        )

    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.list_models",
        new_callable=AsyncMock,
        side_effect=ProviderRateLimitError("OpenAI rate limit exceeded during listing"),
    ):
        response = client.get("/api/v1/llm/models?provider=openai", headers=auth_headers)

    assert response.status_code == 429
    assert "rate limit" in response.json()["detail"].lower()
