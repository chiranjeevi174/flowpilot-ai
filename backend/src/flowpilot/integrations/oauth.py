"""Core OAuth 2.0 lifecycle management, token data structures, and refresh synchronization."""

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.integrations.security import (
    decrypt_oauth_token,
    encrypt_oauth_token,
)
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)

logger = get_logger("integrations.oauth")

# In-process locks for concurrent token refresh coordination per connection
_refresh_locks: dict[uuid.UUID, asyncio.Lock] = {}
_locks_guard = asyncio.Lock()


async def get_connection_refresh_lock(connection_id: uuid.UUID) -> asyncio.Lock:
    """Retrieve or create an async lock for synchronizing token refresh on a specific connection."""
    async with _locks_guard:
        if connection_id not in _refresh_locks:
            _refresh_locks[connection_id] = asyncio.Lock()
        return _refresh_locks[connection_id]


@dataclass
class OAuthTokenBundle:
    """Standardized representation of exchanged OAuth 2.0 credentials."""

    access_token: str
    refresh_token: str | None = None
    expires_in_seconds: int | None = None
    token_type: str = "Bearer"
    granted_scopes: list[str] = field(default_factory=list)
    external_account_id: str | None = None
    external_account_name: str | None = None
    raw_response: dict[str, Any] = field(default_factory=dict)

    @property
    def expires_at(self) -> datetime | None:
        """Calculate UTC expiration timestamp if expires_in_seconds is set."""
        if self.expires_in_seconds is not None and self.expires_in_seconds > 0:
            return datetime.now(UTC) + timedelta(seconds=self.expires_in_seconds)
        return None


class OAuthError(Exception):
    """Base exception for OAuth protocol and provider errors."""


class OAuthConfigurationError(OAuthError):
    """Raised when application client ID or secrets are missing."""


class OAuthAuthenticationError(OAuthError):
    """Raised when authorization code exchange or token refresh fails at provider."""


class OAuthScopeError(OAuthError):
    """Raised when an action requires permissions not granted in the OAuth token."""


class OAuthTokenManager:
    """Manages token retrieval, transparent refresh, and credential persistence."""

    @classmethod
    def is_token_expired(
        cls,
        connection: IntegrationConnection,
        buffer_seconds: int = 120,
    ) -> bool:
        """Check if connection access token is expired or within the expiry buffer."""
        if not connection.encrypted_access_token:
            return True
        if connection.token_expires_at is None:
            return False
        cutoff = datetime.now(UTC) + timedelta(seconds=buffer_seconds)
        return connection.token_expires_at <= cutoff

    @classmethod
    async def get_valid_access_token(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
    ) -> str:
        """Retrieve a valid, decrypted access token, automatically refreshing if expired.

        Uses connection-level locking to protect against concurrent token refresh race conditions.
        """
        if connection.status != ConnectionStatus.ACTIVE:
            raise OAuthAuthenticationError(
                f"Connection '{connection.id}' is '{connection.status}', not 'active'."
            )

        # Quick check if token is still fresh
        if not cls.is_token_expired(connection) and connection.encrypted_access_token:
            return decrypt_oauth_token(connection.encrypted_access_token)

        # Acquire per-connection lock for refresh (in-process + distributed across worker processes)
        lock = await get_connection_refresh_lock(connection.id)
        from flowpilot.core.config import get_settings

        settings = get_settings()

        async with lock:
            dist_lock = None
            try:
                import redis.asyncio as aioredis

                r = aioredis.from_url(settings.REDIS_URL, socket_timeout=2.0)
                dist_lock = r.lock(f"flowpilot:lock:conn_refresh:{connection.id}", timeout=30.0)
                await dist_lock.acquire()
            except Exception as exc:
                logger.debug("Redis distributed lock skipped (%s)", exc)
                dist_lock = None

            try:
                # Re-read connection state from database after acquiring lock
                # to check if another concurrent worker has already refreshed it
                await db.refresh(connection)
                if not cls.is_token_expired(connection) and connection.encrypted_access_token:
                    return decrypt_oauth_token(connection.encrypted_access_token)

                # Perform provider-specific refresh
                from flowpilot.integrations.google.oauth import GoogleOAuth
                from flowpilot.integrations.slack.oauth import SlackOAuth

                provider = connection.provider.lower()
                refreshed_bundle: OAuthTokenBundle

                try:
                    if provider == "google":
                        refreshed_bundle = await GoogleOAuth.refresh_access_token(connection)
                    elif provider == "slack":
                        refreshed_bundle = await SlackOAuth.refresh_access_token(connection)
                    else:
                        raise OAuthError(f"Unsupported provider for refresh: {provider}")

                    # Update connection with new encrypted tokens
                    connection.encrypted_access_token = encrypt_oauth_token(
                        refreshed_bundle.access_token
                    )
                    if refreshed_bundle.refresh_token:
                        connection.encrypted_refresh_token = encrypt_oauth_token(
                            refreshed_bundle.refresh_token
                        )
                    if refreshed_bundle.expires_at:
                        connection.token_expires_at = refreshed_bundle.expires_at
                    connection.last_verified_at = datetime.now(UTC)
                    connection.status = ConnectionStatus.ACTIVE

                    await db.commit()
                    await db.refresh(connection)
                    logger.info(
                        "Successfully refreshed OAuth token for connection %s", connection.id
                    )
                    return refreshed_bundle.access_token

                except Exception as exc:
                    logger.error(
                        "Token refresh failed for connection %s (%s): %s",
                        connection.id,
                        provider,
                        exc,
                    )
                    connection.status = ConnectionStatus.EXPIRED
                    await db.commit()
                    raise OAuthAuthenticationError(
                        f"Failed to refresh OAuth token for {provider}: {exc}"
                    ) from exc
            finally:
                if dist_lock:
                    import contextlib

                    with contextlib.suppress(Exception):
                        await dist_lock.release()
