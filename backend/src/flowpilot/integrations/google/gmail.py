"""Gmail API integration adapter using the official Gmail REST API."""

import base64
import email.utils
import re
from email.message import EmailMessage
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.integrations.oauth import (
    OAuthAuthenticationError,
    OAuthScopeError,
    OAuthTokenManager,
)
from flowpilot.integrations.security import wrap_untrusted_email_content
from flowpilot.models.integration_connection import IntegrationConnection

logger = get_logger("integrations.google.gmail")

GMAIL_BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")


class GmailError(Exception):
    """Base exception for Gmail API errors."""


class GmailClient:
    """Async client for interacting with the official Google Gmail REST API."""

    @classmethod
    def validate_email_address(cls, address: str) -> str:
        """Validate recipient email address format."""
        clean = address.strip()
        # Parse display name if present (e.g., "Alice <alice@example.com>")
        parsed_name, parsed_addr = email.utils.parseaddr(clean)
        target = parsed_addr if parsed_addr else clean
        if not EMAIL_REGEX.match(target):
            raise ValueError(f"Invalid email address: '{address}'")
        return target

    @classmethod
    def _check_scope(cls, connection: IntegrationConnection, required_scope: str) -> None:
        """Ensure connection has been granted the required OAuth permission scope."""
        granted = set(connection.granted_scopes or [])
        if required_scope not in granted:
            msg = (
                f"Missing required OAuth scope: '{required_scope}'. "
                f"Connection has scopes: {sorted(granted)}"
            )
            logger.warning(msg)
            raise OAuthScopeError(msg)

    @classmethod
    def _build_rfc2822_message(
        cls,
        sender: str,
        recipient: str,
        subject: str,
        body_text: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> str:
        """Construct an RFC 2822 MIME message and return as base64url encoded string."""
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        if in_reply_to:
            msg["In-Reply-To"] = in_reply_to
            msg["References"] = references or in_reply_to
        msg.set_content(body_text)

        # Gmail requires URL-safe base64 encoding without padding
        raw_bytes = msg.as_bytes()
        return base64.urlsafe_b64encode(raw_bytes).decode("utf-8").rstrip("=")

    @classmethod
    async def list_messages(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        query: str | None = None,
        max_results: int = 10,
    ) -> list[dict[str, Any]]:
        """List messages matching query in the user's Gmail mailbox."""
        cls._check_scope(connection, "https://www.googleapis.com/auth/gmail.readonly")
        token = await OAuthTokenManager.get_valid_access_token(db, connection)

        params: dict[str, Any] = {"maxResults": min(max(1, max_results), 50)}
        if query:
            params["q"] = query.strip()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GMAIL_BASE_URL}/messages",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Gmail access token was rejected by Google API.")
            if resp.status_code != 200:
                raise GmailError(f"Gmail list messages failed ({resp.status_code}): {resp.text}")

            data = resp.json()
            return data.get("messages", [])

    @classmethod
    async def get_message(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        message_id: str,
    ) -> dict[str, Any]:
        """Fetch full details and body of a Gmail message, wrapped with prompt-injection defense."""
        cls._check_scope(connection, "https://www.googleapis.com/auth/gmail.readonly")
        token = await OAuthTokenManager.get_valid_access_token(db, connection)

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{GMAIL_BASE_URL}/messages/{message_id}",
                headers={"Authorization": f"Bearer {token}"},
                params={"format": "full"},
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Gmail access token was rejected by Google API.")
            if resp.status_code == 404:
                raise GmailError(f"Gmail message '{message_id}' not found.")
            if resp.status_code != 200:
                raise GmailError(f"Gmail get message failed ({resp.status_code}): {resp.text}")

            data = resp.json()

        # Parse headers
        headers_list = data.get("payload", {}).get("headers", [])
        headers_map = {h.get("name", "").lower(): h.get("value", "") for h in headers_list}

        sender = headers_map.get("from", "unknown")
        recipient = headers_map.get("to", "")
        subject = headers_map.get("subject", "(No Subject)")
        date_str = headers_map.get("date", "")
        message_id_header = headers_map.get("message-id", "")

        # Extract plain text body parts
        body_text = ""
        payload = data.get("payload", {})

        def _extract_body(part: dict[str, Any]) -> str:
            mime_type = part.get("mimeType", "")
            part_body = part.get("body", {})
            part_data = part_body.get("data")
            if mime_type == "text/plain" and part_data:
                try:
                    padding = 4 - (len(part_data) % 4)
                    padded = part_data + ("=" * (padding % 4))
                    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")
                except Exception:
                    return ""

            # Check sub-parts
            for sub in part.get("parts", []):
                sub_res = _extract_body(sub)
                if sub_res:
                    return sub_res
            return ""

        body_text = _extract_body(payload) or data.get("snippet", "")

        # Untrusted prompt injection wrapping
        guarded = wrap_untrusted_email_content(
            sender=sender,
            subject=subject,
            body_text=body_text,
        )

        return {
            "id": data.get("id"),
            "thread_id": data.get("threadId"),
            "sender": sender,
            "recipient": recipient,
            "subject": subject,
            "date": date_str,
            "message_id_header": message_id_header,
            "snippet": data.get("snippet", ""),
            "content": guarded["untrusted_body"],
            "security_notice": guarded["security_notice"],
            "labels": data.get("labelIds", []),
        }

    @classmethod
    async def create_draft(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        recipient: str,
        subject: str,
        body_text: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> dict[str, Any]:
        """Create a message draft in Gmail without sending it."""
        cls._check_scope(connection, "https://www.googleapis.com/auth/gmail.compose")
        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        sender = connection.external_account_id or "me"

        clean_recipient = cls.validate_email_address(recipient)
        raw_b64 = cls._build_rfc2822_message(
            sender=sender,
            recipient=clean_recipient,
            subject=subject,
            body_text=body_text,
            in_reply_to=in_reply_to,
            references=references,
        )

        payload = {"message": {"raw": raw_b64}}

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{GMAIL_BASE_URL}/drafts",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Gmail access token was rejected by Google API.")
            if resp.status_code not in (200, 201):
                raise GmailError(f"Gmail create draft failed ({resp.status_code}): {resp.text}")

            draft_data = resp.json()
            return {
                "draft_id": draft_data.get("id"),
                "message_id": draft_data.get("message", {}).get("id"),
                "recipient": clean_recipient,
                "subject": subject,
                "status": "draft_created",
            }

    @classmethod
    async def send_email(
        cls,
        db: AsyncSession,
        connection: IntegrationConnection,
        recipient: str,
        subject: str,
        body_text: str,
        in_reply_to: str | None = None,
        references: str | None = None,
    ) -> dict[str, Any]:
        """Send an email through the user's authorized Gmail connection.

        Mandatory Human Approval Gate: This method must only be executed after explicit human
        approval has verified the recipient, subject, and body digest.
        """
        cls._check_scope(connection, "https://www.googleapis.com/auth/gmail.send")
        token = await OAuthTokenManager.get_valid_access_token(db, connection)
        sender = connection.external_account_id or "me"

        clean_recipient = cls.validate_email_address(recipient)
        raw_b64 = cls._build_rfc2822_message(
            sender=sender,
            recipient=clean_recipient,
            subject=subject,
            body_text=body_text,
            in_reply_to=in_reply_to,
            references=references,
        )

        payload = {"raw": raw_b64}

        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                f"{GMAIL_BASE_URL}/messages/send",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 401:
                raise OAuthAuthenticationError("Gmail access token was rejected by Google API.")
            if resp.status_code not in (200, 201):
                raise GmailError(f"Gmail send email failed ({resp.status_code}): {resp.text}")

            result = resp.json()
            logger.info("Successfully sent email via Gmail message %s", result.get("id"))
            return {
                "message_id": result.get("id"),
                "thread_id": result.get("threadId"),
                "recipient": clean_recipient,
                "subject": subject,
                "status": "sent",
            }
