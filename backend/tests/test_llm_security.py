"""Security and encryption tests for Phase 3 LLM credentials and BYOK."""

from unittest.mock import AsyncMock, patch

import pytest
from cryptography.fernet import Fernet, InvalidToken
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.encryption import (
    EncryptionConfigurationError,
    decrypt_api_key,
    encrypt_api_key,
    generate_key_fingerprint,
    get_cipher,
    get_multi_fernet,
)
from flowpilot.models.llm_credential import LLMCredential
from flowpilot.models.llm_preference import LLMPreference
from flowpilot.models.user import User


def test_encryption_and_decryption_roundtrip() -> None:
    """Verify that encrypting an API key and decrypting it returns the exact original plaintext."""
    raw_key = "sk-test-secret-api-key-123456789"
    encrypted = encrypt_api_key(raw_key)

    assert encrypted != raw_key
    assert "sk-test" not in encrypted
    assert len(encrypted) > 50

    decrypted = decrypt_api_key(encrypted)
    assert decrypted == raw_key


def test_key_fingerprint_generation() -> None:
    """Verify key fingerprint is deterministic, non-reversible, and does not expose the key."""
    raw_key_1 = "sk-proj-abc1234567890xyz"
    raw_key_2 = "sk-proj-abc1234567890xyz"
    raw_key_3 = "sk-proj-different-key"

    fp1 = generate_key_fingerprint(raw_key_1)
    fp2 = generate_key_fingerprint(raw_key_2)
    fp3 = generate_key_fingerprint(raw_key_3)

    assert fp1 == fp2
    assert fp1 != fp3
    assert "...0xyz" in fp1
    assert "sk-proj-abc1234567890" not in fp1


def test_multifernet_key_rotation() -> None:
    """Verify that MultiFernet can decrypt data encrypted with an older secondary key."""
    old_key = Fernet.generate_key().decode()
    new_key = Fernet.generate_key().decode()

    # Encrypt with single old key
    fernet_old = Fernet(old_key.encode())
    plaintext = "my-pre-rotation-gemini-key"
    ciphertext = fernet_old.encrypt(plaintext.encode()).decode()

    # Configure MultiFernet with new key first (primary) and old key second
    rotated_fernet = get_multi_fernet((new_key, old_key))

    # Old ciphertext should still be decryptable
    decrypted = rotated_fernet.decrypt(ciphertext.encode()).decode()
    assert decrypted == plaintext

    # New encryption should be with new primary key
    new_ciphertext = rotated_fernet.encrypt(plaintext.encode()).decode()
    fernet_new = Fernet(new_key.encode())
    assert fernet_new.decrypt(new_ciphertext.encode()).decode() == plaintext


def test_decryption_with_wrong_key_fails() -> None:
    """Verify that attempting to decrypt with an incorrect key raises DecryptionError."""
    key_a = Fernet.generate_key().decode()
    key_b = Fernet.generate_key().decode()

    fernet_a = get_multi_fernet((key_a,))
    ciphertext = fernet_a.encrypt(b"secret").decode()

    fernet_b = get_multi_fernet((key_b,))
    with pytest.raises(InvalidToken):
        fernet_b.decrypt(ciphertext.encode())


def test_missing_encryption_keys_raises_error() -> None:
    """Verify that invoking get_multi_fernet with empty keys raises EncryptionConfigurationError."""
    with pytest.raises(EncryptionConfigurationError):
        get_multi_fernet(())


def test_missing_settings_keys_raises_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify get_cipher() raises error when LLM_ENCRYPTION_KEYS is empty."""
    settings = get_settings()
    monkeypatch.setattr(settings, "LLM_ENCRYPTION_KEYS", [])
    with pytest.raises(EncryptionConfigurationError):
        get_cipher()


async def test_plaintext_never_stored_in_database(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify that plaintext API keys are never stored in the database."""
    raw_api_key = "AIzaSyTestGeminiKey9876543210ABC"

    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        response = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={
                "provider": "gemini",
                "api_key": raw_api_key,
            },
        )
    assert response.status_code == 201

    # Query the database directly to inspect stored record
    result = await db_session.execute(
        select(LLMCredential).where(LLMCredential.user_id == registered_user.id)
    )
    db_cred = result.scalar_one()

    # Assert database stores encrypted text, not plaintext
    assert db_cred.encrypted_api_key != raw_api_key
    assert raw_api_key not in db_cred.encrypted_api_key
    assert "AIzaSy" not in db_cred.encrypted_api_key

    # Assert key can be properly decrypted
    assert decrypt_api_key(db_cred.encrypted_api_key) == raw_api_key


def test_api_responses_never_expose_plaintext_key(
    client: TestClient,
    auth_headers: dict[str, str],
) -> None:
    """Verify that responses from credentials endpoints never expose raw API keys."""
    raw_api_key = "sk-test-super-secret-key-9999"

    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        # 1. Connect
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": raw_api_key},
        )
        assert create_res.status_code == 201
        data = create_res.json()
        assert raw_api_key not in str(data)
        assert "encrypted_api_key" not in data
        assert "key_fingerprint" in data
        cred_id = data["id"]

        # 2. List
        list_res = client.get("/api/v1/llm/credentials", headers=auth_headers)
        assert list_res.status_code == 200
        assert raw_api_key not in str(list_res.json())

        # 3. Replace
        new_key = "sk-test-replacement-key-8888"
        update_res = client.put(
            f"/api/v1/llm/credentials/{cred_id}",
            headers=auth_headers,
            json={"api_key": new_key},
        )
        assert update_res.status_code == 200
        assert new_key not in str(update_res.json())
        assert raw_api_key not in str(update_res.json())


def test_cross_user_credential_isolation(
    client: TestClient,
    auth_headers: dict[str, str],
    second_auth_headers: dict[str, str],
) -> None:
    """Verify User B cannot access, test, replace, or delete User A's credential."""
    with patch(
        "flowpilot.llm.providers.gemini.GeminiProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        # User A connects credential
        res_a = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "gemini", "api_key": "AIzaSyUserASecretKey"},
        )
        assert res_a.status_code == 201
        cred_id = res_a.json()["id"]

    # User B attempts to test User A's credential
    res_b_test = client.post(
        f"/api/v1/llm/credentials/{cred_id}/test",
        headers=second_auth_headers,
    )
    assert res_b_test.status_code == 404

    # User B attempts to replace User A's credential
    res_b_put = client.put(
        f"/api/v1/llm/credentials/{cred_id}",
        headers=second_auth_headers,
        json={"api_key": "AIzaSyHackerKey"},
    )
    assert res_b_put.status_code == 404

    # User B attempts to delete User A's credential
    res_b_del = client.delete(
        f"/api/v1/llm/credentials/{cred_id}",
        headers=second_auth_headers,
    )
    assert res_b_del.status_code == 404

    # Verify User B's list does not contain User A's credential
    res_b_list = client.get("/api/v1/llm/credentials", headers=second_auth_headers)
    assert res_b_list.status_code == 200
    assert len(res_b_list.json()) == 0


async def test_credential_deletion_invalidates_default_preference(
    client: TestClient,
    auth_headers: dict[str, str],
    registered_user: User,
    db_session: AsyncSession,
) -> None:
    """Verify that deleting a credential safely cleans up/invalidates any active LLM preference."""
    with patch(
        "flowpilot.llm.providers.openai.OpenAIProvider.validate_credentials",
        new_callable=AsyncMock,
        return_value=True,
    ):
        # 1. Connect credential
        create_res = client.post(
            "/api/v1/llm/credentials",
            headers=auth_headers,
            json={"provider": "openai", "api_key": "sk-test-key-for-cascade"},
        )
        assert create_res.status_code == 201
        cred_id = create_res.json()["id"]

    # 2. Set default preference
    pref_res = client.put(
        "/api/v1/llm/preferences",
        headers=auth_headers,
        json={"credential_id": cred_id, "model_id": "gpt-4o-mini"},
    )
    assert pref_res.status_code == 200

    # Verify preference exists in DB
    pref_query = await db_session.execute(
        select(LLMPreference).where(LLMPreference.user_id == registered_user.id)
    )
    assert pref_query.scalar_one_or_none() is not None

    # 3. Delete credential
    del_res = client.delete(f"/api/v1/llm/credentials/{cred_id}", headers=auth_headers)
    assert del_res.status_code == 200
    assert "successfully deleted" in del_res.json()["message"].lower()

    # 4. Verify preference is invalidated (404 on get preferences)
    get_pref = client.get("/api/v1/llm/preferences", headers=auth_headers)
    assert get_pref.status_code == 404

    # Direct DB check: preference row was removed
    target_user_id = registered_user.id
    pref_query2 = await db_session.execute(
        select(LLMPreference).where(LLMPreference.user_id == target_user_id)
    )
    assert pref_query2.scalar_one_or_none() is None
