"""Slack OAuth v2 authorization flow, code exchange, and workspace installation."""

import urllib.parse
import uuid
from typing import Any

import httpx

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthConfigurationError,
    OAuthTokenBundle,
)
from flowpilot.integrations.security import (
    decrypt_oauth_token,
    generate_oauth_state,
)
from flowpilot.models.integration_connection import IntegrationConnection

logger = get_logger("integrations.slack.oauth")
settings = get_settings()

SLACK_AUTH_URL = "https://slack.com/oauth/v2/authorize"
SLACK_TOKEN_URL = "https://slack.com/api/oauth.v2.access"
SLACK_REVOKE_URL = "https://slack.com/api/auth.revoke"

# Minimal bot scopes required for FlowPilot actions without admin privileges
DEFAULT_SLACK_BOT_SCOPES = [
    "channels:read",
    "groups:read",
    "chat:write",
    "chat:write.public",
    "team:read",
]


class SlackOAuth:
    """Manages Slack OAuth v2 authorization URLs and server-side code exchange."""

    @classmethod
    def get_authorization_url(
        cls,
        user_id: uuid.UUID,
        redirect_uri: str | None = None,
        custom_scopes: list[str] | None = None,
        client_id: str | None = None,
        connection_id: uuid.UUID | str | None = None,
    ) -> tuple[str, str]:
        """Generate Slack OAuth v2 authorization URL with signed state parameter.

        Returns:
            Tuple of (authorization_url, state)
        """
        active_client_id = client_id or settings.SLACK_CLIENT_ID
        if not active_client_id:
            raise OAuthConfigurationError(
                "Slack OAuth is not configured. Please enter your Slack Client ID and "
                "Secret in App Connections."
            )

        resolved_redirect_uri = redirect_uri or settings.SLACK_REDIRECT_URI
        scopes = custom_scopes or DEFAULT_SLACK_BOT_SCOPES

        state = generate_oauth_state(
            user_id=user_id,
            provider="slack",
            service="slack",
            redirect_uri=resolved_redirect_uri,
            connection_id=connection_id,
        )

        params = {
            "client_id": active_client_id,
            "scope": ",".join(scopes),
            "redirect_uri": resolved_redirect_uri,
            "state": state,
        }

        query_string = urllib.parse.urlencode(params)
        auth_url = f"{SLACK_AUTH_URL}?{query_string}"
        return auth_url, state

    @classmethod
    async def exchange_code(
        cls,
        code: str,
        redirect_uri: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> OAuthTokenBundle:
        """Exchange temporary authorization code for Slack bot token and workspace metadata."""
        active_client_id = client_id or settings.SLACK_CLIENT_ID
        active_client_secret = client_secret or settings.SLACK_CLIENT_SECRET

        if not active_client_id or not active_client_secret:
            raise OAuthConfigurationError("Slack OAuth client credentials are not configured.")

        data: dict[str, Any] = {
            "client_id": active_client_id,
            "client_secret": active_client_secret,
            "code": code,
            "redirect_uri": redirect_uri or settings.SLACK_REDIRECT_URI,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(SLACK_TOKEN_URL, data=data)
            if resp.status_code != 200:
                logger.error(
                    "Slack token exchange HTTP error: status=%s, body=%s",
                    resp.status_code,
                    resp.text,
                )
                raise OAuthAuthenticationError(
                    f"Slack token exchange HTTP error ({resp.status_code}): {resp.text}"
                )

            token_data = resp.json()

        if not token_data.get("ok"):
            error_msg = token_data.get("error", "unknown_error")
            logger.error("Slack OAuth error: %s", error_msg)
            raise OAuthAuthenticationError(f"Slack OAuth error: {error_msg}")

        # Slack v2 returns bot access_token and team info
        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthAuthenticationError("Slack response did not include access_token.")

        team_info = token_data.get("team", {})
        team_id = team_info.get("id")
        team_name = team_info.get("name")
        bot_user_id = token_data.get("bot_user_id")

        scope_str = token_data.get("scope", "")
        granted_scopes = [s.strip() for s in scope_str.split(",") if s.strip()]

        raw_metadata = {
            "team_id": team_id,
            "team_name": team_name,
            "bot_user_id": bot_user_id,
            "app_id": token_data.get("app_id"),
        }

        return OAuthTokenBundle(
            access_token=access_token,
            refresh_token=token_data.get("refresh_token"),
            expires_in_seconds=token_data.get("expires_in"),
            granted_scopes=granted_scopes,
            external_account_id=team_id,
            external_account_name=team_name,
            raw_response=raw_metadata,
        )

    @classmethod
    async def refresh_access_token(
        cls,
        connection: IntegrationConnection,
    ) -> OAuthTokenBundle:
        """Refresh token for Slack (if token rotation is enabled in Slack app)."""
        active_client_id = connection.client_id or settings.SLACK_CLIENT_ID
        active_client_secret = (
            decrypt_oauth_token(connection.encrypted_client_secret)
            if connection.encrypted_client_secret
            else settings.SLACK_CLIENT_SECRET
        )

        if not connection.encrypted_refresh_token:
            # Standard Slack bot tokens do not expire unless token rotation is enabled
            plain_access_token = decrypt_oauth_token(connection.encrypted_access_token)
            return OAuthTokenBundle(
                access_token=plain_access_token,
                granted_scopes=connection.granted_scopes,
                external_account_id=connection.external_account_id,
                external_account_name=connection.external_account_name,
            )

        if not active_client_id or not active_client_secret:
            raise OAuthConfigurationError("Slack OAuth client credentials are not configured.")

        plain_refresh_token = decrypt_oauth_token(connection.encrypted_refresh_token)
        data = {
            "client_id": active_client_id,
            "client_secret": active_client_secret,
            "grant_type": "refresh_token",
            "refresh_token": plain_refresh_token,
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(SLACK_TOKEN_URL, data=data)
            token_data = resp.json()

        if not token_data.get("ok"):
            raise OAuthAuthenticationError(
                f"Slack refresh error: {token_data.get('error', 'unknown')}"
            )

        return OAuthTokenBundle(
            access_token=token_data["access_token"],
            refresh_token=token_data.get("refresh_token") or plain_refresh_token,
            expires_in_seconds=token_data.get("expires_in"),
            granted_scopes=connection.granted_scopes,
            external_account_id=connection.external_account_id,
            external_account_name=connection.external_account_name,
        )

    @classmethod
    async def revoke_token(cls, connection: IntegrationConnection) -> bool:
        """Revoke Slack bot token."""
        try:
            token = decrypt_oauth_token(connection.encrypted_access_token)
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    SLACK_REVOKE_URL,
                    headers={"Authorization": f"Bearer {token}"},
                )
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("Slack token revocation failed: %s", exc)
            return False
