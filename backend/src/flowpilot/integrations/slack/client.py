"""Slack API client using AsyncWebClient for channel discovery and message delivery."""

from typing import Any

from slack_sdk.errors import SlackApiError
from slack_sdk.web.async_client import AsyncWebClient
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthScopeError,
    OAuthTokenManager,
)
from flowpilot.models.integration_connection import IntegrationConnection

logger = get_logger("integrations.slack.client")


class SlackError(Exception):
    """Base exception for Slack operations."""


class SlackClient:
    """Async client wrapping Slack's AsyncWebClient for workspace operations."""

    @classmethod
    def _check_scope(cls, connection: IntegrationConnection, required_scope: str) -> None:
        """Ensure connection has been granted required Slack OAuth scope."""
        granted = set(connection.granted_scopes or [])
        if required_scope not in granted:
            msg = (
                f"Missing required Slack scope: '{required_scope}'. "
                f"Connection has scopes: {sorted(granted)}"
            )
            logger.warning(msg)
            raise OAuthScopeError(msg)

    @classmethod
    async def get_web_client(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
    ) -> AsyncWebClient:
        """Instantiate an AsyncWebClient using the connection's active bot token."""
        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        return AsyncWebClient(token=token)

    @classmethod
    async def list_channels(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        types: str = "public_channel,private_channel",
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """List accessible conversations / channels in the connected Slack workspace."""
        cls._check_scope(connection, "channels:read")
        client = await cls.get_web_client(db, connection)

        try:
            resp = await client.conversations_list(
                types=types,
                limit=min(max(1, limit), 200),
                exclude_archived=True,
            )
            channels = resp.get("channels", [])
            return [
                {
                    "id": ch.get("id"),
                    "name": ch.get("name"),
                    "is_private": ch.get("is_private", False),
                    "is_member": ch.get("is_member", False),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                }
                for ch in channels
            ]
        except SlackApiError as exc:
            error_code = exc.response.get("error", "unknown_error")
            if error_code in ("invalid_auth", "token_revoked", "account_inactive"):
                raise OAuthAuthenticationError(f"Slack auth error: {error_code}") from exc
            logger.error("Slack conversations_list failed: %s", exc)
            raise SlackError(f"Slack conversations_list failed: {error_code}") from exc

    @classmethod
    async def prepare_message(
        cls,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Prepare a message payload for human approval review.

        Explicitly marks the action as pending and unexecuted.
        """
        clean_channel = channel.strip()
        clean_text = text.strip()
        if not clean_channel:
            raise ValueError("Channel must not be empty.")
        if not clean_text and not blocks:
            raise ValueError("Message must contain text or blocks.")

        return {
            "channel": clean_channel,
            "text": clean_text,
            "blocks": blocks or [],
            "status": "prepared",
            "approval_required": True,
        }

    @classmethod
    async def send_message(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        channel: str,
        text: str,
        blocks: list[dict[str, Any]] | None = None,
        thread_ts: str | None = None,
    ) -> dict[str, Any]:
        """Post a message to a Slack channel.

        Mandatory Human Approval Gate: This external side effect requires prior approval.
        """
        cls._check_scope(connection, "chat:write")
        clean_channel = channel.strip()
        clean_text = text.strip()
        if not clean_channel:
            raise ValueError("Target Slack channel must not be empty.")
        if not clean_text and not blocks:
            raise ValueError("Message must contain text or blocks.")

        client = await cls.get_web_client(db, connection)

        try:
            kwargs: dict[str, Any] = {
                "channel": clean_channel,
                "text": clean_text,
            }
            if blocks:
                kwargs["blocks"] = blocks
            if thread_ts:
                kwargs["thread_ts"] = thread_ts

            resp = await client.chat_postMessage(**kwargs)
            logger.info("Successfully posted Slack message to channel %s", clean_channel)
            return {
                "ok": resp.get("ok", True),
                "channel": resp.get("channel"),
                "ts": resp.get("ts"),
                "message_id": resp.get("ts"),
                "status": "sent",
            }
        except SlackApiError as exc:
            error_code = exc.response.get("error", "unknown_error")
            if error_code in ("invalid_auth", "token_revoked", "account_inactive"):
                raise OAuthAuthenticationError(f"Slack auth error: {error_code}") from exc
            logger.error("Slack chat_postMessage failed: %s", exc)
            raise SlackError(f"Slack chat_postMessage failed: {error_code}") from exc
