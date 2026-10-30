"""WhatsApp event webhook handler, cryptographic signature verification, and deduplication."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.integrations.whatsapp.client import (
    WhatsAppClient,
    WhatsAppConfigurationError,
    WhatsAppValidationError,
)
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.integration_event import IntegrationEvent, IntegrationEventStatus

logger = get_logger("integrations.whatsapp.events")
settings = get_settings()


class WebhookVerificationError(Exception):
    """Raised when an inbound webhook fails cryptographic signature verification."""


class WebhookReplayError(Exception):
    """Raised when an inbound webhook has already been processed (duplicate delivery)."""


class WhatsAppEventHandler:
    """Verifies and processes inbound Meta WhatsApp Cloud API webhooks."""

    @classmethod
    def verify_challenge(
        cls,
        mode: str | None,
        verify_token: str | None,
        challenge: str | None,
    ) -> str:
        """Validate Meta webhook subscription verification challenge.

        Meta calls GET on the webhook URL with:
          - hub.mode = "subscribe"
          - hub.verify_token = <configured verify token>
          - hub.challenge = <random challenge string/int>

        Returns:
            The challenge string to return directly to Meta.

        Raises:
            WebhookVerificationError: If mode or token is invalid.
        """
        expected_token = settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN
        if not expected_token:
            logger.error("WHATSAPP_WEBHOOK_VERIFY_TOKEN is not configured on the server.")
            raise WebhookVerificationError("Webhook verify token is not configured on the server.")

        if mode != "subscribe":
            logger.warning("Invalid webhook verification mode: %s", mode)
            raise WebhookVerificationError(f"Invalid mode '{mode}'. Expected 'subscribe'.")

        if verify_token != expected_token:
            logger.warning("Meta webhook verify_token mismatch.")
            raise WebhookVerificationError("Verify token mismatch.")

        if not challenge:
            raise WebhookVerificationError("Missing hub.challenge in verification request.")

        logger.info("Meta webhook verification challenge successfully validated.")
        return str(challenge)

    @classmethod
    def verify_signature(
        cls,
        raw_body: bytes,
        signature_header: str | None,
        app_secret: str | None = None,
    ) -> bool:
        """Verify the X-Hub-Signature-256 header using raw request bytes."""
        try:
            is_valid = WhatsAppClient.verify_webhook_signature(
                raw_body=raw_body,
                signature_header=signature_header,
                app_secret=app_secret,
            )
            if not is_valid:
                logger.warning("Meta X-Hub-Signature-256 verification failed.")
                raise WebhookVerificationError("Invalid X-Hub-Signature-256 signature.")
            return True
        except WhatsAppConfigurationError as exc:
            raise WebhookVerificationError(str(exc)) from exc
        except WhatsAppValidationError as exc:
            raise WebhookVerificationError(str(exc)) from exc

    @classmethod
    async def process_inbound_webhook(
        cls,
        db: AsyncSession,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Atomically process incoming WhatsApp webhook notification.

        Handles:
        1. Message delivery status updates (sent, delivered, read, failed).
        2. Deduplication via IntegrationEvent records.
        3. Updates corresponding ExternalAction record with delivery state and timestamps.
        4. Inbound customer message receipt with sanitized privacy-preserving metadata.
        """
        processed_statuses = 0
        processed_messages = 0
        duplicate_events = 0

        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                statuses = value.get("statuses", [])
                messages = value.get("messages", [])

                # 1. Process delivery status updates
                for st in statuses:
                    wamid = st.get("id")
                    status_name = st.get("status", "unknown")
                    timestamp = st.get("timestamp")
                    recipient_id = st.get("recipient_id")
                    errors = st.get("errors")

                    if not wamid:
                        continue

                    event_dedup_id = f"{wamid}_{status_name}"

                    # Check deduplication
                    stmt = select(IntegrationEvent).where(
                        IntegrationEvent.provider == "whatsapp",
                        IntegrationEvent.external_event_id == event_dedup_id,
                    )
                    existing_ev = await db.scalar(stmt)
                    if existing_ev is not None:
                        duplicate_events += 1
                        continue

                    # Record status in IntegrationEvent
                    event_record = IntegrationEvent(
                        provider="whatsapp",
                        external_event_id=event_dedup_id,
                        event_type=f"status_{status_name}",
                        status=IntegrationEventStatus.RECEIVED,
                        payload_summary={
                            "wamid": wamid,
                            "status": status_name,
                            "recipient_id": recipient_id,
                            "timestamp": timestamp,
                            "errors": errors,
                        },
                    )
                    db.add(event_record)

                    # Update associated ExternalAction audit record if found
                    action_stmt = select(ExternalAction).where(
                        ExternalAction.provider_action_id == wamid
                    )
                    action = await db.scalar(action_stmt)
                    if action:
                        current_resp = dict(action.provider_response or {})
                        current_resp["delivery_status"] = status_name
                        current_resp["delivery_timestamp"] = timestamp
                        if errors:
                            current_resp["delivery_errors"] = errors
                        action.provider_response = current_resp

                        if status_name == "failed":
                            action.status = ExternalActionStatus.FAILED
                            err_msg = (
                                errors[0].get("title", "Unknown error")
                                if errors
                                else "Delivery failed per Meta webhook."
                            )
                            action.error_message = f"WhatsApp delivery failed: {err_msg}"
                        elif status_name in ("delivered", "read"):
                            action.completed_at = datetime.now(UTC)

                        logger.info(
                            "Updated ExternalAction [%s] delivery status to '%s'",
                            action.id,
                            status_name,
                        )

                    processed_statuses += 1

                # 2. Process inbound customer messages
                for msg in messages:
                    msg_id = msg.get("id")
                    sender = msg.get("from")
                    msg_type = msg.get("type", "unknown")
                    timestamp = msg.get("timestamp")

                    if not msg_id:
                        continue

                    # Deduplication check
                    stmt = select(IntegrationEvent).where(
                        IntegrationEvent.provider == "whatsapp",
                        IntegrationEvent.external_event_id == msg_id,
                    )
                    existing_msg = await db.scalar(stmt)
                    if existing_msg is not None:
                        duplicate_events += 1
                        continue

                    # Avoid unnecessary retention of personal message bodies; store metadata
                    msg_event = IntegrationEvent(
                        provider="whatsapp",
                        external_event_id=msg_id,
                        event_type="incoming_message",
                        status=IntegrationEventStatus.RECEIVED,
                        payload_summary={
                            "sender": sender,
                            "type": msg_type,
                            "timestamp": timestamp,
                        },
                    )
                    db.add(msg_event)
                    processed_messages += 1

        await db.commit()
        return {
            "processed_statuses": processed_statuses,
            "processed_messages": processed_messages,
            "duplicate_events": duplicate_events,
        }
