"""Pydantic schemas for external integration connections, OAuth flows, and action telemetry."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ProviderInfoResponse(BaseModel):
    """Metadata regarding a supported external integration provider."""

    id: str = Field(..., description="Provider unique slug, e.g. 'google', 'slack', 'whatsapp'")
    name: str = Field(..., description="Display name of external application")
    category: str = Field(
        ..., description="Application category, e.g. 'communication', 'productivity'"
    )
    supported_services: list[str] = Field(
        default_factory=list, description="Sub-services offered by this provider"
    )
    supported_scopes: list[str] = Field(
        default_factory=list, description="OAuth scopes requested by this integration"
    )
    is_configured: bool = Field(..., description="Whether deployment credentials are configured")
    auth_type: str = Field(
        default="oauth2",
        description="Authentication paradigm: 'oauth2' or 'system_credentials'",
    )
    missing_fields: list[str] = Field(
        default_factory=list,
        description="Missing environment variable names if not fully configured",
    )


class WhatsAppStatusResponse(BaseModel):
    """Configuration readiness and sanitized telemetry for WhatsApp Cloud API."""

    is_configured: bool = Field(
        ..., description="Whether required WhatsApp credentials are configured"
    )
    phone_number_id_configured: bool = Field(..., description="Whether Phone Number ID is set")
    masked_phone_number_id: str | None = Field(default=None, description="Masked phone number ID")
    business_account_id_configured: bool = Field(..., description="Whether WABA ID is set")
    masked_business_account_id: str | None = Field(default=None, description="Masked WABA ID")
    graph_api_version: str = Field(..., description="Configured Meta Graph API version")
    webhook_verify_token_configured: bool = Field(
        ..., description="Whether webhook verify token is set"
    )
    app_secret_configured: bool = Field(
        ..., description="Whether app secret is set for HMAC verification"
    )
    missing_fields: list[str] = Field(
        default_factory=list, description="List of missing environment variable names"
    )
    supported_capabilities: list[str] = Field(
        default_factory=lambda: ["whatsapp_send_message", "whatsapp_send_template"],
        description="Supported agent capabilities",
    )


class IntegrationConnectionResponse(BaseModel):
    """Public representation of an authorized external application connection."""

    id: uuid.UUID = Field(..., description="Unique connection identifier")
    user_id: uuid.UUID = Field(..., description="Owner user ID")
    provider: str = Field(..., description="Provider name ('google', 'slack', 'whatsapp')")
    service: str | None = Field(default=None, description="Sub-service identifier")
    config_method: str = Field(default="custom_credentials", description="Configuration method")
    client_id: str | None = Field(default=None, description="Client ID or App ID entered by user")
    has_client_secret: bool = Field(default=False, description="Whether client secret is stored")
    has_access_token: bool = Field(default=False, description="Whether access token is stored")
    is_default: bool = Field(default=True, description="Whether this is the default connection")
    external_account_id: str | None = Field(
        default=None, description="External identity, e.g. email or workspace ID"
    )
    external_account_name: str | None = Field(
        default=None, description="Display name of connected account"
    )
    granted_scopes: list[str] = Field(default_factory=list, description="Authorized OAuth scopes")
    token_expires_at: datetime | None = Field(
        default=None, description="Expiration timestamp for current access token"
    )
    status: str = Field(
        ...,
        description=(
            "Operational status: active, configured, authorization_required, "
            "expired, revoked, error, restricted"
        ),
    )
    last_verified_at: datetime | None = Field(
        default=None, description="Last successful verification check"
    )
    metadata_json: dict[str, Any] = Field(
        default_factory=dict, description="Safe external metadata (team info, bot IDs)"
    )
    created_at: datetime = Field(..., description="Connection creation timestamp")
    updated_at: datetime = Field(..., description="Last connection update timestamp")

    model_config = {"from_attributes": True}

    @classmethod
    def from_model(cls, conn: Any) -> "IntegrationConnectionResponse":
        """Convert SQLAlchemy model to response, sanitizing secrets."""
        meta = dict(conn.metadata_json or {})
        # Never expose encrypted app secret ciphertext in responses
        has_app_secret = bool(meta.pop("encrypted_app_secret", None))
        meta["has_app_secret"] = has_app_secret

        return cls(
            id=conn.id,
            user_id=conn.user_id,
            provider=conn.provider,
            service=conn.service,
            config_method=getattr(conn, "config_method", "custom_credentials")
            or "custom_credentials",
            client_id=getattr(conn, "client_id", None),
            has_client_secret=bool(getattr(conn, "encrypted_client_secret", None)),
            has_access_token=bool(getattr(conn, "encrypted_access_token", None)),
            is_default=getattr(conn, "is_default", True),
            external_account_id=conn.external_account_id,
            external_account_name=conn.external_account_name,
            granted_scopes=conn.granted_scopes or [],
            token_expires_at=conn.token_expires_at,
            status=conn.status,
            last_verified_at=conn.last_verified_at,
            metadata_json=meta,
            created_at=conn.created_at,
            updated_at=conn.updated_at,
        )


class SaveCustomCredentialsRequest(BaseModel):
    """Payload to create or update user-scoped custom app integration credentials."""

    provider: str = Field(..., description="Target provider: 'google', 'slack', 'whatsapp'")
    service: str | None = Field(
        default=None, description="Specific service: 'gmail', 'sheets', 'slack', 'whatsapp'"
    )
    client_id: str | None = Field(default=None, description="Custom OAuth Client ID or App ID")
    client_secret: str | None = Field(
        default=None, description="Custom OAuth Client Secret or App Secret"
    )
    access_token: str | None = Field(default=None, description="Direct API Access Token (WhatsApp)")
    phone_number_id: str | None = Field(default=None, description="WhatsApp Phone Number ID")
    business_account_id: str | None = Field(
        default=None, description="WhatsApp Business Account ID (WABA)"
    )
    app_secret: str | None = Field(
        default=None, description="WhatsApp Meta App Secret for webhooks"
    )
    webhook_verify_token: str | None = Field(
        default=None, description="WhatsApp Webhook Verify Token"
    )
    graph_api_version: str = Field(default="v21.0", description="Meta Graph API Version")
    is_default: bool = Field(
        default=True, description="Whether to make this the primary connection"
    )


class ProviderSetupGuideStep(BaseModel):
    """Step in an interactive setup guide."""

    step_number: int
    title: str
    instructions: str
    required_info: list[str] = Field(default_factory=list)
    portal_name: str
    portal_url: str
    callback_url: str | None = None
    tip: str | None = None


class ProviderSetupGuideResponse(BaseModel):
    """Complete interactive setup guide for a provider."""

    provider: str
    name: str
    description: str
    portal_name: str
    portal_url: str
    callback_url: str | None = None
    webhook_url: str | None = None
    supported_methods: list[str] = Field(default_factory=lambda: ["custom_credentials", "oauth"])
    required_fields: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[ProviderSetupGuideStep] = Field(default_factory=list)


class AppConnectionOverviewItem(BaseModel):
    """Card overview of an integration provider for the App Connections module."""

    id: str
    name: str
    category: str
    icon: str
    description: str
    status: str
    connection_id: uuid.UUID | None = None
    connected_account: str | None = None
    config_method: str | None = None
    is_default: bool = True
    has_credentials: bool = False
    has_access_token: bool = False
    client_id: str | None = None
    client_id_preview: str | None = None
    has_client_secret: bool = False
    phone_number_id: str | None = None
    business_account_id: str | None = None
    graph_api_version: str | None = "v21.0"
    has_app_secret: bool = False
    last_verified_at: datetime | None = None
    updated_at: datetime | None = None
    supported_methods: list[str] = Field(default_factory=list)
    platform_oauth_available: bool = False
    services: list[str] = Field(default_factory=list)
    callback_url: str | None = None


class SetDefaultConnectionRequest(BaseModel):
    """Payload to select default connection for a provider."""

    connection_id: uuid.UUID


class IntegrationAuthorizeResponse(BaseModel):
    """Authorization initiation payload with URL for browser redirection."""

    provider: str = Field(..., description="Target integration provider")
    authorization_url: str = Field(..., description="URL to redirect user for OAuth consent")
    state: str = Field(..., description="Cryptographically signed CSRF state token")


class IntegrationConnectionTestResponse(BaseModel):
    """Result of active connectivity and authentication probe on a connection."""

    id: uuid.UUID = Field(..., description="Connection ID")
    ok: bool = Field(..., description="Whether connection is valid and responsive")
    provider: str = Field(..., description="Provider name")
    status: str = Field(..., description="Current connection status")
    message: str = Field(..., description="Detailed diagnostic or error message")
    external_account_id: str | None = Field(default=None, description="Verified account ID")
    tested_at: datetime = Field(..., description="UTC timestamp of the connectivity test")


class ExternalActionResponse(BaseModel):
    """Audit entry of an external API operation executed on behalf of a user."""

    id: uuid.UUID = Field(..., description="Action ID")
    user_id: uuid.UUID = Field(..., description="Owner user ID")
    run_id: uuid.UUID | None = Field(default=None, description="Associated agent run ID")
    connection_id: uuid.UUID | None = Field(default=None, description="Integration connection used")
    operation: str = Field(..., description="Executed operation name")
    parameter_digest: str = Field(..., description="SHA-256 digest of parameters")
    idempotency_key: str = Field(..., description="Unique idempotency key")
    status: str = Field(..., description="Lifecycle status")
    approval_reference: str | None = Field(
        default=None, description="Human approval reference token if sensitive"
    )
    provider_action_id: str | None = Field(
        default=None, description="External entity ID (e.g., message_id)"
    )
    provider_response: dict[str, Any] = Field(
        default_factory=dict, description="Sanitized response payload"
    )
    error_message: str | None = Field(default=None, description="Error details if failed")
    created_at: datetime = Field(..., description="Creation timestamp")
    completed_at: datetime | None = Field(default=None, description="Completion timestamp")

    model_config = {"from_attributes": True}
