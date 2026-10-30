"""Multi-LLM Gateway and BYOK endpoints."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.db.session import get_db
from flowpilot.llm.gateway import (
    CredentialNotFoundError as GatewayCredNotFoundError,
)
from flowpilot.llm.gateway import (
    NoPreferenceConfiguredError,
    gateway,
)
from flowpilot.llm.providers import (
    LLMProviderError,
    ModelInfo,
    ProviderAuthenticationError,
    ProviderQuotaExceededError,
    ProviderRateLimitError,
    UnsupportedProviderError,
)
from flowpilot.models.user import User
from flowpilot.schemas.auth import MessageResponse
from flowpilot.schemas.llm import (
    ConnectionTestResponse,
    CredentialCreateRequest,
    CredentialResponse,
    CredentialUpdateRequest,
    GenerationRequest,
    GenerationResponse,
    PreferenceRequest,
    PreferenceResponse,
    ProviderResponse,
    UsageRecordResponse,
)
from flowpilot.services.llm import (
    CredentialNotFoundError,
    DuplicateCredentialError,
    LLMService,
)

router = APIRouter(prefix="/llm", tags=["LLM Gateway & BYOK"])


@router.get(
    "/providers",
    response_model=list[ProviderResponse],
    status_code=status.HTTP_200_OK,
    summary="List supported LLM providers",
    description="Returns the catalog of LLM providers natively supported by FlowPilot AI.",
)
async def list_providers() -> list[ProviderResponse]:
    """Retrieve supported LLM providers."""
    return [ProviderResponse(**p) for p in LLMService.get_supported_providers()]


@router.post(
    "/credentials",
    response_model=CredentialResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Connect an LLM provider (BYOK)",
    description=(
        "Submits a user-provided API key, validates connection with the provider, "
        "encrypts the secret, and persists the credential."
    ),
)
async def connect_credential(
    data: CredentialCreateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Validate and connect a new personal LLM API key."""
    try:
        cred = await LLMService.connect_credential(
            db=db,
            user_id=current_user.id,
            provider_name=data.provider,
            api_key=data.api_key,
        )
        return CredentialResponse.model_validate(cred)
    except DuplicateCredentialError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except UnsupportedProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider credential verification failed: {exc!s}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider connection error: {exc!s}",
        ) from exc


@router.get(
    "/credentials",
    response_model=list[CredentialResponse],
    status_code=status.HTTP_200_OK,
    summary="List connected credentials",
    description=(
        "Returns all LLM credentials connected by the authenticated user with masked fingerprints."
    ),
)
async def list_credentials(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[CredentialResponse]:
    """List connected LLM credentials for the authenticated user."""
    creds = await LLMService.list_credentials(db, current_user.id)
    return [CredentialResponse.model_validate(c) for c in creds]


@router.post(
    "/credentials/{credential_id}/test",
    response_model=ConnectionTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Test provider connection",
    description="Performs an on-demand non-billable connection test for an existing credential.",
)
async def test_credential(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConnectionTestResponse:
    """Test connection using stored credential."""
    try:
        return await LLMService.test_credential(db, current_user.id, credential_id)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Authentication test failed: {exc!s}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider test error: {exc!s}",
        ) from exc


@router.put(
    "/credentials/{credential_id}",
    response_model=CredentialResponse,
    status_code=status.HTTP_200_OK,
    summary="Replace API key",
    description="Validates and updates an existing credential with a new secret API key.",
)
async def replace_credential(
    credential_id: uuid.UUID,
    data: CredentialUpdateRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> CredentialResponse:
    """Replace API key for a connected credential."""
    try:
        updated = await LLMService.replace_credential(
            db=db,
            user_id=current_user.id,
            credential_id=credential_id,
            new_api_key=data.api_key,
        )
        return CredentialResponse.model_validate(updated)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Replacement key verification failed: {exc!s}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider error: {exc!s}",
        ) from exc


@router.delete(
    "/credentials/{credential_id}",
    response_model=MessageResponse,
    status_code=status.HTTP_200_OK,
    summary="Delete credential",
    description=(
        "Deletes a connected credential and safely invalidates any associated default preferences."
    ),
)
async def delete_credential(
    credential_id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MessageResponse:
    """Delete credential record."""
    try:
        await LLMService.delete_credential(db, current_user.id, credential_id)
        return MessageResponse(message="Credential successfully deleted.")
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.get(
    "/models",
    response_model=list[ModelInfo],
    status_code=status.HTTP_200_OK,
    summary="Discover available models",
    description=(
        "Discovers available text generation models using authenticated provider connections."
    ),
)
async def list_models(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    provider: str | None = Query(default=None, description="Optional provider filter"),
) -> list[ModelInfo]:
    """Dynamically discover available models."""
    try:
        return await LLMService.list_models(db, current_user.id, provider)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProviderRateLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Provider rate limit exceeded: {exc!s}",
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Provider authentication error: {exc!s}",
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Provider model discovery error: {exc!s}",
        ) from exc


@router.get(
    "/preferences",
    response_model=PreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get default LLM preference",
    description="Returns the authenticated user's active default LLM provider and model.",
)
async def get_preference(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreferenceResponse:
    """Get active default model configuration."""
    pref = await LLMService.get_preference(db, current_user.id)
    if pref is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No default LLM preference configured.",
        )
    return PreferenceResponse.model_validate(pref)


@router.put(
    "/preferences",
    response_model=PreferenceResponse,
    status_code=status.HTTP_200_OK,
    summary="Update default LLM preference",
    description="Sets the user's active default LLM provider and model for workflow execution.",
)
async def update_preference(
    data: PreferenceRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PreferenceResponse:
    """Update active default model configuration."""
    try:
        updated = await LLMService.update_preference(
            db=db,
            user_id=current_user.id,
            credential_id=data.credential_id,
            model_id=data.model_id,
        )
        return PreferenceResponse.model_validate(updated)
    except CredentialNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/generate",
    response_model=GenerationResponse,
    status_code=status.HTTP_200_OK,
    summary="Generate text via Unified LLM Gateway",
    description=(
        "Executes a text generation request through the user's connected BYOK credentials "
        "and tracks token consumption."
    ),
)
async def generate_text(
    data: GenerationRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GenerationResponse:
    """Invoke the Unified LLM Gateway."""
    try:
        result = await gateway.generate(
            db=db,
            user_id=current_user.id,
            messages=data.messages,
            model=data.model,
            provider=data.provider,
            temperature=data.temperature,
            max_tokens=data.max_tokens,
        )
        return GenerationResponse(
            content=result.content,
            model=result.model,
            provider=result.provider,
            usage=result.usage,
            estimated_cost=result.estimated_cost,
            currency=result.currency,
            latency_ms=result.latency_ms,
        )
    except NoPreferenceConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except (GatewayCredNotFoundError, CredentialNotFoundError) as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ProviderAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Provider authentication failed: {exc!s}",
        ) from exc
    except (ProviderRateLimitError, ProviderQuotaExceededError) as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except LLMProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"LLM provider error: {exc!s}",
        ) from exc


@router.get(
    "/usage",
    response_model=list[UsageRecordResponse],
    status_code=status.HTTP_200_OK,
    summary="Get LLM usage history",
    description=(
        "Returns the historical token consumption and estimated cost logs "
        "for the authenticated user."
    ),
)
async def get_usage_history(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[UsageRecordResponse]:
    """Retrieve historical LLM gateway usage records."""
    records = await LLMService.list_usage(db, current_user.id, limit=limit, offset=offset)
    return [UsageRecordResponse.model_validate(r) for r in records]
