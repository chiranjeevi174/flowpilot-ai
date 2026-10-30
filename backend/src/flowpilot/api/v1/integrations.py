"""FastAPI router endpoints for external application integrations, OAuth 2.0, and action audits."""

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.api.dependencies import get_current_user
from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.db.session import get_db
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthError,
)
from flowpilot.integrations.security import OAuthStateError
from flowpilot.models.user import User
from flowpilot.schemas.integrations import (
    AppConnectionOverviewItem,
    ExternalActionResponse,
    IntegrationAuthorizeResponse,
    IntegrationConnectionResponse,
    IntegrationConnectionTestResponse,
    ProviderInfoResponse,
    ProviderSetupGuideResponse,
    SaveCustomCredentialsRequest,
    WhatsAppStatusResponse,
)
from flowpilot.services.integrations import (
    IntegrationNotFoundError,
    IntegrationService,
    IntegrationServiceError,
)

logger = get_logger("api.v1.integrations")
settings = get_settings()

router = APIRouter(prefix="/integrations", tags=["External Integrations"])


@router.get(
    "/overview",
    response_model=list[AppConnectionOverviewItem],
    status_code=status.HTTP_200_OK,
    summary="App Connections provider overview",
    description=(
        "Aggregates configuration status, connected accounts, and credentials for "
        "Gmail, Sheets, Slack, and WhatsApp."
    ),
)
async def get_app_connections_overview(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[AppConnectionOverviewItem]:
    """Retrieve cards overview for the App Connections dashboard."""
    return await IntegrationService.get_app_connections_overview(db, current_user.id)


@router.get(
    "/guides",
    response_model=list[ProviderSetupGuideResponse],
    status_code=status.HTTP_200_OK,
    summary="Retrieve setup guides for all providers",
    description="Returns interactive step-by-step instructions, portal links, and callback URLs.",
)
async def get_all_setup_guides(
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[ProviderSetupGuideResponse]:
    """Return all provider setup guides."""
    return IntegrationService.get_setup_guides()


@router.get(
    "/guides/{provider}",
    response_model=ProviderSetupGuideResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve setup guide for a specific provider",
    description="Returns interactive step-by-step instructions for Google, Slack, or WhatsApp.",
)
async def get_provider_setup_guide(
    provider: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ProviderSetupGuideResponse:
    """Return setup guide for specified provider."""
    try:
        return IntegrationService.get_setup_guide(provider)
    except IntegrationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/credentials",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Save user custom application credentials",
    description="Encrypts and stores user-scoped Client ID/Secret or WhatsApp access tokens.",
)
async def save_custom_credentials(
    payload: SaveCustomCredentialsRequest,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationConnectionResponse:
    """Save custom credentials for Gmail/Sheets, Slack, or WhatsApp."""
    try:
        conn = await IntegrationService.save_custom_credentials(
            db=db,
            user_id=current_user.id,
            payload=payload,
        )
        return IntegrationConnectionResponse.from_model(conn)
    except IntegrationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/providers",
    response_model=list[ProviderInfoResponse],
    status_code=status.HTTP_200_OK,
    summary="List supported external integration providers",
    description="Returns metadata and configuration status for Gmail, Sheets, Slack, and WhatsApp.",
)
async def list_providers() -> list[ProviderInfoResponse]:
    """List supported external integrations."""
    return IntegrationService.get_supported_providers()


@router.get(
    "/whatsapp/status",
    response_model=WhatsAppStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve WhatsApp Business configuration readiness",
    description=(
        "Returns sanitized status and missing variable diagnostics without exposing secrets."
    ),
)
async def get_whatsapp_status(
    current_user: Annotated[User, Depends(get_current_user)],
) -> WhatsAppStatusResponse:
    """Retrieve WhatsApp Business deployment configuration status."""
    return IntegrationService.get_whatsapp_status()


@router.post(
    "/whatsapp/test",
    response_model=IntegrationConnectionTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Probe Meta WhatsApp Cloud API credentials and connectivity",
    description="Tests access token validity and phone number ID against Meta Graph API.",
)
async def test_whatsapp_connection(
    current_user: Annotated[User, Depends(get_current_user)],
) -> IntegrationConnectionTestResponse:
    """Probe WhatsApp Cloud API credentials."""
    return await IntegrationService.test_whatsapp_connection()


@router.get(
    "/whatsapp/webhook",
    status_code=status.HTTP_200_OK,
    summary="Meta WhatsApp webhook subscription verification (alias)",
    include_in_schema=False,
)
async def whatsapp_webhook_verification_alias(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """Forward verification challenge to canonical webhook handler."""
    from flowpilot.api.v1.webhooks import whatsapp_webhook_verification

    return await whatsapp_webhook_verification(hub_mode, hub_verify_token, hub_challenge)


@router.post(
    "/whatsapp/webhook",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound Meta WhatsApp Cloud API events (alias)",
    include_in_schema=False,
)
async def whatsapp_events_webhook_alias(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> Any:
    """Forward inbound event to canonical webhook handler."""
    from flowpilot.api.v1.webhooks import whatsapp_events_webhook

    return await whatsapp_events_webhook(request, db, x_hub_signature_256)


@router.get(
    "",
    response_model=list[IntegrationConnectionResponse],
    status_code=status.HTTP_200_OK,
    summary="List authenticated user's external connections",
    description="Returns all active external connections owned by the authenticated user.",
)
async def list_user_connections(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[IntegrationConnectionResponse]:
    """Retrieve all integration connections for the current user."""
    connections = await IntegrationService.list_user_connections(db, current_user.id)
    return [IntegrationConnectionResponse.from_model(c) for c in connections]


@router.get(
    "/actions",
    response_model=list[ExternalActionResponse],
    status_code=status.HTTP_200_OK,
    summary="List external action execution history",
    description="Retrieve audit records of actions executed on behalf of the user.",
)
async def list_external_actions(
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> list[ExternalActionResponse]:
    """Retrieve external action execution history for the current user."""
    actions, _ = await IntegrationService.list_external_actions(
        db, current_user.id, limit=limit, offset=offset
    )
    return [ExternalActionResponse.model_validate(a) for a in actions]


@router.get(
    "/{provider}/authorize",
    response_model=IntegrationAuthorizeResponse,
    status_code=status.HTTP_200_OK,
    summary="Initiate OAuth 2.0 authorization code flow",
    description="Generates provider authorization URL with PKCE and signed state token.",
)
async def authorize_integration(
    provider: str,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    service: Annotated[str | None, Query(description="Target capability")] = None,
    redirect_uri: Annotated[str | None, Query(description="Custom redirect URI")] = None,
    connection_id: Annotated[uuid.UUID | None, Query(description="Existing connection ID")] = None,
) -> IntegrationAuthorizeResponse:
    """Generate authorization URL for external OAuth provider."""
    try:
        return await IntegrationService.initiate_oauth_flow(
            user_id=current_user.id,
            provider=provider,
            service=service,
            redirect_uri=redirect_uri,
            connection_id=connection_id,
            db=db,
        )
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except IntegrationServiceError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{provider}/callback",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Handle OAuth 2.0 callback",
    description=(
        "Exchanges temporary authorization code for tokens, verifies state token, "
        "encrypts credentials, and updates connection."
    ),
)
async def oauth_callback(
    provider: str,
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    code: Annotated[str | None, Query()] = None,
    state: Annotated[str | None, Query()] = None,
    error: Annotated[str | None, Query()] = None,
) -> Any:
    """Handle OAuth 2.0 callback and persist encrypted credentials."""
    if error:
        logger.warning("OAuth callback received error from %s: %s", provider, error)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth authorization was denied or failed: {error}",
        )

    if not code or not state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required OAuth callback parameters: 'code' and 'state'.",
        )

    try:
        connection = await IntegrationService.handle_oauth_callback(
            db=db,
            provider=provider,
            code=code,
            state=state,
            error=error,
        )

        # If browser request expecting HTML navigation, redirect to frontend App Connections page
        accept_header = request.headers.get("accept", "")
        if "text/html" in accept_header:
            target_url = (
                f"{settings.FRONTEND_URL}/settings/connections"
                f"?status=success&provider={provider}&id={connection.id}"
            )
            return RedirectResponse(url=target_url, status_code=status.HTTP_302_FOUND)

        return IntegrationConnectionResponse.from_model(connection)

    except OAuthStateError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth security verification failed: {exc}",
        ) from exc
    except OAuthAuthenticationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"OAuth code exchange failed: {exc}",
        ) from exc
    except OAuthConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get(
    "/{id}",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Retrieve external connection details",
    description="Retrieve details of a specific connection with strict user ownership validation.",
)
async def get_connection(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationConnectionResponse:
    """Retrieve connection details by ID."""
    try:
        connection = await IntegrationService.get_user_connection(db, current_user.id, id)
        return IntegrationConnectionResponse.from_model(connection)
    except IntegrationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{id}/test",
    response_model=IntegrationConnectionTestResponse,
    status_code=status.HTTP_200_OK,
    summary="Verify external integration connectivity and token validity",
    description="Performs an active API call against the external provider to test credentials.",
)
async def test_connection(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationConnectionTestResponse:
    """Test connection readiness."""
    try:
        return await IntegrationService.test_connection(db, current_user.id, id)
    except IntegrationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.post(
    "/{id}/default",
    response_model=IntegrationConnectionResponse,
    status_code=status.HTTP_200_OK,
    summary="Set connection as default for its provider",
    description=(
        "Marks this connection as the primary connection used for automated workflow execution."
    ),
)
async def set_default_connection(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> IntegrationConnectionResponse:
    """Designate connection as default."""
    try:
        conn = await IntegrationService.set_default_connection(db, current_user.id, id)
        return IntegrationConnectionResponse.from_model(conn)
    except IntegrationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc


@router.delete(
    "/{id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disconnect and revoke external integration",
    description="Safely revokes tokens with the provider and deletes the connection record.",
)
async def disconnect_connection(
    id: uuid.UUID,
    current_user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Disconnect and delete integration connection."""
    try:
        await IntegrationService.disconnect_connection(db, current_user.id, id)
    except IntegrationNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
