"""External capability registry for LangGraph agents and idempotent execution."""

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger
from flowpilot.integrations.google.gmail import GmailClient
from flowpilot.integrations.google.sheets import GoogleSheetsClient
from flowpilot.integrations.security import compute_parameter_digest, decrypt_oauth_token
from flowpilot.integrations.slack.client import SlackClient
from flowpilot.integrations.whatsapp.client import WhatsAppClient
from flowpilot.models.external_action import ExternalAction, ExternalActionStatus
from flowpilot.models.integration_connection import (
    ConnectionStatus,
    IntegrationConnection,
)

logger = get_logger("integrations.registry")


class IntegrationExecutionError(Exception):
    """Base exception for integration tool execution failures."""


class ConnectionNotFoundError(IntegrationExecutionError):
    """Raised when the user has not connected the required external application."""


class ApprovalRequiredError(IntegrationExecutionError):
    """Raised when an external action requires approval that has not been granted."""


class ParameterTamperedError(IntegrationExecutionError):
    """Raised when action parameters modified after approval invalidate the decision."""


@dataclass(frozen=True)
class ExternalCapability:
    """Specification of an authorized external agent capability."""

    name: str
    description: str
    provider: str
    service: str
    required_scope: str | None
    requires_approval: bool
    handler: Callable[..., Awaitable[dict[str, Any]]]


EXTERNAL_CAPABILITIES: dict[str, ExternalCapability] = {}


def register_capability(cap: ExternalCapability) -> None:
    """Register an external capability specification."""
    EXTERNAL_CAPABILITIES[cap.name.lower()] = cap


# Helper to find user's active connection for a given provider and service
async def find_user_connection(
    db: AsyncSession,
    user_id: uuid.UUID,
    provider: str,
    service: str | None = None,
    connection_id: uuid.UUID | None = None,
) -> IntegrationConnection:
    """Locate the authenticated user's active connection for a provider.

    Strict user isolation: never queries connections belonging to other users.
    """
    if connection_id:
        stmt = select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.user_id == user_id,
        )
        conn = await db.scalar(stmt)
        if not conn:
            raise ConnectionNotFoundError(
                f"Connection '{connection_id}' not found for authenticated user."
            )
        return conn

    # Match by provider and optional service, prioritizing default connections
    stmt = (
        select(IntegrationConnection)
        .where(
            IntegrationConnection.user_id == user_id,
            IntegrationConnection.provider == provider.lower(),
            IntegrationConnection.status == ConnectionStatus.ACTIVE,
        )
        .order_by(
            IntegrationConnection.is_default.desc(),
            IntegrationConnection.updated_at.desc(),
        )
    )
    results = list((await db.scalars(stmt)).all())
    if not results:
        raise ConnectionNotFoundError(
            f"You have not connected your '{provider}' account. "
            "Please connect it in App Connections."
        )

    # Prefer connection matching service if specified
    if service:
        for r in results:
            if r.service == service:
                return r

    return results[0]


# ==============================================================================
# Capability Handlers with Idempotency and Audit Tracking
# ==============================================================================


async def _execute_with_action_audit(
    db: AsyncSession,
    user_id: uuid.UUID,
    operation: str,
    parameters: dict[str, Any],
    connection: IntegrationConnection | None,
    run_id: str | uuid.UUID | None,
    execution_fn: Callable[[], Awaitable[tuple[str | None, dict[str, Any]]]],
) -> dict[str, Any]:
    """Execute external action with idempotency enforcement and ExternalAction audit persistence."""
    material_params = {
        k: v
        for k, v in parameters.items()
        if k
        not in (
            "approved",
            "approval_parameter_digest",
            "approval_reference",
            "step_id",
            "idempotency_key",
            "run_id",
            "previous_results",
        )
    }

    # Enforce approval requirement and parameter integrity
    cap = EXTERNAL_CAPABILITIES.get(operation.lower())
    if cap and cap.requires_approval:
        if not parameters.get("approved"):
            raise ApprovalRequiredError(
                f"Action '{operation}' requires explicit human approval before execution."
            )
        expected_digest = parameters.get("approval_parameter_digest")
        if expected_digest:
            actual_digest = compute_parameter_digest(material_params)
            if actual_digest != expected_digest:
                raise ParameterTamperedError(
                    f"Parameter digest mismatch for '{operation}': "
                    "parameters were modified after approval."
                )

    digest = compute_parameter_digest(material_params)
    step_id = parameters.get("step_id", "step")

    # Idempotency key binds user, run, step, and operation
    custom_key = parameters.get("idempotency_key")
    if custom_key:
        idempotency_key = str(custom_key).strip()
    elif run_id:
        idempotency_key = f"{run_id}_{step_id}_{operation}_{digest[:12]}"
    else:
        idempotency_key = f"{user_id}_{operation}_{digest}"

    # Check for existing action with same idempotency key (replay / worker redelivery protection)
    check_stmt = select(ExternalAction).where(ExternalAction.idempotency_key == idempotency_key)
    existing_action = await db.scalar(check_stmt)
    if existing_action:
        if existing_action.status == ExternalActionStatus.SUCCEEDED:
            logger.info(
                "Idempotent replay: returning previously completed result for %s",
                idempotency_key,
            )
            return {
                "operation": operation,
                "status": "success",
                "idempotent_replay": True,
                "provider_action_id": existing_action.provider_action_id,
                "result": existing_action.provider_response,
            }
        if existing_action.status == ExternalActionStatus.EXECUTING:
            logger.warning("Action %s is already executing (concurrency conflict)", idempotency_key)
            raise IntegrationExecutionError(
                f"Action '{operation}' with key '{idempotency_key}' is already executing."
            )

    parsed_run_id = uuid.UUID(str(run_id)) if run_id else None

    # Record action in EXECUTING state
    action = ExternalAction(
        id=uuid.uuid4(),
        user_id=user_id,
        run_id=parsed_run_id,
        connection_id=connection.id if connection else None,
        operation=operation,
        parameter_digest=digest,
        idempotency_key=idempotency_key,
        status=ExternalActionStatus.EXECUTING,
        approval_reference=parameters.get("approval_reference"),
    )
    db.add(action)
    await db.commit()

    try:
        provider_action_id, response_data = await execution_fn()
        action.status = ExternalActionStatus.SUCCEEDED
        action.provider_action_id = provider_action_id
        action.provider_response = response_data
        action.completed_at = datetime.now(UTC)
        await db.commit()

        return {
            "operation": operation,
            "status": "success",
            "provider_action_id": provider_action_id,
            "result": response_data,
        }
    except Exception as exc:
        action.status = ExternalActionStatus.FAILED
        action.error_message = str(exc)
        action.completed_at = datetime.now(UTC)
        await db.commit()
        raise


# --- Gmail Capabilities ---


async def execute_gmail_list_messages(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: gmail_list_messages."""
    conn = await find_user_connection(db, user_id, "google", "gmail")
    query = parameters.get("query")
    max_results = int(parameters.get("max_results", 10))
    messages = await GmailClient.list_messages(db, conn, query=query, max_results=max_results)
    return {
        "operation": "gmail_list_messages",
        "result": {"messages": messages, "count": len(messages)},
    }


async def execute_gmail_get_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: gmail_get_message."""
    message_id = parameters.get("message_id")
    if not message_id:
        raise ValueError("Parameter 'message_id' is required.")
    conn = await find_user_connection(db, user_id, "google", "gmail")
    msg_data = await GmailClient.get_message(db, conn, message_id=str(message_id).strip())
    return {
        "operation": "gmail_get_message",
        "result": msg_data,
    }


async def execute_gmail_prepare_response(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: gmail_prepare_response."""
    recipient = parameters.get("recipient") or parameters.get("to", "")
    subject = parameters.get("subject", "")
    body = parameters.get("body") or parameters.get("response_text", "")
    in_reply_to = parameters.get("in_reply_to")

    return {
        "operation": "gmail_prepare_response",
        "status": "prepared",
        "result": {
            "recipient": recipient,
            "subject": subject,
            "body": body,
            "in_reply_to": in_reply_to,
            "notice": "Response prepared for review. Has not been sent.",
        },
    }


async def execute_gmail_create_draft(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: gmail_create_draft."""
    conn = await find_user_connection(db, user_id, "google", "gmail")
    recipient = parameters.get("recipient") or parameters.get("to")
    subject = parameters.get("subject", "")
    body = parameters.get("body", "")
    if not recipient or not body:
        raise ValueError(
            "Parameters 'recipient' (or 'to') and 'body' are required to create draft."
        )

    draft_res = await GmailClient.create_draft(
        db,
        conn,
        recipient=str(recipient),
        subject=str(subject),
        body_text=str(body),
        in_reply_to=parameters.get("in_reply_to"),
        references=parameters.get("references"),
    )
    return {
        "operation": "gmail_create_draft",
        "result": draft_res,
    }


async def execute_gmail_send_email(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: gmail_send_email (Requires Human Approval)."""
    conn = await find_user_connection(db, user_id, "google", "gmail")
    recipient = parameters.get("recipient") or parameters.get("to")
    subject = parameters.get("subject", "")
    body = parameters.get("body", "")
    if not recipient or not body:
        raise ValueError("Parameters 'recipient' (or 'to') and 'body' are required to send email.")

    run_id = parameters.get("run_id")

    async def _send():
        res = await GmailClient.send_email(
            db,
            conn,
            recipient=str(recipient),
            subject=str(subject),
            body_text=str(body),
            in_reply_to=parameters.get("in_reply_to"),
            references=parameters.get("references"),
        )
        return res.get("message_id"), res

    return await _execute_with_action_audit(
        db=db,
        user_id=user_id,
        operation="gmail_send_email",
        parameters=parameters,
        connection=conn,
        run_id=run_id,
        execution_fn=_send,
    )


# --- Slack Capabilities ---


async def execute_slack_list_channels(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: slack_list_channels."""
    conn = await find_user_connection(db, user_id, "slack")
    types = parameters.get("types", "public_channel,private_channel")
    limit = int(parameters.get("limit", 100))
    channels = await SlackClient.list_channels(db, conn, types=types, limit=limit)
    return {
        "operation": "slack_list_channels",
        "result": {"channels": channels, "count": len(channels)},
    }


async def execute_slack_prepare_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: slack_prepare_message."""
    channel = parameters.get("channel", "")
    text = parameters.get("text", "")
    blocks = parameters.get("blocks")
    res = await SlackClient.prepare_message(channel=str(channel), text=str(text), blocks=blocks)
    return {
        "operation": "slack_prepare_message",
        "result": res,
    }


async def execute_slack_send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: slack_send_message (Requires Human Approval)."""
    conn = await find_user_connection(db, user_id, "slack")
    channel = parameters.get("channel")
    text = parameters.get("text", "")
    blocks = parameters.get("blocks")
    thread_ts = parameters.get("thread_ts")
    if not channel or (not text and not blocks):
        raise ValueError("Target 'channel' and 'text' or 'blocks' are required for Slack message.")

    run_id = parameters.get("run_id")

    async def _post():
        res = await SlackClient.send_message(
            db,
            conn,
            channel=str(channel),
            text=str(text),
            blocks=blocks,
            thread_ts=thread_ts,
        )
        return res.get("ts"), res

    return await _execute_with_action_audit(
        db=db,
        user_id=user_id,
        operation="slack_send_message",
        parameters=parameters,
        connection=conn,
        run_id=run_id,
        execution_fn=_post,
    )


# --- Google Sheets Capabilities ---


async def execute_sheets_read_range(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: sheets_read_range."""
    conn = await find_user_connection(db, user_id, "google", "sheets")
    spreadsheet_id = parameters.get("spreadsheet_id")
    range_name = parameters.get("range") or parameters.get("range_name")
    if not spreadsheet_id or not range_name:
        raise ValueError("Parameters 'spreadsheet_id' and 'range' are required.")

    res = await GoogleSheetsClient.read_range(
        db,
        conn,
        spreadsheet_id=str(spreadsheet_id),
        range_name=str(range_name),
    )
    return {
        "operation": "sheets_read_range",
        "result": res,
    }


async def execute_sheets_append_rows(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: sheets_append_rows (Requires Human Approval)."""
    conn = await find_user_connection(db, user_id, "google", "sheets")
    spreadsheet_id = parameters.get("spreadsheet_id")
    range_name = parameters.get("range") or parameters.get("range_name")
    values = parameters.get("values") or parameters.get("rows")
    if not spreadsheet_id or not range_name or not values:
        raise ValueError("Parameters 'spreadsheet_id', 'range', and 'values' are required.")

    run_id = parameters.get("run_id")

    async def _append():
        res = await GoogleSheetsClient.append_rows(
            db,
            conn,
            spreadsheet_id=str(spreadsheet_id),
            range_name=str(range_name),
            values=values,
        )
        return res.get("updated_range"), res

    return await _execute_with_action_audit(
        db=db,
        user_id=user_id,
        operation="sheets_append_rows",
        parameters=parameters,
        connection=conn,
        run_id=run_id,
        execution_fn=_append,
    )


# --- WhatsApp Capabilities ---


async def execute_whatsapp_send_message(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: whatsapp_send_message (MANDATES HUMAN APPROVAL)."""
    settings = get_settings()

    recipient = parameters.get("recipient") or parameters.get("to")
    text = parameters.get("message") or parameters.get("text") or parameters.get("body")
    preview_url = bool(parameters.get("preview_url", False))
    if not recipient or not text:
        raise ValueError("Parameters 'recipient' (phone number) and 'text'/'message' are required.")

    norm_recipient = WhatsAppClient.normalize_phone_number(str(recipient))

    conn: IntegrationConnection | None = None
    try:
        conn = await find_user_connection(db, user_id, "whatsapp")
    except ConnectionNotFoundError:
        conn = None

    phone_number_id = None
    access_token = None
    graph_version = None

    if conn and conn.status == ConnectionStatus.ACTIVE:
        phone_number_id = conn.external_account_id or conn.metadata_json.get("phone_number_id")
        if conn.encrypted_access_token:
            access_token = decrypt_oauth_token(conn.encrypted_access_token)
        graph_version = conn.metadata_json.get("graph_api_version", "v21.0")
    elif not settings.is_production and settings.is_whatsapp_configured:
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        access_token = settings.WHATSAPP_ACCESS_TOKEN
        graph_version = settings.WHATSAPP_GRAPH_API_VERSION or "v21.0"
    else:
        raise IntegrationExecutionError(
            "WhatsApp Business is not connected. "
            "Please configure your WhatsApp Business Cloud API credentials in App Connections."
        )

    run_id = parameters.get("run_id")

    async def _send():
        res = await WhatsAppClient.send_text_message(
            recipient=norm_recipient,
            text=str(text),
            preview_url=preview_url,
            phone_number_id=phone_number_id,
            access_token=access_token,
            graph_version=graph_version,
        )
        return res.get("message_id"), res

    return await _execute_with_action_audit(
        db=db,
        user_id=user_id,
        operation="whatsapp_send_message",
        parameters=parameters,
        connection=conn,
        run_id=run_id,
        execution_fn=_send,
    )


async def execute_whatsapp_send_template(
    db: AsyncSession,
    user_id: uuid.UUID,
    parameters: dict[str, Any],
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    """Capability: whatsapp_send_template (MANDATES HUMAN APPROVAL)."""
    settings = get_settings()

    recipient = parameters.get("recipient") or parameters.get("to")
    template_name = parameters.get("template_name") or parameters.get("template")
    language_code = parameters.get("language_code") or parameters.get("language") or "en_US"
    components = parameters.get("components")

    if not recipient or not template_name:
        raise ValueError("Parameters 'recipient' (phone number) and 'template_name' are required.")

    norm_recipient = WhatsAppClient.normalize_phone_number(str(recipient))

    conn: IntegrationConnection | None = None
    try:
        conn = await find_user_connection(db, user_id, "whatsapp")
    except ConnectionNotFoundError:
        conn = None

    phone_number_id = None
    access_token = None
    graph_version = None

    if conn and conn.status == ConnectionStatus.ACTIVE:
        phone_number_id = conn.external_account_id or conn.metadata_json.get("phone_number_id")
        if conn.encrypted_access_token:
            access_token = decrypt_oauth_token(conn.encrypted_access_token)
        graph_version = conn.metadata_json.get("graph_api_version", "v21.0")
    elif not settings.is_production and settings.is_whatsapp_configured:
        phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        access_token = settings.WHATSAPP_ACCESS_TOKEN
        graph_version = settings.WHATSAPP_GRAPH_API_VERSION or "v21.0"
    else:
        raise IntegrationExecutionError(
            "WhatsApp Business is not connected. "
            "Please configure your WhatsApp Business Cloud API credentials in App Connections."
        )

    run_id = parameters.get("run_id")

    async def _send_template():
        res = await WhatsAppClient.send_template_message(
            recipient=norm_recipient,
            template_name=str(template_name),
            language_code=str(language_code),
            components=components,
            phone_number_id=phone_number_id,
            access_token=access_token,
            graph_version=graph_version,
        )
        return res.get("message_id"), res

    return await _execute_with_action_audit(
        db=db,
        user_id=user_id,
        operation="whatsapp_send_template",
        parameters=parameters,
        connection=conn,
        run_id=run_id,
        execution_fn=_send_template,
    )


# ==============================================================================
# Capability Registrations
# ==============================================================================

register_capability(
    ExternalCapability(
        name="gmail_list_messages",
        description="Search and list recent emails in the connected Gmail account.",
        provider="google",
        service="gmail",
        required_scope="https://www.googleapis.com/auth/gmail.readonly",
        requires_approval=False,
        handler=execute_gmail_list_messages,
    )
)
register_capability(
    ExternalCapability(
        name="gmail_get_message",
        description="Retrieve full email content and metadata with prompt-injection defense.",
        provider="google",
        service="gmail",
        required_scope="https://www.googleapis.com/auth/gmail.readonly",
        requires_approval=False,
        handler=execute_gmail_get_message,
    )
)
register_capability(
    ExternalCapability(
        name="gmail_prepare_response",
        description="Format and prepare an email response without sending it.",
        provider="google",
        service="gmail",
        required_scope=None,
        requires_approval=False,
        handler=execute_gmail_prepare_response,
    )
)
register_capability(
    ExternalCapability(
        name="gmail_create_draft",
        description="Create an email draft in the connected Gmail account.",
        provider="google",
        service="gmail",
        required_scope="https://www.googleapis.com/auth/gmail.compose",
        requires_approval=False,
        handler=execute_gmail_create_draft,
    )
)
register_capability(
    ExternalCapability(
        name="gmail_send_email",
        description="Send an email through the user's Gmail account (MANDATES HUMAN APPROVAL).",
        provider="google",
        service="gmail",
        required_scope="https://www.googleapis.com/auth/gmail.send",
        requires_approval=True,
        handler=execute_gmail_send_email,
    )
)

register_capability(
    ExternalCapability(
        name="slack_list_channels",
        description="List accessible public and private channels in the connected Slack workspace.",
        provider="slack",
        service="slack",
        required_scope="channels:read",
        requires_approval=False,
        handler=execute_slack_list_channels,
    )
)
register_capability(
    ExternalCapability(
        name="slack_prepare_message",
        description="Prepare a Slack message payload for human review.",
        provider="slack",
        service="slack",
        required_scope=None,
        requires_approval=False,
        handler=execute_slack_prepare_message,
    )
)
register_capability(
    ExternalCapability(
        name="slack_send_message",
        description="Post a message to a Slack channel (MANDATES HUMAN APPROVAL).",
        provider="slack",
        service="slack",
        required_scope="chat:write",
        requires_approval=True,
        handler=execute_slack_send_message,
    )
)

register_capability(
    ExternalCapability(
        name="sheets_read_range",
        description="Read cell values from a designated range in a Google Spreadsheet.",
        provider="google",
        service="sheets",
        required_scope="https://www.googleapis.com/auth/spreadsheets",
        requires_approval=False,
        handler=execute_sheets_read_range,
    )
)
register_capability(
    ExternalCapability(
        name="sheets_append_rows",
        description=(
            "Append rows to a Google Spreadsheet with formula injection protection "
            "(MANDATES HUMAN APPROVAL)."
        ),
        provider="google",
        service="sheets",
        required_scope="https://www.googleapis.com/auth/spreadsheets",
        requires_approval=True,
        handler=execute_sheets_append_rows,
    )
)

register_capability(
    ExternalCapability(
        name="whatsapp_send_message",
        description=(
            "Send a customer-service WhatsApp message to a recipient phone number "
            "(MANDATES HUMAN APPROVAL)."
        ),
        provider="whatsapp",
        service="whatsapp",
        required_scope="whatsapp_business_messaging",
        requires_approval=True,
        handler=execute_whatsapp_send_message,
    )
)
register_capability(
    ExternalCapability(
        name="whatsapp_send_template",
        description=(
            "Send an approved WhatsApp template message to a recipient phone number "
            "(MANDATES HUMAN APPROVAL)."
        ),
        provider="whatsapp",
        service="whatsapp",
        required_scope="whatsapp_business_messaging",
        requires_approval=True,
        handler=execute_whatsapp_send_template,
    )
)
