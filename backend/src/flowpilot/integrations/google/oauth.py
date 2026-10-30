"""Google OAuth 2.0 flow implementation supporting Gmail and Google Sheets scopes with PKCE."""

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
    generate_pkce_challenge,
    generate_pkce_verifier,
)
from flowpilot.models.integration_connection import IntegrationConnection

logger = get_logger("integrations.google.oauth")
settings = get_settings()

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"

# Explicit minimal scope definitions
SCOPES_USERINFO = [
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

SCOPES_GMAIL = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.send",
]

SCOPES_SHEETS = [
    "https://www.googleapis.com/auth/spreadsheets",
]


class GoogleOAuth:
    """Manages Google OAuth 2.0 authorization URLs, code exchange, and token refresh."""

    @classmethod
    def get_service_scopes(cls, service: str | None = None) -> list[str]:
        """Return the minimal necessary scopes for the requested Google service."""
        scopes = list(SCOPES_USERINFO)
        requested = (service or "all").lower().strip()

        if requested in ("gmail", "mail"):
            scopes.extend(SCOPES_GMAIL)
        elif requested in ("sheets", "spreadsheets"):
            scopes.extend(SCOPES_SHEETS)
        else:
            # Combined / default
            scopes.extend(SCOPES_GMAIL)
            scopes.extend(SCOPES_SHEETS)

        # De-duplicate preserving order
        seen = set()
        deduped = []
        for s in scopes:
            if s not in seen:
                seen.add(s)
                deduped.append(s)
        return deduped

    @classmethod
    def get_authorization_url(
        cls,
        user_id: uuid.UUID,
        service: str | None = None,
        redirect_uri: str | None = None,
        client_id: str | None = None,
        connection_id: uuid.UUID | str | None = None,
    ) -> tuple[str, str, str]:
        """Generate Google OAuth 2.0 authorization URL with PKCE and signed state.

        Returns:
            Tuple of (authorization_url, state, code_verifier)
        """
        active_client_id = client_id or settings.GOOGLE_CLIENT_ID
        if not active_client_id:
            raise OAuthConfigurationError(
                "Google OAuth is not configured. Please enter your Google Client ID and "
                "Secret in App Connections."
            )

        resolved_redirect_uri = redirect_uri or settings.GOOGLE_REDIRECT_URI
        code_verifier = generate_pkce_verifier()
        code_challenge = generate_pkce_challenge(code_verifier)

        # Signed tamper-resistant state storing code_verifier, user_id, and optional connection_id
        state = generate_oauth_state(
            user_id=user_id,
            provider="google",
            service=service,
            redirect_uri=resolved_redirect_uri,
            code_verifier=code_verifier,
            connection_id=connection_id,
        )

        scopes = cls.get_service_scopes(service)
        params = {
            "client_id": active_client_id,
            "redirect_uri": resolved_redirect_uri,
            "response_type": "code",
            "scope": " ".join(scopes),
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",  # Mandatory to receive refresh_token
            "prompt": "consent",  # Ensures refresh_token is returned even if re-authorizing
            "include_granted_scopes": "true",
        }

        query_string = urllib.parse.urlencode(params)
        auth_url = f"{GOOGLE_AUTH_URL}?{query_string}"
        return auth_url, state, code_verifier

    @classmethod
    async def exchange_code(
        cls,
        code: str,
        code_verifier: str | None,
        redirect_uri: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
    ) -> OAuthTokenBundle:
        """Exchange authorization code for OAuth access and refresh tokens."""
        active_client_id = client_id or settings.GOOGLE_CLIENT_ID
        active_client_secret = client_secret or settings.GOOGLE_CLIENT_SECRET

        if not active_client_id or not active_client_secret:
            raise OAuthConfigurationError("Google OAuth client credentials are not configured.")

        data: dict[str, Any] = {
            "client_id": active_client_id,
            "client_secret": active_client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri or settings.GOOGLE_REDIRECT_URI,
        }
        if code_verifier:
            data["code_verifier"] = code_verifier

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
            if resp.status_code != 200:
                logger.error(
                    "Google token exchange failed: status=%s, body=%s",
                    resp.status_code,
                    resp.text,
                )
                raise OAuthAuthenticationError(
                    f"Google token exchange failed ({resp.status_code}): {resp.text}"
                )

            token_data = resp.json()

        access_token = token_data.get("access_token")
        if not access_token:
            raise OAuthAuthenticationError("Token response did not contain access_token.")

        refresh_token = token_data.get("refresh_token")
        expires_in = token_data.get("expires_in")
        scope_str = token_data.get("scope", "")
        granted_scopes = [s.strip() for s in scope_str.split(" ") if s.strip()]

        # Query userinfo to determine external account identity
        account_email: str | None = None
        account_name: str | None = None
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                ui_resp = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if ui_resp.status_code == 200:
                    ui_data = ui_resp.json()
                    account_email = ui_data.get("email")
                    account_name = ui_data.get("name") or account_email
        except Exception as exc:
            logger.warning("Could not fetch Google user profile: %s", exc)

        return OAuthTokenBundle(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in_seconds=expires_in,
            granted_scopes=granted_scopes,
            external_account_id=account_email,
            external_account_name=account_name,
            raw_response=token_data,
        )

    @classmethod
    async def refresh_access_token(
        cls,
        connection: IntegrationConnection,
    ) -> OAuthTokenBundle:
        """Use refresh token to obtain a fresh access token from Google."""
        active_client_id = connection.client_id or settings.GOOGLE_CLIENT_ID
        active_client_secret = (
            decrypt_oauth_token(connection.encrypted_client_secret)
            if connection.encrypted_client_secret
            else settings.GOOGLE_CLIENT_SECRET
        )

        if not active_client_id or not active_client_secret:
            raise OAuthConfigurationError("Google OAuth client credentials are not configured.")

        if not connection.encrypted_refresh_token:
            raise OAuthAuthenticationError(
                f"Connection '{connection.id}' has no refresh token stored."
            )

        plain_refresh_token = decrypt_oauth_token(connection.encrypted_refresh_token)

        data = {
            "client_id": active_client_id,
            "client_secret": active_client_secret,
            "refresh_token": plain_refresh_token,
            "grant_type": "refresh_token",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(GOOGLE_TOKEN_URL, data=data)
            if resp.status_code != 200:
                logger.error(
                    "Google token refresh failed: status=%s, body=%s", resp.status_code, resp.text
                )
                raise OAuthAuthenticationError(
                    f"Google token refresh failed ({resp.status_code}): {resp.text}"
                )

            token_data = resp.json()

        new_access_token = token_data.get("access_token")
        if not new_access_token:
            raise OAuthAuthenticationError("Token refresh response did not contain access_token.")

        # Google might or might not return a new refresh token on refresh
        new_refresh_token = token_data.get("refresh_token") or plain_refresh_token
        expires_in = token_data.get("expires_in")
        scope_str = token_data.get("scope", "")
        granted_scopes = (
            [s.strip() for s in scope_str.split(" ") if s.strip()]
            if scope_str
            else connection.granted_scopes
        )

        return OAuthTokenBundle(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
            expires_in_seconds=expires_in,
            granted_scopes=granted_scopes,
            external_account_id=connection.external_account_id,
            external_account_name=connection.external_account_name,
            raw_response=token_data,
        )

    @classmethod
    async def revoke_token(cls, connection: IntegrationConnection) -> bool:
        """Revoke Google OAuth token at Google servers for safe disconnection."""
        token_to_revoke: str | None = None
        if connection.encrypted_refresh_token:
            token_to_revoke = decrypt_oauth_token(connection.encrypted_refresh_token)
        elif connection.encrypted_access_token:
            token_to_revoke = decrypt_oauth_token(connection.encrypted_access_token)

        if not token_to_revoke:
            return True

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(GOOGLE_REVOKE_URL, data={"token": token_to_revoke})
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("Google revoke call encountered error: %s", exc)
            return False
