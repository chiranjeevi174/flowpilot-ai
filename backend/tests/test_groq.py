"""Comprehensive test suite for Groq LLM Provider, BYOK, and Gateway integration."""

import os
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import groq
import pytest
from fastapi.testclient import TestClient

from flowpilot.llm.pricing import calculate_cost
from flowpilot.llm.providers.base import (
    LLMGenerationRequest,
    LLMMessage,
    ModelInfo,
    ModelNotFoundError,
    ProviderAuthenticationError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from flowpilot.llm.providers.groq import GroqProvider


@pytest.fixture
def groq_provider() -> GroqProvider:
    return GroqProvider()


# --- Unit Tests for GroqProvider Adapter ---


@pytest.mark.asyncio
async def test_groq_validate_credentials_success(groq_provider: GroqProvider):
    """Verify credential validation passes when models.list() succeeds."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(return_value=MagicMock())

    with patch.object(groq_provider, "_get_client", return_value=mock_client):
        valid = await groq_provider.validate_credentials("gsk_test_valid_key_1234567890")
        assert valid is True
        mock_client.models.list.assert_awaited_once()


@pytest.mark.asyncio
async def test_groq_validate_credentials_auth_error(groq_provider: GroqProvider):
    """Verify AuthenticationError is mapped to ProviderAuthenticationError."""
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=401)
    mock_client.models.list = AsyncMock(
        side_effect=groq.AuthenticationError(
            message="Invalid API Key",
            response=mock_response,
            body={"error": {"message": "Invalid API Key"}},
        )
    )

    with (
        patch.object(groq_provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderAuthenticationError),
    ):
        await groq_provider.validate_credentials("gsk_invalid_key_1234567890")


@pytest.mark.asyncio
async def test_groq_validate_credentials_rate_limit(groq_provider: GroqProvider):
    """Verify RateLimitError is mapped to ProviderRateLimitError."""
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=429)
    mock_client.models.list = AsyncMock(
        side_effect=groq.RateLimitError(
            message="Rate limit reached",
            response=mock_response,
            body={"error": {"message": "Rate limit reached"}},
        )
    )

    with (
        patch.object(groq_provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderRateLimitError),
    ):
        await groq_provider.validate_credentials("gsk_key_1234567890")


@pytest.mark.asyncio
async def test_groq_validate_credentials_quota_error(groq_provider: GroqProvider):
    """Verify RateLimitError with quota message maps to ProviderQuotaExceededError."""
    mock_client = MagicMock()
    mock_response = MagicMock(status_code=429)
    mock_client.models.list = AsyncMock(
        side_effect=groq.RateLimitError(
            message="Insufficient quota or balance exhausted",
            response=mock_response,
            body={"error": {"message": "Insufficient quota"}},
        )
    )

    with (
        patch.object(groq_provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderQuotaExceededError),
    ):
        await groq_provider.validate_credentials("gsk_key_1234567890")


@pytest.mark.asyncio
async def test_groq_validate_credentials_timeout(groq_provider: GroqProvider):
    """Verify APITimeoutError maps to ProviderTimeoutError."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=groq.APITimeoutError(request=MagicMock()))

    with (
        patch.object(groq_provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderTimeoutError),
    ):
        await groq_provider.validate_credentials("gsk_key_1234567890")


@pytest.mark.asyncio
async def test_groq_validate_credentials_unavailable(groq_provider: GroqProvider):
    """Verify APIConnectionError maps to ProviderUnavailableError."""
    mock_client = MagicMock()
    mock_client.models.list = AsyncMock(side_effect=groq.APIConnectionError(request=MagicMock()))

    with (
        patch.object(groq_provider, "_get_client", return_value=mock_client),
        pytest.raises(ProviderUnavailableError),
    ):
        await groq_provider.validate_credentials("gsk_key_1234567890")


@pytest.mark.asyncio
async def test_groq_list_models_filtering(groq_provider: GroqProvider):
    """Verify non-text models (whisper, guard) are filtered and text models are kept."""
    mock_client = MagicMock()

    m1 = MagicMock(id="llama-3.3-70b-versatile", owned_by="meta")
    m2 = MagicMock(id="whisper-large-v3", owned_by="openai")
    m3 = MagicMock(id="llama-guard-3-8b", owned_by="meta")
    m4 = MagicMock(id="mixtral-8x7b-32768", owned_by="mistralai")
    m5 = MagicMock(id="gemma2-9b-it", owned_by="google")
    m6 = MagicMock(id="deepseek-r1-distill-llama-70b", owned_by="deepseek")

    mock_page = MagicMock(data=[m1, m2, m3, m4, m5, m6])
    mock_client.models.list = AsyncMock(return_value=mock_page)

    with patch.object(groq_provider, "_get_client", return_value=mock_client):
        models = await groq_provider.list_models("gsk_key_1234567890")

    model_ids = [m.id for m in models]
    assert "llama-3.3-70b-versatile" in model_ids
    assert "mixtral-8x7b-32768" in model_ids
    assert "gemma2-9b-it" in model_ids
    assert "deepseek-r1-distill-llama-70b" in model_ids
    # Whisper & Guard must be excluded
    assert "whisper-large-v3" not in model_ids
    assert "llama-guard-3-8b" not in model_ids

    # Context window checks
    llama_info = next(m for m in models if m.id == "llama-3.3-70b-versatile")
    assert llama_info.context_window == 128000
    assert llama_info.provider == "groq"
    mixtral_info = next(m for m in models if m.id == "mixtral-8x7b-32768")
    assert mixtral_info.context_window == 32768


@pytest.mark.asyncio
async def test_groq_validate_model_support(groq_provider: GroqProvider):
    """Verify validation succeeds for existing models and raises for unsupported ones."""
    mock_client = MagicMock()
    m1 = MagicMock(id="llama-3.3-70b-versatile", owned_by="meta")
    mock_page = MagicMock(data=[m1])
    mock_client.models.list = AsyncMock(return_value=mock_page)

    with patch.object(groq_provider, "_get_client", return_value=mock_client):
        assert await groq_provider.validate_model_support("key", "llama-3.3-70b-versatile") is True
        with pytest.raises(ModelNotFoundError):
            await groq_provider.validate_model_support("key", "non-existent-model")


@pytest.mark.asyncio
async def test_groq_generate_success(groq_provider: GroqProvider):
    """Verify text generation and token usage extraction."""
    mock_client = MagicMock()
    mock_response = MagicMock(
        choices=[MagicMock(message=MagicMock(content="Hello from Groq!"))],
        usage=MagicMock(prompt_tokens=15, completion_tokens=8, total_tokens=23),
    )
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    req = LLMGenerationRequest(
        messages=[
            LLMMessage(role="system", content="You are a helpful assistant."),
            LLMMessage(role="user", content="Say hello."),
        ],
        model="llama-3.3-70b-versatile",
        temperature=0.5,
        max_tokens=100,
    )

    with patch.object(groq_provider, "_get_client", return_value=mock_client):
        res = await groq_provider.generate("gsk_key", req)

    assert res.content == "Hello from Groq!"
    assert res.provider == "groq"
    assert res.model == "llama-3.3-70b-versatile"
    assert res.usage is not None
    assert res.usage.prompt_tokens == 15
    assert res.usage.completion_tokens == 8
    assert res.usage.total_tokens == 23


# --- Pricing and Cost Calculation Tests ---


def test_groq_pricing_calculation():
    """Verify token cost calculation for Groq models and null return for unknown models."""
    cost, currency = calculate_cost(
        provider="groq",
        model="llama-3.3-70b-versatile",
        input_tokens=1000,
        output_tokens=1000,
    )
    assert currency == "USD"
    # input: 1000/1M * 0.59 = 0.00059, output: 1000/1M * 0.79 = 0.00079 => total = 0.00138
    assert cost == Decimal("0.001380")

    # Fast small model
    cost_small, _ = calculate_cost(
        provider="groq",
        model="llama-3.1-8b-instant",
        input_tokens=10000,
        output_tokens=5000,
    )
    assert cost_small is not None

    # Unknown model must return None rather than invented number
    unknown_cost, unknown_curr = calculate_cost(
        provider="groq",
        model="future-unpriced-model-v99",
        input_tokens=100,
        output_tokens=100,
    )
    assert unknown_cost is None
    assert unknown_curr is None


# --- End-to-End API Integration Tests for Groq ---


def test_api_connect_groq_success(client: TestClient, auth_headers: dict[str, str]):
    """Verify connecting a Groq API key via API endpoint."""
    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "groq", "api_key": "gsk_valid_groq_api_key_test_12345"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "groq"
    assert "key_fingerprint" in data
    assert "api_key" not in data
    assert "encrypted_api_key" not in data


def test_api_groq_model_discovery(client: TestClient, auth_headers: dict[str, str]):
    """Verify discovering Groq models for a connected user."""
    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        connect_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "groq", "api_key": "gsk_valid_key_for_discovery_123"},
        )
        assert connect_res.status_code in (201, 409)

    mock_models = [
        ModelInfo(
            id="llama-3.3-70b-versatile",
            name="llama-3.3-70b-versatile",
            provider="groq",
            description="Llama 3.3",
            context_window=128000,
        ),
        ModelInfo(
            id="mixtral-8x7b-32768",
            name="mixtral-8x7b-32768",
            provider="groq",
            description="Mixtral 8x7B",
            context_window=32768,
        ),
    ]

    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.list_models",
        new_callable=AsyncMock,
        return_value=mock_models,
    ):
        res = client.get("/api/v1/llm/models?provider=groq", headers=auth_headers)
        assert res.status_code == 200
        models_data = res.json()
        assert len(models_data) == 2
        ids = [m["id"] for m in models_data]
        assert "llama-3.3-70b-versatile" in ids
        assert "mixtral-8x7b-32768" in ids


def test_api_set_groq_preference_and_cascade_delete(
    client: TestClient, auth_headers: dict[str, str]
):
    """Verify setting default preference to Groq, and that deleting credential clears preference."""
    # 1. Connect Groq
    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        cred_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "groq", "api_key": "gsk_pref_test_key_12345678"},
        )
        if cred_res.status_code == 409:
            # Already connected in this test session, fetch credentials
            list_res = client.get("/api/v1/llm/credentials", headers=auth_headers)
            creds = list_res.json()
            cred_id = next(c["id"] for c in creds if c["provider"] == "groq")
        else:
            assert cred_res.status_code == 201
            cred_id = cred_res.json()["id"]

    # 2. Set preference
    pref_res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={"credential_id": cred_id, "model_id": "llama-3.3-70b-versatile"},
    )
    assert pref_res.status_code == 200
    pref_data = pref_res.json()
    assert pref_data["provider"] == "groq"
    assert pref_data["model_id"] == "llama-3.3-70b-versatile"

    # 3. Verify get preference
    get_pref = client.get("/api/v1/llm/preferences", headers=auth_headers)
    assert get_pref.status_code == 200
    assert get_pref.json()["provider"] == "groq"

    # 4. Delete credential and verify preference cascade
    del_res = client.delete(f"/api/v1/llm/credentials/{cred_id}", headers=auth_headers)
    assert del_res.status_code == 200

    after_pref = client.get("/api/v1/llm/preferences", headers=auth_headers)
    assert after_pref.status_code == 404


def test_api_cross_user_groq_isolation(client: TestClient, auth_headers: dict[str, str]):
    """Verify User B cannot access or list User A's Groq credentials."""
    # User A connects Groq
    with patch(
        "flowpilot.llm.providers.groq.GroqProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "groq", "api_key": "gsk_usera_secret_key_12345"},
        )

    # Register and login User B
    user_b_email = f"userb_{uuid.uuid4().hex[:6]}@example.com"
    reg_b = client.post(
        "/api/v1/auth/register",
        json={"email": user_b_email, "password": "Password123!", "full_name": "User B"},
    )
    assert reg_b.status_code == 201

    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": user_b_email, "password": "Password123!"},
    )
    assert login_b.status_code == 200
    token_b = login_b.json()["access_token"]
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # User B lists credentials -> should NOT see User A's groq credential
    list_b = client.get("/api/v1/llm/credentials", headers=headers_b)
    assert list_b.status_code == 200
    creds_b = list_b.json()
    assert not any(c["provider"] == "groq" for c in creds_b)


# --- Optional Live Smoke Test ---


@pytest.mark.skipif(
    not os.getenv("GROQ_API_KEY"),
    reason="Requires live GROQ_API_KEY environment variable",
)
@pytest.mark.asyncio
async def test_live_groq_smoke():
    """Optional live integration smoke test using user-supplied GROQ_API_KEY."""
    api_key = os.environ["GROQ_API_KEY"]
    provider = GroqProvider()
    valid = await provider.validate_credentials(api_key)
    assert valid is True

    models = await provider.list_models(api_key)
    assert len(models) > 0
    first_model = models[0].id

    req = LLMGenerationRequest(
        messages=[LLMMessage(role="user", content="Reply with one word: 'READY'.")],
        model=first_model,
        max_tokens=10,
    )
    resp = await provider.generate(api_key, req)
    assert resp.content.strip() != ""
    assert resp.usage is not None
