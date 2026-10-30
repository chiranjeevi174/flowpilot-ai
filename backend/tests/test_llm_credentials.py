"""Automated integration tests for LLM Credential and Preference management endpoints."""

import uuid
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from flowpilot.llm.providers.base import ProviderAuthenticationError


def test_list_supported_providers(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify listing supported providers returns gemini, openai, and groq."""
    response = client.get("/api/v1/llm/providers", headers=auth_headers)
    assert response.status_code == 200
    providers = response.json()
    ids = [p["id"] for p in providers]
    assert "gemini" in ids
    assert "openai" in ids
    assert "groq" in ids


def test_connect_provider_success(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify successfully connecting a Gemini credential with simulated SDK validation."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyValidGeminiKey123456789"},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["provider"] == "gemini"
    assert "key_fingerprint" in data
    assert data["last_validated_at"] is not None
    assert "api_key" not in data
    assert "encrypted_api_key" not in data


def test_connect_provider_duplicate_rejection(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify connecting the same provider twice for the same user is rejected with 409 Conflict."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        first_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-testkey11111111111"},
        )
        assert first_res.status_code == 201

        second_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-testkey22222222222"},
        )
        assert second_res.status_code == 409
        assert "already connected" in second_res.json()["detail"].lower()


def test_connect_provider_invalid_key_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify connecting with an invalid API key is rejected by the provider check.

    Must return 400 Bad Request.
    """
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        side_effect=ProviderAuthenticationError("API key not valid. Please pass a valid API key."),
    ):
        response = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyInvalidKeyProvided123"},
        )
    assert response.status_code == 400
    assert "verification failed" in response.json()["detail"].lower()


def test_connect_provider_empty_or_short_key_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify malformed or too short API keys are rejected by Pydantic schema validation."""
    response = client.post(
        "/api/v1/llm/credentials",
        headers=auth_headers,
        json={"provider": "gemini", "api_key": "short"},
    )
    assert response.status_code == 422


def test_list_user_credentials(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify listing credentials returns all connected providers for the authenticated user."""
    # Initially empty
    initial_res = client.get("/api/v1/llm/credentials", headers=auth_headers)
    assert initial_res.status_code == 200
    assert initial_res.json() == []

    # Connect both gemini and openai
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
        client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyGeminiKey99999999999"},
        )
        client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-OpenAIKey9999999999"},
        )

    # Check list
    list_res = client.get("/api/v1/llm/credentials", headers=auth_headers)
    assert list_res.status_code == 200
    data = list_res.json()
    assert len(data) == 2
    providers = {c["provider"] for c in data}
    assert providers == {"gemini", "openai"}


def test_test_credential_connection_endpoint(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify on-demand credential testing endpoint."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyGeminiKey99999999999"},
        )
        cred_id = create_res.json()["id"]

        test_res = client.post(
            f"/api/v1/llm/credentials/{cred_id}/test",
            headers=auth_headers,
        )
        assert test_res.status_code == 200
        test_data = test_res.json()
        assert test_data["status"] == "valid"
        assert "successful" in test_data["message"].lower()


def test_test_credential_connection_failure(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify testing a credential when provider fails reports error."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-OpenAIKey9999999999"},
        )
        cred_id = create_res.json()["id"]

    # When testing, provider raises auth error
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        side_effect=ProviderAuthenticationError("Revoked API key"),
    ):
        test_res = client.post(
            f"/api/v1/llm/credentials/{cred_id}/test",
            headers=auth_headers,
        )
        assert test_res.status_code == 400
        assert "failed" in test_res.json()["detail"].lower()


def test_replace_credential(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify updating/replacing an existing credential's secret key."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyOriginalKey1111111"},
        )
        cred_id = create_res.json()["id"]
        orig_fp = create_res.json()["key_fingerprint"]

        # Replace with new valid key
        update_res = client.put(
            f"/api/v1/llm/credentials/{cred_id}",
            headers=auth_headers,
            json={"api_key": "AIzaSyReplacementKey2222222"},
        )
        assert update_res.status_code == 200
        new_fp = update_res.json()["key_fingerprint"]
        assert new_fp != orig_fp


def test_delete_credential(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify deleting a credential removes it from active credentials."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-DeleteMeKey1234567"},
        )
        cred_id = create_res.json()["id"]

        del_res = client.delete(f"/api/v1/llm/credentials/{cred_id}", headers=auth_headers)
        assert del_res.status_code == 200

        # Trying to delete again returns 404
        del_again = client.delete(f"/api/v1/llm/credentials/{cred_id}", headers=auth_headers)
        assert del_again.status_code == 404


def test_preferences_lifecycle(client: TestClient, auth_headers: dict[str, str]) -> None:
    """Verify setting and retrieving user default LLM preferences."""
    # 404 when no preference configured
    get_res = client.get("/api/v1/llm/preferences", headers=auth_headers)
    assert get_res.status_code == 404

    # Connect credential
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-proj-PrefKey123456789"},
        )
        cred_id = create_res.json()["id"]

    # Set preference
    set_res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={"credential_id": cred_id, "model_id": "gpt-4o"},
    )
    assert set_res.status_code == 200
    pref = set_res.json()
    assert pref["credential_id"] == cred_id
    assert pref["provider"] == "openai"
    assert pref["model_id"] == "gpt-4o"

    # Retrieve preference
    get_res2 = client.get("/api/v1/llm/preferences", headers=auth_headers)
    assert get_res2.status_code == 200
    assert get_res2.json()["model_id"] == "gpt-4o"


def test_set_preference_nonexistent_credential_rejected(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    """Verify setting a preference pointing to an unknown credential is rejected with 404."""
    fake_id = str(uuid.uuid4())
    res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={"credential_id": fake_id, "model_id": "gpt-4o"},
    )
    assert res.status_code == 404
