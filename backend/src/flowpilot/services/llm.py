"""Business logic service for LLM credentials, model discovery, preferences, and usage."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.encryption import (
    decrypt_api_key,
    encrypt_api_key,
    generate_key_fingerprint,
)
from flowpilot.core.logging import get_logger
from flowpilot.llm.providers import (
    ModelInfo,
    get_provider,
    list_supported_providers,
)
from flowpilot.models.llm_credential import LLMCredential
from flowpilot.models.llm_preference import LLMPreference
from flowpilot.models.llm_usage import LLMUsage
from flowpilot.schemas.llm import ConnectionTestResponse

logger = get_logger("services.llm")


class LLMServiceError(Exception):
    """Base exception for LLM service operations."""


class CredentialNotFoundError(LLMServiceError):
    """Raised when an LLM credential is not found or not owned by user."""


class PreferenceNotFoundError(LLMServiceError):
    """Raised when no LLM preference is configured."""


class DuplicateCredentialError(LLMServiceError):
    """Raised when attempting to connect an already configured provider."""


class LLMService:
    """Service encapsulating BYOK credentials, preferences, model discovery, and usage."""

    @staticmethod
    def get_supported_providers() -> list[dict[str, str]]:
        """Return all supported LLM providers."""
        return list_supported_providers()

    @classmethod
    async def connect_credential(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        provider_name: str,
        api_key: str,
    ) -> LLMCredential:
        """Validate, encrypt, and store user's BYOK provider credentials."""
        clean_key = api_key.strip()
        provider = get_provider(provider_name)

        # 1. Validate credentials with provider API
        await provider.validate_credentials(clean_key)
        now = datetime.now(UTC)

        # 2. Check for existing credential for this user/provider
        existing_result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.user_id == user_id,
                LLMCredential.provider == provider.provider_name,
            )
        )
        existing = existing_result.scalar_one_or_none()
        if existing is not None:
            msg = (
                f"Provider '{provider.provider_name}' is already connected. "
                "Use PUT to replace the credential."
            )
            raise DuplicateCredentialError(msg)

        # 3. Encrypt API key and generate safe fingerprint
        encrypted_key = encrypt_api_key(clean_key)
        fingerprint = generate_key_fingerprint(clean_key)

        cred = LLMCredential(
            user_id=user_id,
            provider=provider.provider_name,
            encrypted_api_key=encrypted_key,
            key_fingerprint=fingerprint,
            last_validated_at=now,
        )
        db.add(cred)
        await db.flush()
        await db.refresh(cred)
        logger.info(
            "Connected %s credentials for user_id=%s, fingerprint=%s",
            provider.provider_name,
            user_id,
            fingerprint,
        )
        return cred

    @classmethod
    async def list_credentials(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[LLMCredential]:
        """List all active credentials owned by the user (keys remain encrypted)."""
        result = await db.execute(
            select(LLMCredential)
            .where(LLMCredential.user_id == user_id)
            .order_by(LLMCredential.created_at)
        )
        return list(result.scalars().all())

    @classmethod
    async def test_credential(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> ConnectionTestResponse:
        """Execute on-demand connection verification for a connected credential."""
        result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.id == credential_id,
                LLMCredential.user_id == user_id,
            )
        )
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")

        plain_key = decrypt_api_key(cred.encrypted_api_key)
        provider = get_provider(cred.provider)

        await provider.validate_credentials(plain_key)
        now = datetime.now(UTC)
        cred.last_validated_at = now
        await db.flush()

        return ConnectionTestResponse(
            provider=cred.provider,
            status="valid",
            message=f"Successfully authenticated connection to {cred.provider.title()}.",
            tested_at=now,
        )

    @classmethod
    async def replace_credential(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        credential_id: uuid.UUID,
        new_api_key: str,
    ) -> LLMCredential:
        """Replace the API key on an existing credential record."""
        clean_key = new_api_key.strip()
        result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.id == credential_id,
                LLMCredential.user_id == user_id,
            )
        )
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")

        provider = get_provider(cred.provider)
        await provider.validate_credentials(clean_key)

        now = datetime.now(UTC)
        cred.encrypted_api_key = encrypt_api_key(clean_key)
        cred.key_fingerprint = generate_key_fingerprint(clean_key)
        cred.last_validated_at = now
        cred.updated_at = now

        await db.flush()
        await db.refresh(cred)
        logger.info(
            "Replaced API key on credential %s for user_id=%s",
            credential_id,
            user_id,
        )
        return cred

    @classmethod
    async def delete_credential(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        credential_id: uuid.UUID,
    ) -> None:
        """Delete an LLM credential, automatically invalidating any associated preference."""
        result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.id == credential_id,
                LLMCredential.user_id == user_id,
            )
        )
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(f"Credential '{credential_id}' not found.")

        # Invalidate any preference referencing this credential
        await db.execute(
            delete(LLMPreference).where(
                LLMPreference.credential_id == credential_id,
                LLMPreference.user_id == user_id,
            )
        )

        await db.delete(cred)
        await db.flush()
        logger.info("Deleted credential %s for user_id=%s", credential_id, user_id)

    @classmethod
    async def list_models(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        provider_name: str | None = None,
    ) -> list[ModelInfo]:
        """Discover available models for user's connected providers."""
        query = select(LLMCredential).where(LLMCredential.user_id == user_id)
        if provider_name:
            query = query.where(LLMCredential.provider == provider_name.strip().lower())

        result = await db.execute(query)
        credentials = list(result.scalars().all())

        if provider_name and not credentials:
            raise CredentialNotFoundError(
                f"No connected credentials found for provider '{provider_name}'."
            )

        all_models: list[ModelInfo] = []

        if not credentials:
            return []

        for cred in credentials:
            plain_key = decrypt_api_key(cred.encrypted_api_key)
            provider = get_provider(cred.provider)
            discovered = await provider.list_models(plain_key)
            all_models.extend(discovered)

        return all_models

    @classmethod
    async def get_preference(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> LLMPreference | None:
        """Retrieve user's active default LLM preference."""
        result = await db.execute(select(LLMPreference).where(LLMPreference.user_id == user_id))
        return result.scalar_one_or_none()

    @classmethod
    async def update_preference(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        credential_id: uuid.UUID,
        model_id: str,
    ) -> LLMPreference:
        """Set or update user's default provider and model preference."""
        # Ensure credential exists and belongs to this user
        result = await db.execute(
            select(LLMCredential).where(
                LLMCredential.id == credential_id,
                LLMCredential.user_id == user_id,
            )
        )
        cred = result.scalar_one_or_none()
        if cred is None:
            raise CredentialNotFoundError(
                f"Credential '{credential_id}' does not exist or is not owned by user."
            )

        now = datetime.now(UTC)
        pref_result = await db.execute(
            select(LLMPreference).where(LLMPreference.user_id == user_id)
        )
        pref = pref_result.scalar_one_or_none()

        if pref is not None:
            pref.credential_id = credential_id
            pref.provider = cred.provider
            pref.model_id = model_id.strip()
            pref.updated_at = now
        else:
            pref = LLMPreference(
                user_id=user_id,
                credential_id=credential_id,
                provider=cred.provider,
                model_id=model_id.strip(),
            )
            db.add(pref)

        await db.flush()
        await db.refresh(pref)
        return pref

    set_preference = update_preference

    @classmethod
    async def list_usage(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[LLMUsage]:
        """Retrieve historical LLM gateway usage records for the user."""
        result = await db.execute(
            select(LLMUsage)
            .where(LLMUsage.user_id == user_id)
            .order_by(desc(LLMUsage.created_at))
            .limit(limit)
            .offset(offset)
        )
        return list(result.scalars().all())
