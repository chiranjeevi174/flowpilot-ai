"""Integration service managing connections, OAuth handshakes, and diagnostic probes."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.integrations.google.oauth import GoogleOAuth
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthError,
    OAuthTokenBundle,
    OAuthTokenManager,
)
from flowpilot.integrations.security import (
    decrypt_oauth_token,
    encrypt_oauth_token,
    validate_oauth_state,
)
from flowpilot.integrations.slack.oauth import SlackOAuth
from flowpilot.models.external_action import ExternalAction
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)
from flowpilot.schemas.integrations import (
    AppConnectionOverviewItem,
    IntegrationAuthorizeResponse,
    IntegrationConnectionTestResponse,
    ProviderInfoResponse,
    ProviderSetupGuideResponse,
    ProviderSetupGuideStep,
    SaveCustomCredentialsRequest,
    WhatsAppStatusResponse,
)

logger = get_logger("services.integrations")
settings = get_settings()


class IntegrationServiceError(Exception):
    """Base exception for integration service errors."""


class IntegrationNotFoundError(IntegrationServiceError):
    """Raised when the requested integration connection is not found or owned by another user."""


class IntegrationService:
    """Service handling OAuth callbacks, token storage, and connection verification."""

    @classmethod
    def get_supported_providers(cls) -> list[ProviderInfoResponse]:
        """List supported external integrations and their deployment readiness."""
        google_missing: list[str] = []
        if not settings.GOOGLE_CLIENT_ID:
            google_missing.append("GOOGLE_CLIENT_ID")
        if not settings.GOOGLE_CLIENT_SECRET:
            google_missing.append("GOOGLE_CLIENT_SECRET")
        google_configured = len(google_missing) == 0

        slack_missing: list[str] = []
        if not settings.SLACK_CLIENT_ID:
            slack_missing.append("SLACK_CLIENT_ID")
        if not settings.SLACK_CLIENT_SECRET:
            slack_missing.append("SLACK_CLIENT_SECRET")
        slack_configured = len(slack_missing) == 0

        whatsapp_missing = settings.whatsapp_missing_fields
        whatsapp_configured = settings.is_whatsapp_configured

        return [
            ProviderInfoResponse(
                id="google",
                name="Google (Gmail & Sheets)",
                category="productivity",
                supported_services=["gmail", "sheets"],
                supported_scopes=[
                    "https://www.googleapis.com/auth/gmail.readonly",
                    "https://www.googleapis.com/auth/gmail.compose",
                    "https://www.googleapis.com/auth/gmail.send",
                    "https://www.googleapis.com/auth/spreadsheets",
                ],
                is_configured=google_configured,
                auth_type="oauth2",
                missing_fields=google_missing,
            ),
            ProviderInfoResponse(
                id="slack",
                name="Slack",
                category="communication",
                supported_services=["slack"],
                supported_scopes=[
                    "channels:read",
                    "groups:read",
                    "chat:write",
                    "chat:write.public",
                    "team:read",
                ],
                is_configured=slack_configured,
                auth_type="oauth2",
                missing_fields=slack_missing,
            ),
            ProviderInfoResponse(
                id="whatsapp",
                name="WhatsApp Business",
                category="communication",
                supported_services=["whatsapp"],
                supported_scopes=[
                    "whatsapp_business_messaging",
                ],
                is_configured=whatsapp_configured,
                auth_type="system_credentials",
                missing_fields=whatsapp_missing,
            ),
        ]

    @classmethod
    def get_setup_guide(cls, provider: str) -> ProviderSetupGuideResponse:
        """Return interactive step-by-step setup guide for specified provider."""
        norm = provider.lower().strip()
        backend_url = settings.FRONTEND_URL.replace(":3000", ":8000")
        google_cb = (
            settings.GOOGLE_REDIRECT_URI or f"{backend_url}/api/v1/integrations/google/callback"
        )
        slack_cb = (
            settings.SLACK_REDIRECT_URI or f"{backend_url}/api/v1/integrations/slack/callback"
        )
        whatsapp_webhook = f"{backend_url}/api/v1/webhooks/whatsapp"

        if norm in ("google", "gmail", "sheets"):
            return ProviderSetupGuideResponse(
                provider="google",
                name="Google Workspace (Gmail & Google Sheets)",
                description=(
                    "Authorize FlowPilot AI to automate Gmail messaging, message drafting, "
                    "and Google Sheets spreadsheet data operations."
                ),
                portal_name="Google Cloud Console",
                portal_url="https://console.cloud.google.com/",
                callback_url=google_cb,
                supported_methods=["custom_credentials", "oauth"],
                required_fields=[
                    {
                        "name": "client_id",
                        "label": "OAuth Client ID",
                        "type": "text",
                        "placeholder": "123456789-abcdefg.apps.googleusercontent.com",
                        "is_secret": False,
                        "required": True,
                        "help": "Identifies your application created in Google Cloud Console.",
                    },
                    {
                        "name": "client_secret",
                        "label": "OAuth Client Secret",
                        "type": "password",
                        "placeholder": "GOCSPX-xxxxxxxxxxxxxxxxxxxx",
                        "is_secret": True,
                        "required": True,
                        "help": "Confidential secret generated by Google Cloud for authorization.",
                    },
                ],
                steps=[
                    ProviderSetupGuideStep(
                        step_number=1,
                        title="Create or Select a Google Cloud Project",
                        instructions=(
                            "Open Google Cloud Console and select or create a project dedicated "
                            "to FlowPilot automations."
                        ),
                        required_info=["Project Name"],
                        portal_name="Google Cloud Console",
                        portal_url="https://console.cloud.google.com/projectcreate",
                        tip="A single Google Cloud project hosts credentials for Gmail & Sheets.",
                    ),
                    ProviderSetupGuideStep(
                        step_number=2,
                        title="Enable Gmail & Google Sheets APIs",
                        instructions=(
                            "Navigate to APIs & Services > Library. Search for 'Gmail API' and "
                            "click Enable. Then search for 'Google Sheets API' and click Enable."
                        ),
                        required_info=["Gmail API", "Google Sheets API"],
                        portal_name="API Library",
                        portal_url="https://console.cloud.google.com/apis/library",
                    ),
                    ProviderSetupGuideStep(
                        step_number=3,
                        title="Configure OAuth Consent Screen",
                        instructions=(
                            "Under APIs & Services > OAuth consent screen, choose 'External'. Set "
                            "App Name to 'FlowPilot AI', add your support email, and add your "
                            "Google account under 'Test users'."
                        ),
                        required_info=["User Type: External", "Test Users"],
                        portal_name="OAuth Consent Screen",
                        portal_url="https://console.cloud.google.com/apis/credentials/consent",
                        tip="In testing mode, only emails added as 'Test Users' can authorize.",
                    ),
                    ProviderSetupGuideStep(
                        step_number=4,
                        title="Create OAuth Client Credentials",
                        instructions=(
                            "Go to APIs & Services > Credentials > Create Credentials > OAuth "
                            "client ID. Select 'Web application' as the Application type."
                        ),
                        required_info=["Application type: Web application"],
                        portal_name="Credentials",
                        portal_url="https://console.cloud.google.com/apis/credentials",
                    ),
                    ProviderSetupGuideStep(
                        step_number=5,
                        title="Add Authorized Redirect URI",
                        instructions=(
                            "In the 'Authorized redirect URIs' section, paste the exact callback "
                            "URL displayed below. Click Save."
                        ),
                        required_info=["Authorized Redirect URI"],
                        portal_name="Credentials",
                        portal_url="https://console.cloud.google.com/apis/credentials",
                        callback_url=google_cb,
                    ),
                    ProviderSetupGuideStep(
                        step_number=6,
                        title="Save Credentials & Authorize",
                        instructions=(
                            "Copy your Client ID and Client Secret, paste them into "
                            "FlowPilot's credential form, click 'Save Credentials', then "
                            "click 'Connect Google'."
                        ),
                        required_info=["Client ID", "Client Secret"],
                        portal_name="FlowPilot App Connections",
                        portal_url="https://console.cloud.google.com/apis/credentials",
                    ),
                ],
            )
        elif norm == "slack":
            return ProviderSetupGuideResponse(
                provider="slack",
                name="Slack",
                description=(
                    "Connect a Slack workspace to allow automated channel updates, alerts, "
                    "and workflow notifications."
                ),
                portal_name="Slack API Apps Portal",
                portal_url="https://api.slack.com/apps",
                callback_url=slack_cb,
                supported_methods=["custom_credentials", "oauth"],
                required_fields=[
                    {
                        "name": "client_id",
                        "label": "Slack Client ID",
                        "type": "text",
                        "placeholder": "123456789.987654321",
                        "is_secret": False,
                        "required": True,
                        "help": (
                            "Found under Basic Information > App Credentials in your Slack app."
                        ),
                    },
                    {
                        "name": "client_secret",
                        "label": "Slack Client Secret",
                        "type": "password",
                        "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        "is_secret": True,
                        "required": True,
                        "help": "Confidential signing secret for exchanging Slack bot tokens.",
                    },
                ],
                steps=[
                    ProviderSetupGuideStep(
                        step_number=1,
                        title="Create a Slack App",
                        instructions=(
                            "Navigate to the Slack API portal and click 'Create New App' > "
                            "'From scratch'. Enter 'FlowPilot AI' and select your target workspace."
                        ),
                        required_info=["App Name", "Development Workspace"],
                        portal_name="Slack Apps",
                        portal_url="https://api.slack.com/apps",
                    ),
                    ProviderSetupGuideStep(
                        step_number=2,
                        title="Locate Client ID and Client Secret",
                        instructions=(
                            "In the left sidebar, click 'Basic Information'. Scroll down to "
                            "'App Credentials' to locate your Client ID and Client Secret."
                        ),
                        required_info=["Client ID", "Client Secret"],
                        portal_name="Basic Information",
                        portal_url="https://api.slack.com/apps",
                    ),
                    ProviderSetupGuideStep(
                        step_number=3,
                        title="Configure Redirect URL",
                        instructions=(
                            "In the left sidebar, click 'OAuth & Permissions'. Under 'Redirect "
                            "URLs', click 'Add New Redirect URL', paste FlowPilot's callback URL, "
                            "and click 'Save URLs'."
                        ),
                        required_info=["Redirect URL"],
                        portal_name="OAuth & Permissions",
                        portal_url="https://api.slack.com/apps",
                        callback_url=slack_cb,
                    ),
                    ProviderSetupGuideStep(
                        step_number=4,
                        title="Configure Bot Token Scopes",
                        instructions=(
                            "Scroll down to 'Scopes' > 'Bot Token Scopes'. Add: chat:write, "
                            "chat:write.public, channels:read, groups:read, and team:read."
                        ),
                        required_info=["Bot Scopes"],
                        portal_name="OAuth & Permissions",
                        portal_url="https://api.slack.com/apps",
                    ),
                    ProviderSetupGuideStep(
                        step_number=5,
                        title="Save & Authorize FlowPilot",
                        instructions=(
                            "Enter your Client ID and Client Secret into FlowPilot, click 'Save "
                            "Credentials', then click 'Connect Slack' to install the app."
                        ),
                        required_info=["Authorize App"],
                        portal_name="FlowPilot App Connections",
                        portal_url="https://api.slack.com/apps",
                    ),
                ],
            )
        elif norm == "whatsapp":
            return ProviderSetupGuideResponse(
                provider="whatsapp",
                name="WhatsApp Business (Meta Cloud API)",
                description=(
                    "Send template and direct messages via Meta's official WhatsApp Business "
                    "Cloud API."
                ),
                portal_name="Meta for Developers",
                portal_url="https://developers.facebook.com/apps/",
                webhook_url=whatsapp_webhook,
                supported_methods=["custom_credentials"],
                required_fields=[
                    {
                        "name": "access_token",
                        "label": "Meta Access Token",
                        "type": "password",
                        "placeholder": "EAAG...",
                        "is_secret": True,
                        "required": True,
                        "help": (
                            "System user token or temporary test token with "
                            "whatsapp_business_messaging permission."
                        ),
                    },
                    {
                        "name": "phone_number_id",
                        "label": "Phone Number ID",
                        "type": "text",
                        "placeholder": "104829104812345",
                        "is_secret": False,
                        "required": True,
                        "help": (
                            "Identifies the WhatsApp Cloud API sender in your Meta app under "
                            "WhatsApp > API Setup."
                        ),
                    },
                    {
                        "name": "business_account_id",
                        "label": "WhatsApp Business Account ID (WABA)",
                        "type": "text",
                        "placeholder": "102938475612345",
                        "is_secret": False,
                        "required": False,
                        "help": (
                            "Found in WhatsApp > API Setup. Required for webhook subscription "
                            "synchronization."
                        ),
                    },
                    {
                        "name": "app_secret",
                        "label": "Meta App Secret",
                        "type": "password",
                        "placeholder": "xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
                        "is_secret": True,
                        "required": False,
                        "help": (
                            "Used by FlowPilot to cryptographically verify incoming Meta "
                            "delivery-status webhooks (HMAC-SHA256)."
                        ),
                    },
                    {
                        "name": "webhook_verify_token",
                        "label": "Webhook Verify Token",
                        "type": "text",
                        "placeholder": "flowpilot_webhook_verify_secret",
                        "is_secret": False,
                        "required": False,
                        "help": (
                            "Custom token entered into Meta Webhook Configuration for "
                            "challenge validation."
                        ),
                    },
                ],
                steps=[
                    ProviderSetupGuideStep(
                        step_number=1,
                        title="Create a Meta Developer App",
                        instructions=(
                            "Go to Meta for Developers. Click 'Create App', choose 'Business' or "
                            "'Other', and add the 'WhatsApp' capability to your application."
                        ),
                        required_info=["Meta Developer App"],
                        portal_name="Meta Developers",
                        portal_url="https://developers.facebook.com/apps/",
                    ),
                    ProviderSetupGuideStep(
                        step_number=2,
                        title="Locate API Setup & Sender Credentials",
                        instructions=(
                            "Under WhatsApp > API Setup, locate your 'Phone Number ID' and "
                            "'WhatsApp Business Account ID'. For testing, Meta provides a free "
                            "test sender."
                        ),
                        required_info=["Phone Number ID", "WABA ID"],
                        portal_name="WhatsApp API Setup",
                        portal_url="https://developers.facebook.com/apps/",
                    ),
                    ProviderSetupGuideStep(
                        step_number=3,
                        title="Obtain a Meta Access Token",
                        instructions=(
                            "For quick testing, copy the Temporary Access Token. For production, "
                            "create a System User in Meta Business Suite > Users > System Users, "
                            "assign your WhatsApp account with 'whatsapp_business_messaging' "
                            "permission, and generate a permanent token."
                        ),
                        required_info=["System User Token"],
                        portal_name="Meta Business Suite",
                        portal_url="https://business.facebook.com/settings/system-users",
                        tip=(
                            "Temporary tokens expire in 24 hours. Production requires a "
                            "System User token."
                        ),
                    ),
                    ProviderSetupGuideStep(
                        step_number=4,
                        title="Configure Webhooks (Optional for Delivery Tracking)",
                        instructions=(
                            "Under WhatsApp > Configuration, click 'Edit' next to Callback URL. "
                            "Enter FlowPilot's Webhook URL and a Verification Token. Subscribe "
                            "to the 'messages' field."
                        ),
                        required_info=["Callback URL", "Verify Token"],
                        portal_name="WhatsApp Configuration",
                        portal_url="https://developers.facebook.com/apps/",
                        callback_url=whatsapp_webhook,
                    ),
                    ProviderSetupGuideStep(
                        step_number=5,
                        title="Save & Test Connection",
                        instructions=(
                            "Enter your Phone Number ID and Access Token into FlowPilot, then "
                            "click 'Save & Test Connection' to verify connectivity."
                        ),
                        required_info=["Verify Sender"],
                        portal_name="FlowPilot App Connections",
                        portal_url="https://developers.facebook.com/apps/",
                    ),
                ],
            )
        else:
            raise IntegrationServiceError(f"No setup guide found for provider: {provider}")

    @classmethod
    def get_setup_guides(cls) -> list[ProviderSetupGuideResponse]:
        """Return setup guides for all supported providers."""
        return [
            cls.get_setup_guide("google"),
            cls.get_setup_guide("slack"),
            cls.get_setup_guide("whatsapp"),
        ]

    @classmethod
    async def list_user_connections(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[IntegrationConnection]:
        """List all external connections belonging strictly to the authenticated user."""
        stmt = (
            select(IntegrationConnection)
            .where(IntegrationConnection.user_id == user_id)
            .order_by(IntegrationConnection.created_at.desc())
        )
        result = await db.scalars(stmt)
        return list(result.all())

    @classmethod
    async def get_user_connection(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> IntegrationConnection:
        """Fetch a specific connection, enforcing strict user ownership."""
        stmt = select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.user_id == user_id,
        )
        connection = await db.scalar(stmt)
        if not connection:
            raise IntegrationNotFoundError(
                f"Connection '{connection_id}' not found or access denied."
            )
        return connection

    @classmethod
    async def get_app_connections_overview(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
    ) -> list[AppConnectionOverviewItem]:
        """Aggregate configuration & connection status for Gmail, Sheets, Slack, WhatsApp."""
        user_conns = await cls.list_user_connections(db, user_id)
        now = datetime.now(UTC)

        backend_url = settings.FRONTEND_URL.replace(":3000", ":8000")
        google_cb = (
            settings.GOOGLE_REDIRECT_URI or f"{backend_url}/api/v1/integrations/google/callback"
        )
        slack_cb = (
            settings.SLACK_REDIRECT_URI or f"{backend_url}/api/v1/integrations/slack/callback"
        )
        whatsapp_webhook = f"{backend_url}/api/v1/webhooks/whatsapp"

        # Organize user connections by provider
        google_conns = [c for c in user_conns if c.provider == "google"]
        slack_conns = [c for c in user_conns if c.provider == "slack"]
        whatsapp_conns = [c for c in user_conns if c.provider == "whatsapp"]

        # Default or primary connection per provider
        google_conn = next(
            (c for c in google_conns if c.is_default),
            google_conns[0] if google_conns else None,
        )
        slack_conn = next(
            (c for c in slack_conns if c.is_default),
            slack_conns[0] if slack_conns else None,
        )
        whatsapp_conn = next(
            (c for c in whatsapp_conns if c.is_default),
            whatsapp_conns[0] if whatsapp_conns else None,
        )

        def resolve_status(conn: IntegrationConnection | None, provider_id: str) -> str:
            if not conn:
                return "not_configured"
            if conn.status == ConnectionStatus.ERROR:
                return "error"
            if conn.status == ConnectionStatus.RESTRICTED:
                return "restricted"
            if conn.status == ConnectionStatus.EXPIRED:
                return "token_expired"
            if (
                conn.token_expires_at
                and conn.token_expires_at <= now
                and not conn.encrypted_refresh_token
            ):
                return "token_expired"

            if provider_id == "whatsapp":
                if conn.encrypted_access_token and conn.external_account_id:
                    if conn.status == ConnectionStatus.ACTIVE:
                        return "connected"
                    if conn.status == ConnectionStatus.CONFIGURED:
                        return "credentials_saved"
                    return "error"
                if conn.external_account_id or conn.encrypted_access_token:
                    return "credentials_saved"
                return "configuration_incomplete"

            if not conn.encrypted_access_token:
                if conn.client_id and conn.encrypted_client_secret:
                    return "authorization_required"
                if conn.client_id or conn.encrypted_client_secret:
                    return "credentials_saved"
                return "configuration_incomplete"
            return "connected"

        def client_preview(client_id: str | None) -> str | None:
            if not client_id:
                return None
            if len(client_id) <= 12:
                return client_id
            return f"{client_id[:6]}...{client_id[-4:]}"

        # 1. Gmail
        gmail_conn = google_conn
        gmail_status = resolve_status(gmail_conn, "google")
        gmail_item = AppConnectionOverviewItem(
            id="gmail",
            name="Gmail",
            category="Email Automation",
            icon="mail",
            description=(
                "Automate email notifications, draft creation, and mailbox inbox inspection."
            ),
            status=gmail_status,
            connection_id=gmail_conn.id if gmail_conn else None,
            connected_account=(
                (gmail_conn.external_account_name or gmail_conn.external_account_id)
                if (gmail_conn and gmail_status == "connected")
                else None
            ),
            config_method=gmail_conn.config_method if gmail_conn else None,
            is_default=gmail_conn.is_default if gmail_conn else True,
            has_credentials=bool(
                gmail_conn and gmail_conn.client_id and gmail_conn.encrypted_client_secret
            ),
            has_access_token=bool(gmail_conn and gmail_conn.encrypted_access_token),
            client_id=gmail_conn.client_id if gmail_conn else None,
            client_id_preview=client_preview(gmail_conn.client_id) if gmail_conn else None,
            has_client_secret=bool(gmail_conn and gmail_conn.encrypted_client_secret),
            last_verified_at=gmail_conn.last_verified_at if gmail_conn else None,
            updated_at=gmail_conn.updated_at if gmail_conn else None,
            supported_methods=["custom_credentials"]
            + (["oauth"] if bool(settings.GOOGLE_CLIENT_ID) else []),
            platform_oauth_available=bool(
                settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
            ),
            services=["gmail"],
            callback_url=google_cb,
        )

        # 2. Google Sheets
        sheets_conn = google_conn
        sheets_status = resolve_status(sheets_conn, "google")
        sheets_item = AppConnectionOverviewItem(
            id="sheets",
            name="Google Sheets",
            category="Spreadsheets & Data",
            icon="sheet",
            description=(
                "Read tabular records, append lead or execution rows, and update spreadsheet cells."
            ),
            status=sheets_status,
            connection_id=sheets_conn.id if sheets_conn else None,
            connected_account=(
                (sheets_conn.external_account_name or sheets_conn.external_account_id)
                if (sheets_conn and sheets_status == "connected")
                else None
            ),
            config_method=sheets_conn.config_method if sheets_conn else None,
            is_default=sheets_conn.is_default if sheets_conn else True,
            has_credentials=bool(
                sheets_conn and sheets_conn.client_id and sheets_conn.encrypted_client_secret
            ),
            has_access_token=bool(sheets_conn and sheets_conn.encrypted_access_token),
            client_id=sheets_conn.client_id if sheets_conn else None,
            client_id_preview=client_preview(sheets_conn.client_id) if sheets_conn else None,
            has_client_secret=bool(sheets_conn and sheets_conn.encrypted_client_secret),
            last_verified_at=sheets_conn.last_verified_at if sheets_conn else None,
            updated_at=sheets_conn.updated_at if sheets_conn else None,
            supported_methods=["custom_credentials"]
            + (["oauth"] if bool(settings.GOOGLE_CLIENT_ID) else []),
            platform_oauth_available=bool(
                settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET
            ),
            services=["sheets"],
            callback_url=google_cb,
        )

        # 3. Slack
        slack_status = resolve_status(slack_conn, "slack")
        slack_item = AppConnectionOverviewItem(
            id="slack",
            name="Slack",
            category="Team Collaboration",
            icon="slack",
            description=(
                "Send channel alerts, direct team messages, and automation run status updates."
            ),
            status=slack_status,
            connection_id=slack_conn.id if slack_conn else None,
            connected_account=(
                (slack_conn.external_account_name or slack_conn.external_account_id)
                if (slack_conn and slack_status == "connected")
                else None
            ),
            config_method=slack_conn.config_method if slack_conn else None,
            is_default=slack_conn.is_default if slack_conn else True,
            has_credentials=bool(
                slack_conn and slack_conn.client_id and slack_conn.encrypted_client_secret
            ),
            has_access_token=bool(slack_conn and slack_conn.encrypted_access_token),
            client_id=slack_conn.client_id if slack_conn else None,
            client_id_preview=client_preview(slack_conn.client_id) if slack_conn else None,
            has_client_secret=bool(slack_conn and slack_conn.encrypted_client_secret),
            last_verified_at=slack_conn.last_verified_at if slack_conn else None,
            updated_at=slack_conn.updated_at if slack_conn else None,
            supported_methods=["custom_credentials"]
            + (["oauth"] if bool(settings.SLACK_CLIENT_ID) else []),
            platform_oauth_available=bool(
                settings.SLACK_CLIENT_ID and settings.SLACK_CLIENT_SECRET
            ),
            services=["slack"],
            callback_url=slack_cb,
        )

        # 4. WhatsApp Business
        whatsapp_status = resolve_status(whatsapp_conn, "whatsapp")
        whatsapp_meta = (
            whatsapp_conn.metadata_json if (whatsapp_conn and whatsapp_conn.metadata_json) else {}
        )
        whatsapp_item = AppConnectionOverviewItem(
            id="whatsapp",
            name="WhatsApp Business",
            category="Customer Messaging",
            icon="message-circle",
            description=(
                "Send direct text notifications and pre-approved marketing/utility templates "
                "via Meta Cloud API."
            ),
            status=whatsapp_status,
            connection_id=whatsapp_conn.id if whatsapp_conn else None,
            connected_account=(
                (whatsapp_conn.external_account_name or whatsapp_conn.external_account_id)
                if (whatsapp_conn and whatsapp_status == "connected")
                else None
            ),
            config_method=whatsapp_conn.config_method if whatsapp_conn else None,
            is_default=whatsapp_conn.is_default if whatsapp_conn else True,
            has_credentials=bool(
                whatsapp_conn
                and whatsapp_conn.encrypted_access_token
                and whatsapp_conn.external_account_id
            ),
            has_access_token=bool(whatsapp_conn and whatsapp_conn.encrypted_access_token),
            client_id=whatsapp_conn.external_account_id if whatsapp_conn else None,
            client_id_preview=(
                client_preview(whatsapp_conn.external_account_id) if whatsapp_conn else None
            ),
            has_client_secret=bool(whatsapp_conn and whatsapp_conn.encrypted_access_token),
            phone_number_id=whatsapp_conn.external_account_id if whatsapp_conn else None,
            business_account_id=whatsapp_meta.get("business_account_id"),
            graph_api_version=whatsapp_meta.get("graph_api_version", "v21.0"),
            has_app_secret=bool(whatsapp_meta.get("encrypted_app_secret")),
            last_verified_at=whatsapp_conn.last_verified_at if whatsapp_conn else None,
            updated_at=whatsapp_conn.updated_at if whatsapp_conn else None,
            supported_methods=["custom_credentials"],
            platform_oauth_available=False,
            services=["whatsapp"],
            callback_url=whatsapp_webhook,
        )

        return [gmail_item, sheets_item, slack_item, whatsapp_item]

    @classmethod
    async def save_custom_credentials(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        payload: SaveCustomCredentialsRequest,
    ) -> IntegrationConnection:
        """Create or update user-scoped custom application credentials."""
        provider = payload.provider.lower().strip()
        now = datetime.now(UTC)

        # Look for existing connection for this user & provider
        stmt = (
            select(IntegrationConnection)
            .where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.provider == provider,
            )
            .order_by(
                IntegrationConnection.is_default.desc(),
                IntegrationConnection.updated_at.desc(),
            )
        )
        existing = await db.scalar(stmt)

        # If payload specifies default, unset default for other connections of this provider
        if payload.is_default:
            other_stmt = select(IntegrationConnection).where(
                IntegrationConnection.user_id == user_id,
                IntegrationConnection.provider == provider,
            )
            other_conns = list((await db.scalars(other_stmt)).all())
            for c in other_conns:
                c.is_default = False

        if provider in ("google", "slack"):
            encrypted_secret = (
                encrypt_oauth_token(payload.client_secret.strip())
                if (payload.client_secret and payload.client_secret.strip())
                else (existing.encrypted_client_secret if existing else None)
            )

            if existing:
                existing.config_method = "custom_credentials"
                creds_changed = False
                if payload.client_id is not None and payload.client_id.strip():
                    new_client_id = payload.client_id.strip()
                    if existing.client_id != new_client_id:
                        existing.client_id = new_client_id
                        creds_changed = True
                if payload.client_secret and payload.client_secret.strip():
                    existing.encrypted_client_secret = encrypted_secret
                    creds_changed = True

                # Invalidate existing token if client credentials changed
                if creds_changed and existing.encrypted_access_token:
                    existing.encrypted_access_token = None
                    existing.encrypted_refresh_token = None
                    existing.external_account_id = None
                    existing.external_account_name = None

                if payload.service:
                    existing.service = payload.service
                existing.is_default = payload.is_default
                existing.updated_at = now
                if not existing.encrypted_access_token:
                    existing.status = (
                        ConnectionStatus.AUTHORIZATION_REQUIRED
                        if existing.client_id and existing.encrypted_client_secret
                        else ConnectionStatus.CONFIGURED
                    )
                await db.commit()
                await db.refresh(existing)
                logger.info(
                    "Updated custom credentials for connection %s (%s)", existing.id, provider
                )
                return existing

            conn = IntegrationConnection(
                id=uuid.uuid4(),
                user_id=user_id,
                provider=provider,
                service=payload.service or provider,
                config_method="custom_credentials",
                client_id=payload.client_id.strip() if payload.client_id else None,
                encrypted_client_secret=encrypted_secret,
                is_default=payload.is_default,
                status=(
                    ConnectionStatus.AUTHORIZATION_REQUIRED
                    if payload.client_id and encrypted_secret
                    else ConnectionStatus.CONFIGURED
                ),
                created_at=now,
                updated_at=now,
            )
            db.add(conn)
            await db.commit()
            await db.refresh(conn)
            logger.info("Created custom credentials connection %s (%s)", conn.id, provider)
            return conn

        elif provider == "whatsapp":
            encrypted_token = (
                encrypt_oauth_token(payload.access_token.strip())
                if (payload.access_token and payload.access_token.strip())
                else (existing.encrypted_access_token if existing else None)
            )
            phone_number_id = (
                payload.phone_number_id.strip()
                if (payload.phone_number_id and payload.phone_number_id.strip())
                else (existing.external_account_id if existing else None)
            )

            meta: dict[str, Any] = (
                dict(existing.metadata_json) if (existing and existing.metadata_json) else {}
            )
            if payload.phone_number_id and payload.phone_number_id.strip():
                meta["phone_number_id"] = payload.phone_number_id.strip()
            if payload.business_account_id is not None:
                meta["business_account_id"] = payload.business_account_id.strip()
            if payload.graph_api_version:
                meta["graph_api_version"] = payload.graph_api_version.strip()
            if payload.webhook_verify_token is not None:
                meta["webhook_verify_token"] = payload.webhook_verify_token.strip()
            if payload.app_secret and payload.app_secret.strip():
                meta["encrypted_app_secret"] = encrypt_oauth_token(payload.app_secret.strip())

            status = (
                ConnectionStatus.ACTIVE
                if (encrypted_token and phone_number_id)
                else ConnectionStatus.CONFIGURED
            )
            account_name = existing.external_account_name if existing else None

            # Test WhatsApp sender connectivity immediately if token and phone_number_id
            # are provided
            if payload.access_token and phone_number_id:
                from flowpilot.integrations.whatsapp.client import (
                    WhatsAppClient,
                    WhatsAppError,
                )

                try:
                    probe = await WhatsAppClient.get_phone_number_details(
                        phone_number_id=phone_number_id,
                        access_token=payload.access_token.strip(),
                        graph_version=payload.graph_api_version or "v21.0",
                    )
                    verified_name = probe.get("verified_name", "WhatsApp Business")
                    display_num = probe.get("display_phone_number", phone_number_id)
                    account_name = f"{verified_name} ({display_num})"
                    status = ConnectionStatus.ACTIVE
                except WhatsAppError as probe_err:
                    logger.warning("WhatsApp initial credentials probe warning: %s", probe_err)
                    status = ConnectionStatus.ERROR
            elif existing and not payload.access_token:
                # Retain existing status if access token wasn't replaced
                status = existing.status

            if existing:
                existing.config_method = "custom_credentials"
                existing.encrypted_access_token = encrypted_token
                existing.external_account_id = phone_number_id
                if account_name:
                    existing.external_account_name = account_name
                existing.metadata_json = meta
                existing.is_default = payload.is_default
                existing.status = status
                existing.updated_at = now
                if status == ConnectionStatus.ACTIVE:
                    existing.last_verified_at = now
                await db.commit()
                await db.refresh(existing)
                logger.info("Updated custom WhatsApp connection %s", existing.id)
                return existing

            conn = IntegrationConnection(
                id=uuid.uuid4(),
                user_id=user_id,
                provider="whatsapp",
                service="whatsapp",
                config_method="custom_credentials",
                encrypted_access_token=encrypted_token,
                external_account_id=phone_number_id,
                external_account_name=account_name or phone_number_id,
                metadata_json=meta,
                is_default=payload.is_default,
                status=status,
                last_verified_at=now if status == ConnectionStatus.ACTIVE else None,
                created_at=now,
                updated_at=now,
            )
            db.add(conn)
            await db.commit()
            await db.refresh(conn)
            logger.info("Created custom WhatsApp connection %s", conn.id)
            return conn
        else:
            raise IntegrationServiceError(f"Unsupported provider: {provider}")

    @classmethod
    async def set_default_connection(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> IntegrationConnection:
        """Set a connection as the user's primary connection for its provider."""
        conn = await cls.get_user_connection(db, user_id, connection_id)
        other_stmt = select(IntegrationConnection).where(
            IntegrationConnection.user_id == user_id,
            IntegrationConnection.provider == conn.provider,
        )
        for c in (await db.scalars(other_stmt)).all():
            c.is_default = c.id == conn.id
        await db.commit()
        await db.refresh(conn)
        return conn

    @classmethod
    async def initiate_oauth_flow(
        cls,
        user_id: uuid.UUID,
        provider: str,
        service: str | None = None,
        redirect_uri: str | None = None,
        connection_id: uuid.UUID | None = None,
        db: AsyncSession | None = None,
    ) -> IntegrationAuthorizeResponse:
        """Generate provider-specific authorization URL with signed state token and PKCE."""
        norm_provider = provider.lower().strip()

        custom_client_id: str | None = None
        custom_conn_id: uuid.UUID | None = connection_id

        if db:
            if connection_id:
                try:
                    conn = await cls.get_user_connection(db, user_id, connection_id)
                    if conn.client_id:
                        custom_client_id = conn.client_id
                except IntegrationNotFoundError:
                    pass
            else:
                stmt = (
                    select(IntegrationConnection)
                    .where(
                        IntegrationConnection.user_id == user_id,
                        IntegrationConnection.provider == norm_provider,
                        IntegrationConnection.client_id.isnot(None),
                    )
                    .order_by(
                        IntegrationConnection.is_default.desc(),
                        IntegrationConnection.updated_at.desc(),
                    )
                )
                existing = await db.scalar(stmt)
                if existing and existing.client_id:
                    custom_client_id = existing.client_id
                    custom_conn_id = existing.id

        if norm_provider == "google":
            auth_url, state, _ = GoogleOAuth.get_authorization_url(
                user_id=user_id,
                service=service,
                redirect_uri=redirect_uri,
                client_id=custom_client_id,
                connection_id=custom_conn_id,
            )
            return IntegrationAuthorizeResponse(
                provider="google",
                authorization_url=auth_url,
                state=state,
            )
        elif norm_provider == "slack":
            auth_url, state = SlackOAuth.get_authorization_url(
                user_id=user_id,
                redirect_uri=redirect_uri,
                client_id=custom_client_id,
                connection_id=custom_conn_id,
            )
            return IntegrationAuthorizeResponse(
                provider="slack",
                authorization_url=auth_url,
                state=state,
            )
        else:
            raise IntegrationServiceError(f"Unsupported OAuth provider: '{provider}'")

    @classmethod
    async def handle_oauth_callback(
        cls,
        db: AsyncSession,
        provider: str,
        code: str,
        state: str,
        error: str | None = None,
    ) -> IntegrationConnection:
        """Process OAuth authorization-code callback, encrypt tokens, and upsert connection."""
        norm_provider = provider.lower().strip()

        if error:
            logger.warning("OAuth authorization rejected by user: %s", error)
            raise OAuthAuthenticationError(f"OAuth authorization rejected: {error}")

        # Validate state signature, expiration, and provider binding
        payload = validate_oauth_state(state, expected_provider=norm_provider)
        user_id = uuid.UUID(payload["user_id"])
        service = payload.get("service")
        redirect_uri = payload.get("redirect_uri")
        code_verifier = payload.get("code_verifier")
        connection_id_str = payload.get("connection_id")

        custom_client_id: str | None = None
        custom_client_secret: str | None = None
        target_connection: IntegrationConnection | None = None

        if connection_id_str:
            try:
                target_conn_id = uuid.UUID(connection_id_str)
                stmt = select(IntegrationConnection).where(
                    IntegrationConnection.id == target_conn_id,
                    IntegrationConnection.user_id == user_id,
                )
                target_connection = await db.scalar(stmt)
                if target_connection:
                    custom_client_id = target_connection.client_id
                    if target_connection.encrypted_client_secret:
                        custom_client_secret = decrypt_oauth_token(
                            target_connection.encrypted_client_secret
                        )
            except Exception as e:
                logger.warning("Could not resolve connection_id from state: %s", e)

        # Exchange authorization code for tokens
        bundle: OAuthTokenBundle
        if norm_provider == "google":
            bundle = await GoogleOAuth.exchange_code(
                code=code,
                code_verifier=code_verifier,
                redirect_uri=redirect_uri,
                client_id=custom_client_id,
                client_secret=custom_client_secret,
            )
        elif norm_provider == "slack":
            bundle = await SlackOAuth.exchange_code(
                code=code,
                redirect_uri=redirect_uri,
                client_id=custom_client_id,
                client_secret=custom_client_secret,
            )
        else:
            raise IntegrationServiceError(f"Unsupported provider: {provider}")

        # Encrypt tokens using MultiFernet
        encrypted_access = encrypt_oauth_token(bundle.access_token)
        encrypted_refresh = (
            encrypt_oauth_token(bundle.refresh_token) if bundle.refresh_token else None
        )

        now = datetime.now(UTC)

        # If we initiated authorization for an existing custom connection,
        # update that exact connection
        if target_connection:
            target_connection.external_account_id = bundle.external_account_id
            target_connection.external_account_name = (
                bundle.external_account_name or target_connection.external_account_name
            )
            target_connection.encrypted_access_token = encrypted_access
            if encrypted_refresh:
                target_connection.encrypted_refresh_token = encrypted_refresh
            target_connection.granted_scopes = bundle.granted_scopes
            target_connection.token_expires_at = bundle.expires_at
            target_connection.status = ConnectionStatus.ACTIVE
            target_connection.last_verified_at = now
            target_connection.updated_at = now
            target_connection.metadata_json = {
                **(target_connection.metadata_json or {}),
                **bundle.raw_response,
            }
            await db.commit()
            await db.refresh(target_connection)
            logger.info(
                "Bound OAuth tokens to custom connection %s for user %s",
                target_connection.id,
                user_id,
            )
            return target_connection

        # Check for existing connection matching user, provider, and external_account_id
        stmt = select(IntegrationConnection).where(
            IntegrationConnection.user_id == user_id,
            IntegrationConnection.provider == norm_provider,
            IntegrationConnection.external_account_id == bundle.external_account_id,
        )
        existing = await db.scalar(stmt)

        if existing:
            # Update existing connection
            existing.encrypted_access_token = encrypted_access
            if encrypted_refresh:
                existing.encrypted_refresh_token = encrypted_refresh
            existing.granted_scopes = bundle.granted_scopes
            existing.token_expires_at = bundle.expires_at
            existing.external_account_name = (
                bundle.external_account_name or existing.external_account_name
            )
            existing.metadata_json = {**existing.metadata_json, **bundle.raw_response}
            existing.status = ConnectionStatus.ACTIVE
            existing.last_verified_at = now
            existing.updated_at = now
            await db.commit()
            await db.refresh(existing)
            logger.info("Updated existing connection %s for user %s", existing.id, user_id)
            return existing

        # Create new connection
        connection = IntegrationConnection(
            id=uuid.uuid4(),
            user_id=user_id,
            provider=norm_provider,
            service=service,
            config_method="oauth" if not custom_client_id else "custom_credentials",
            client_id=custom_client_id,
            encrypted_client_secret=(
                encrypt_oauth_token(custom_client_secret) if custom_client_secret else None
            ),
            is_default=True,
            external_account_id=bundle.external_account_id,
            external_account_name=bundle.external_account_name,
            encrypted_access_token=encrypted_access,
            encrypted_refresh_token=encrypted_refresh,
            granted_scopes=bundle.granted_scopes,
            token_expires_at=bundle.expires_at,
            status=ConnectionStatus.ACTIVE,
            last_verified_at=now,
            created_at=now,
            updated_at=now,
            metadata_json=bundle.raw_response,
        )
        db.add(connection)
        await db.commit()
        await db.refresh(connection)
        logger.info(
            "Created new %s connection %s for user %s",
            norm_provider,
            connection.id,
            user_id,
        )
        return connection

    @classmethod
    async def test_connection(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> IntegrationConnectionTestResponse:
        """Execute active diagnostic verification on an external connection."""
        connection = await cls.get_user_connection(db, user_id, connection_id)
        now = datetime.now(UTC)

        try:
            if connection.provider == "whatsapp":
                from flowpilot.integrations.whatsapp.client import (
                    WhatsAppClient,
                )

                if not connection.encrypted_access_token:
                    raise OAuthError("No access token is configured for this WhatsApp connection.")
                token = decrypt_oauth_token(connection.encrypted_access_token)
                phone_number_id = connection.external_account_id or (
                    connection.metadata_json or {}
                ).get("phone_number_id")
                graph_version = (connection.metadata_json or {}).get(
                    "graph_api_version", settings.WHATSAPP_GRAPH_API_VERSION or "v21.0"
                )

                if not phone_number_id:
                    raise OAuthError("Phone Number ID is missing for this WhatsApp connection.")

                details = await WhatsAppClient.get_phone_number_details(
                    phone_number_id=phone_number_id,
                    access_token=token,
                    graph_version=graph_version,
                )
                verified_name = details.get("verified_name", "WhatsApp Business Sender")
                display_phone = details.get("display_phone_number", phone_number_id)
                status_text = details.get("status", "ACTIVE")

                connection.last_verified_at = now
                connection.status = ConnectionStatus.ACTIVE
                connection.external_account_name = f"{verified_name} ({display_phone})"
                await db.commit()
                return IntegrationConnectionTestResponse(
                    id=connection.id,
                    ok=True,
                    provider="whatsapp",
                    status="active",
                    message=(
                        f"WhatsApp sender verified successfully: {verified_name} "
                        f"({display_phone}). Status: {status_text}."
                    ),
                    external_account_id=display_phone,
                    tested_at=now,
                )

            # Refresh if needed and test connectivity for OAuth providers (Google, Slack)
            token = await OAuthTokenManager.get_valid_access_token(db, connection)

            if connection.provider == "google":
                import httpx

                async with httpx.AsyncClient(timeout=10.0) as client:
                    resp = await client.get(
                        "https://www.googleapis.com/oauth2/v3/userinfo",
                        headers={"Authorization": f"Bearer {token}"},
                    )
                    if resp.status_code != 200:
                        raise OAuthError(f"Google userinfo check returned {resp.status_code}")
                    userinfo = resp.json()
                    connection.last_verified_at = now
                    connection.status = ConnectionStatus.ACTIVE
                    await db.commit()
                    return IntegrationConnectionTestResponse(
                        id=connection.id,
                        ok=True,
                        provider="google",
                        status="active",
                        message="Google authentication and API reachability verified successfully.",
                        external_account_id=userinfo.get("email") or connection.external_account_id,
                        tested_at=now,
                    )

            elif connection.provider == "slack":
                from slack_sdk.web.async_client import AsyncWebClient

                client = AsyncWebClient(token=token)
                auth_test = await client.auth_test()
                if not auth_test.get("ok"):
                    raise OAuthError(f"Slack auth.test returned error: {auth_test.get('error')}")

                connection.last_verified_at = now
                connection.status = ConnectionStatus.ACTIVE
                await db.commit()
                return IntegrationConnectionTestResponse(
                    id=connection.id,
                    ok=True,
                    provider="slack",
                    status="active",
                    message="Slack workspace authentication verified successfully.",
                    external_account_id=auth_test.get("team_id") or connection.external_account_id,
                    tested_at=now,
                )

            else:
                return IntegrationConnectionTestResponse(
                    id=connection.id,
                    ok=False,
                    provider=connection.provider,
                    status=connection.status,
                    message=f"Unsupported provider: {connection.provider}",
                    external_account_id=connection.external_account_id,
                    tested_at=now,
                )

        except Exception as exc:
            logger.warning("Connection test failed for %s: %s", connection.id, exc)
            connection.status = ConnectionStatus.ERROR
            await db.commit()
            return IntegrationConnectionTestResponse(
                id=connection.id,
                ok=False,
                provider=connection.provider,
                status="error",
                message=f"Connection test failed: {exc}",
                external_account_id=connection.external_account_id,
                tested_at=now,
            )

    @classmethod
    async def disconnect_connection(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        connection_id: uuid.UUID,
    ) -> None:
        """Revoke external provider credentials and delete connection."""
        connection = await cls.get_user_connection(db, user_id, connection_id)

        # Attempt safe remote revocation
        if connection.provider == "google":
            await GoogleOAuth.revoke_token(connection)
        elif connection.provider == "slack":
            await SlackOAuth.revoke_token(connection)

        await db.delete(connection)
        await db.commit()
        logger.info("Successfully disconnected and deleted connection %s", connection_id)

    @classmethod
    async def list_external_actions(
        cls,
        db: AsyncSession,
        user_id: uuid.UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ExternalAction], int]:
        """Query user's external action execution audit history."""
        from sqlalchemy import func

        stmt = (
            select(ExternalAction)
            .where(ExternalAction.user_id == user_id)
            .order_by(ExternalAction.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        count_stmt = select(func.count(ExternalAction.id)).where(ExternalAction.user_id == user_id)

        actions = list((await db.scalars(stmt)).all())
        total = await db.scalar(count_stmt) or 0
        return actions, total

    @classmethod
    def get_whatsapp_status(cls) -> WhatsAppStatusResponse:
        """Return sanitized configuration and readiness telemetry for WhatsApp Cloud API."""
        pid = settings.WHATSAPP_PHONE_NUMBER_ID
        waba = settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        masked_pid = f"******{pid[-4:]}" if pid and len(pid) >= 4 else None
        masked_waba = f"******{waba[-4:]}" if waba and len(waba) >= 4 else None

        return WhatsAppStatusResponse(
            is_configured=settings.is_whatsapp_configured,
            phone_number_id_configured=bool(pid),
            masked_phone_number_id=masked_pid,
            business_account_id_configured=bool(waba),
            masked_business_account_id=masked_waba,
            graph_api_version=settings.WHATSAPP_GRAPH_API_VERSION or "v21.0",
            webhook_verify_token_configured=bool(settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN),
            app_secret_configured=bool(settings.WHATSAPP_APP_SECRET),
            missing_fields=settings.whatsapp_missing_fields,
            supported_capabilities=["whatsapp_send_message", "whatsapp_send_template"],
        )

    @classmethod
    async def test_whatsapp_connection(cls) -> IntegrationConnectionTestResponse:
        """Probe Meta WhatsApp Cloud API credentials using verified phone number discovery."""
        from flowpilot.integrations.whatsapp.client import WhatsAppClient, WhatsAppError

        now = datetime.now(UTC)
        if not settings.is_whatsapp_configured:
            return IntegrationConnectionTestResponse(
                id=uuid.uuid4(),
                ok=False,
                provider="whatsapp",
                status="not_configured",
                message=(
                    "WhatsApp Cloud API is not configured on the server. Missing: "
                    + ", ".join(settings.whatsapp_missing_fields)
                ),
                tested_at=now,
            )

        try:
            details = await WhatsAppClient.get_phone_number_details()
            verified_name = details.get("verified_name", "WhatsApp Business Number")
            display_phone = details.get("display_phone_number", settings.WHATSAPP_PHONE_NUMBER_ID)
            status_text = details.get("status", "ACTIVE")

            # Proactively ensure WABA is subscribed to App for delivery telemetry webhooks
            waba_note = ""
            if settings.WHATSAPP_BUSINESS_ACCOUNT_ID:
                try:
                    await WhatsAppClient.subscribe_waba_to_app()
                    waba_note = " Webhook telemetry subscription active."
                except Exception as sub_exc:
                    logger.warning("Could not auto-verify WABA webhook subscription: %s", sub_exc)
                    waba_note = f" (Note: Webhook subscription check returned: {sub_exc})"

            return IntegrationConnectionTestResponse(
                id=uuid.uuid4(),
                ok=True,
                provider="whatsapp",
                status="active",
                message=(
                    f"Connected to Meta Graph API. Verified sender: {verified_name} "
                    f"({display_phone}). Status: {status_text}.{waba_note}"
                ),
                external_account_id=display_phone,
                tested_at=now,
            )
        except WhatsAppError as exc:
            return IntegrationConnectionTestResponse(
                id=uuid.uuid4(),
                ok=False,
                provider="whatsapp",
                status="error",
                message=f"WhatsApp connectivity probe failed: {exc}",
                tested_at=now,
            )
