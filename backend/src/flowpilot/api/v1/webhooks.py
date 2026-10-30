"""FastAPI webhook router for inbound integration events with raw-body signature validation."""

import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.logging import get_logger
from flowpilot.db.session import get_db
from flowpilot.integrations.slack.events import (
    SlackEventHandler,
    WebhookReplayError,
    WebhookVerificationError,
)

logger = get_logger("api.v1.webhooks")
router = APIRouter(prefix="/webhooks", tags=["Integration Webhooks"])


@router.post(
    "/slack",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound Slack Events API webhooks",
    description=(
        "Verifies X-Slack-Signature using raw request bytes, handles URL verification challenges, "
        "and deduplicates events."
    ),
)
async def slack_events_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_slack_signature: Annotated[str | None, Header()] = None,
    x_slack_request_timestamp: Annotated[str | None, Header()] = None,
) -> Any:
    """Handle inbound Slack event delivery with signature validation and deduplication."""
    # 1. Read raw body bytes for cryptographic HMAC verification
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty webhook request body.",
        )

    # 2. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON in webhook request body.",
        ) from exc

    # 3. Handle Slack URL verification challenge (issued during webhook configuration)
    if payload.get("type") == "url_verification":
        # Always verify signature on challenges if headers are supplied
        if x_slack_signature and x_slack_request_timestamp:
            try:
                SlackEventHandler.verify_slack_signature(
                    raw_body=raw_body,
                    timestamp_header=x_slack_request_timestamp,
                    signature_header=x_slack_signature,
                )
            except WebhookVerificationError as exc:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail=str(exc),
                ) from exc

        challenge = payload.get("challenge")
        return Response(
            content=json.dumps({"challenge": challenge}),
            media_type="application/json",
            status_code=status.HTTP_200_OK,
        )

    # 4. Enforce HMAC-SHA256 signature verification on all event notifications
    try:
        SlackEventHandler.verify_slack_signature(
            raw_body=raw_body,
            timestamp_header=x_slack_request_timestamp,
            signature_header=x_slack_signature,
        )
    except WebhookVerificationError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    # 5. Enforce event deduplication via IntegrationEvent record
    try:
        record = await SlackEventHandler.record_inbound_event(db=db, event_payload=payload)
        return {
            "ok": True,
            "event_id": record.external_event_id,
            "status": "received",
        }
    except WebhookReplayError:
        # Acknowledge duplicate cleanly so Slack does not continue retrying
        return {
            "ok": True,
            "status": "ignored_duplicate",
        }


@router.get(
    "/whatsapp",
    status_code=status.HTTP_200_OK,
    summary="Meta WhatsApp webhook subscription verification challenge",
    description=(
        "Validates hub.verify_token and returns hub.challenge as required by Meta Cloud API."
    ),
)
async def whatsapp_webhook_verification(
    hub_mode: Annotated[str | None, Query(alias="hub.mode")] = None,
    hub_verify_token: Annotated[str | None, Query(alias="hub.verify_token")] = None,
    hub_challenge: Annotated[str | None, Query(alias="hub.challenge")] = None,
) -> Response:
    """Handle Meta WhatsApp Webhook verification handshake."""
    from flowpilot.integrations.whatsapp.events import (
        WebhookVerificationError as WhatsAppWebhookVerificationError,
    )
    from flowpilot.integrations.whatsapp.events import (
        WhatsAppEventHandler,
    )

    try:
        challenge = WhatsAppEventHandler.verify_challenge(
            mode=hub_mode,
            verify_token=hub_verify_token,
            challenge=hub_challenge,
        )
        return Response(content=challenge, media_type="text/plain", status_code=status.HTTP_200_OK)
    except WhatsAppWebhookVerificationError as exc:
        logger.warning("WhatsApp webhook verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


@router.post(
    "/whatsapp",
    status_code=status.HTTP_200_OK,
    summary="Receive inbound Meta WhatsApp Cloud API events",
    description=(
        "Verifies X-Hub-Signature-256 HMAC-SHA256, tracks delivery states (sent, delivered, "
        "read, failed), and deduplicates events."
    ),
)
async def whatsapp_events_webhook(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    x_hub_signature_256: Annotated[str | None, Header(alias="X-Hub-Signature-256")] = None,
) -> Any:
    """Handle inbound WhatsApp event and status deliveries with cryptographic verification."""
    from flowpilot.integrations.whatsapp.events import (
        WebhookVerificationError as WhatsAppWebhookVerificationError,
    )
    from flowpilot.integrations.whatsapp.events import (
        WhatsAppEventHandler,
    )

    # 1. Read raw body bytes for cryptographic HMAC verification
    raw_body = await request.body()
    if not raw_body:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty webhook request body.",
        )

    # 2. Parse JSON payload
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed JSON in webhook request body.",
        ) from exc

    # 3. Enforce HMAC-SHA256 signature verification via Meta App Secret
    try:
        WhatsAppEventHandler.verify_signature(
            raw_body=raw_body,
            signature_header=x_hub_signature_256,
        )
    except WhatsAppWebhookVerificationError as exc:
        logger.warning("WhatsApp webhook signature verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc

    # 4. Process event and update delivery status atomically
    result = await WhatsAppEventHandler.process_inbound_webhook(
        db=db,
        payload=payload,
    )

    return {
        "ok": True,
        "status": "processed",
        "details": result,
    }
