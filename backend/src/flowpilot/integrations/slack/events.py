"""Slack event webhook handler, cryptographic signature verification, and deduplication."""

import time
from typing import Any

from slack_sdk.signature import SignatureVerifier
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.models.integration_event import IntegrationEvent, IntegrationEventStatus

logger = get_logger("integrations.slack.events")
settings = get_settings()


class WebhookVerificationError(Exception):
    """Raised when an inbound webhook fails cryptographic signature verification."""


class WebhookReplayError(Exception):
    """Raised when an inbound webhook has already been processed (duplicate delivery)."""


class SlackEventHandler:
    """Verifies and records inbound Slack Events API webhooks."""

    @classmethod
    def verify_slack_signature(
        cls,
        raw_body: bytes,
        timestamp_header: str | None,
        signature_header: str | None,
        signing_secret: str | None = None,
    ) -> bool:
        """Verify the X-Slack-Signature using HMAC-SHA256 and the raw request body.

        Args:
            raw_body: The unparsed raw HTTP request bytes.
            timestamp_header: Value of X-Slack-Request-Timestamp header.
            signature_header: Value of X-Slack-Signature header.
            signing_secret: Optional override, defaults to settings.SLACK_SIGNING_SECRET.

        Returns:
            True if signature is valid and within replay window.

        Raises:
            WebhookVerificationError: If headers are missing, timestamp is expired,
                or signature fails verification.
        """
        secret = signing_secret or settings.SLACK_SIGNING_SECRET
        if not secret:
            raise WebhookVerificationError("Slack signing secret is not configured on the server.")

        if not timestamp_header or not signature_header:
            msg = (
                "Missing Slack signature verification headers "
                "(X-Slack-Signature / X-Slack-Request-Timestamp)."
            )
            raise WebhookVerificationError(msg)

        try:
            ts = int(timestamp_header)
        except ValueError as exc:
            raise WebhookVerificationError("Invalid timestamp header format.") from exc

        # Reject requests older than 5 minutes (300 seconds) to prevent replay attacks
        now = int(time.time())
        if abs(now - ts) > 300:
            logger.warning("Slack webhook timestamp out of bounds: diff=%s", abs(now - ts))
            raise WebhookVerificationError("Slack request timestamp is expired or out of bounds.")

        verifier = SignatureVerifier(signing_secret=secret)
        body_str = raw_body.decode("utf-8", errors="replace")
        is_valid = verifier.is_valid(
            body=body_str,
            timestamp=timestamp_header,
            signature=signature_header,
        )

        if not is_valid:
            logger.warning("Slack signature verification failed.")
            raise WebhookVerificationError("Invalid Slack signature.")

        return True

    @classmethod
    async def record_inbound_event(
        cls,
        db: AsyncSession,
        event_payload: dict[str, Any],
    ) -> IntegrationEvent:
        """Atomically record inbound Slack event, enforcing deduplication.

        Args:
            db: Async database session.
            event_payload: Decoded JSON payload from Slack event request.

        Returns:
            The persisted IntegrationEvent record.

        Raises:
            WebhookReplayError: If the external_event_id has already been recorded.
        """
        event_id = event_payload.get("event_id")
        if not event_id:
            # Fallback for events without top-level event_id
            inner = event_payload.get("event", {})
            event_id = inner.get("event_ts") or inner.get("client_msg_id") or str(time.time())

        # Check if already processed
        stmt = select(IntegrationEvent).where(
            IntegrationEvent.provider == "slack",
            IntegrationEvent.external_event_id == event_id,
        )
        existing = await db.scalar(stmt)
        if existing is not None:
            logger.info("Ignoring duplicate Slack event: %s", event_id)
            raise WebhookReplayError(f"Duplicate event '{event_id}' already processed.")

        event_type = event_payload.get("event", {}).get("type") or event_payload.get(
            "type", "unknown"
        )

        # Sanitize summary payload — avoid storing entire message bodies or sensitive info
        inner_event = event_payload.get("event", {})
        summary = {
            "type": event_type,
            "team_id": event_payload.get("team_id"),
            "channel": inner_event.get("channel"),
            "user": inner_event.get("user"),
            "event_time": event_payload.get("event_time"),
        }

        record = IntegrationEvent(
            provider="slack",
            external_event_id=event_id,
            event_type=event_type,
            status=IntegrationEventStatus.RECEIVED,
            payload_summary=summary,
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        logger.info("Recorded Slack inbound event: id=%s, type=%s", event_id, event_type)
        return record
