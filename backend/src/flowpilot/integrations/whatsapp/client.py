"""Meta WhatsApp Business Platform (Cloud API) client adapter.

Provides asynchronous HTTP integration with Meta's official Graph API for:
- Free-form text customer service messages (within 24h messaging window)
- Meta-approved template messages
- Phone number ID validation and metadata discovery
- Destination phone number normalization (E.164 without leading '+')
- Cryptographic webhook signature verification (HMAC-SHA256)
- Normalized error classification and bounded retries
"""

import asyncio
import hashlib
import hmac
import re
from typing import Any

import httpx

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger

logger = get_logger("integrations.whatsapp.client")
settings = get_settings()

E164_REGEX = re.compile(r"^\d{7,15}$")


class WhatsAppError(Exception):
    """Base exception for WhatsApp Cloud API operations."""


class WhatsAppConfigurationError(WhatsAppError):
    """Raised when required WhatsApp deployment settings are missing."""


class WhatsAppAuthenticationError(WhatsAppError):
    """Raised when Meta rejects credentials, token is expired, or permissions are insufficient."""


class WhatsAppRateLimitError(WhatsAppError):
    """Raised when Meta API rate limits or throughput thresholds are exceeded."""


class WhatsAppMessagingWindowError(WhatsAppError):
    """Raised when free-form text is attempted outside the 24-hour customer service window."""


class WhatsAppRecipientError(WhatsAppError):
    """Raised when the destination phone number is invalid, unregistered, or blocked."""


class WhatsAppValidationError(WhatsAppError):
    """Raised when input parameters (e.g. phone format, template fields) fail validation."""


class WhatsAppNetworkTimeoutError(WhatsAppError):
    """Raised when network connectivity to Meta Graph API times out."""


class WhatsAppClient:
    """Asynchronous client adapter for Meta WhatsApp Business Cloud API."""

    DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)
    MAX_RETRIES = 2
    RETRY_BACKOFF = 1.0

    @classmethod
    def normalize_phone_number(cls, phone: str) -> str:
        """Normalize destination phone number to Meta's expected format (digits only, no '+').

        E.164 international standard requires country code followed by national number
        (7-15 digits). Meta Cloud API requires digits only without a leading '+' sign.

        Args:
            phone: Raw input phone number (e.g., '+1 (555) 012-3456' or '15550123456').

        Returns:
            Normalized digits-only string (e.g., '15550123456').

        Raises:
            WhatsAppValidationError: If phone number is empty, lacks digits, or violates E.164.
        """
        if not phone or not isinstance(phone, str):
            raise WhatsAppValidationError("Destination phone number must be a non-empty string.")

        # Remove leading '+', spaces, hyphens, parentheses, and dots
        cleaned = re.sub(r"[\s\-\(\)\.]", "", phone.strip())
        if cleaned.startswith("+"):
            cleaned = cleaned[1:]

        if not cleaned.isdigit():
            raise WhatsAppValidationError(
                f"Phone number '{phone}' contains non-digit characters. "
                "Destination must include country code with digits only."
            )

        if not E164_REGEX.match(cleaned):
            raise WhatsAppValidationError(
                f"Phone number '{phone}' (normalized: '{cleaned}') is invalid. "
                "E.164 standard requires 7 to 15 digits including country code."
            )

        return cleaned

    @classmethod
    def verify_webhook_signature(
        cls,
        raw_body: bytes,
        signature_header: str | None,
        app_secret: str | None = None,
    ) -> bool:
        """Verify Meta's X-Hub-Signature-256 HMAC-SHA256 signature using raw request bytes.

        Args:
            raw_body: Raw unparsed bytes of the incoming HTTP request body.
            signature_header: Header value of X-Hub-Signature-256 (format: 'sha256={hash}').
            app_secret: Meta App Secret. Defaults to settings.WHATSAPP_APP_SECRET.

        Returns:
            True if signature is valid.

        Raises:
            WhatsAppValidationError: If secret or header is missing or format is invalid.
        """
        secret = app_secret or settings.WHATSAPP_APP_SECRET
        if not secret:
            raise WhatsAppConfigurationError("WHATSAPP_APP_SECRET is not configured on the server.")

        if not signature_header:
            raise WhatsAppValidationError("Missing required 'X-Hub-Signature-256' header.")

        if not signature_header.startswith("sha256="):
            raise WhatsAppValidationError(
                "Invalid 'X-Hub-Signature-256' header format. Expected 'sha256=<hex>'."
            )

        expected_hash = signature_header[len("sha256=") :]
        computed_hash = hmac.new(
            key=secret.encode("utf-8"),
            msg=raw_body,
            digestmod=hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(computed_hash, expected_hash)

    @classmethod
    def _get_credentials(
        cls,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        graph_version: str | None = None,
    ) -> tuple[str, str, str]:
        """Resolve active credentials from arguments or environment settings."""
        pid = phone_number_id or settings.WHATSAPP_PHONE_NUMBER_ID
        token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        version = graph_version or settings.WHATSAPP_GRAPH_API_VERSION or "v21.0"

        if not pid:
            raise WhatsAppConfigurationError(
                "WhatsApp Phone Number ID is not configured (WHATSAPP_PHONE_NUMBER_ID)."
            )
        if not token:
            raise WhatsAppConfigurationError(
                "WhatsApp Access Token is not configured (WHATSAPP_ACCESS_TOKEN)."
            )

        return pid, token, version

    @classmethod
    def _normalize_meta_error(cls, status_code: int, error_data: dict[str, Any]) -> WhatsAppError:
        """Translate Meta Graph API error codes into descriptive exceptions."""
        code = error_data.get("code")
        subcode = error_data.get("error_subcode")
        message = error_data.get("message", "Unknown Meta API error")
        details = error_data.get("error_data", {}).get("details", "")

        err_summary = f"{message} (code: {code}, subcode: {subcode})"
        if details:
            err_summary = f"{err_summary} - {details}"

        # Authentication / Token expired / Permissions
        if status_code == 401 or code in (190, 102, 10, 200):
            return WhatsAppAuthenticationError(
                f"Meta WhatsApp authentication failed: {err_summary}"
            )

        # Rate Limiting
        if status_code == 429 or code in (80007, 130429, 4):
            return WhatsAppRateLimitError(f"Meta WhatsApp rate limit reached: {err_summary}")

        # 24-hour Customer Service Window Expired
        # Meta returns 131030 / 131047 / 131026 for messages outside customer window
        if code in (131030, 131047, 131026) or subcode in (131030, 131047, 131026):
            return WhatsAppMessagingWindowError(
                "Cannot send free-form text: More than 24 hours have elapsed since the user last "
                "messaged your WhatsApp Business number. You must use an approved Meta template. "
                f"Details: {err_summary}"
            )

        # Invalid or Unregistered Recipient
        if code in (131008, 131009, 131021) or (code == 100 and "recipient" in message.lower()):
            return WhatsAppRecipientError(
                f"Invalid or ineligible WhatsApp recipient: {err_summary}"
            )

        # Parameter validation error
        if status_code == 400 or code == 100:
            return WhatsAppValidationError(f"Invalid WhatsApp message parameters: {err_summary}")

        return WhatsAppError(f"Meta WhatsApp API error [{status_code}]: {err_summary}")

    @classmethod
    async def _post_with_retry(
        cls,
        url: str,
        payload: dict[str, Any],
        access_token: str,
    ) -> dict[str, Any]:
        """Perform POST request against Meta Cloud API with bounded retries for transient faults."""
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

        last_exc: Exception | None = None
        for attempt in range(cls.MAX_RETRIES + 1):
            try:
                async with httpx.AsyncClient(timeout=cls.DEFAULT_TIMEOUT) as client:
                    resp = await client.post(url, json=payload, headers=headers)

                if resp.is_success:
                    return resp.json()

                # Parse Meta JSON error
                try:
                    data = resp.json()
                    error_data = data.get("error", {})
                except Exception:
                    error_data = {"message": resp.text}

                # If server error (500, 502, 503, 504), retry with backoff
                if resp.status_code in (500, 502, 503, 504) and attempt < cls.MAX_RETRIES:
                    backoff = cls.RETRY_BACKOFF * (2**attempt)
                    logger.warning(
                        "Meta API 5xx error (%d) on attempt %d. Retrying in %.1fs...",
                        resp.status_code,
                        attempt + 1,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue

                # Raise structured exception on non-retriable failure
                raise cls._normalize_meta_error(resp.status_code, error_data)

            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < cls.MAX_RETRIES:
                    backoff = cls.RETRY_BACKOFF * (2**attempt)
                    logger.warning(
                        "Meta API timeout on attempt %d. Retrying in %.1fs...", attempt + 1, backoff
                    )
                    await asyncio.sleep(backoff)
                    continue
                raise WhatsAppNetworkTimeoutError(
                    f"Request to Meta WhatsApp Cloud API timed out after "
                    f"{cls.MAX_RETRIES + 1} attempts."
                ) from exc
            except (WhatsAppError, WhatsAppValidationError):
                raise
            except Exception as exc:
                logger.error("Unexpected error calling Meta WhatsApp API: %s", exc)
                raise WhatsAppError(f"WhatsApp API request failed: {exc}") from exc

        if last_exc:
            raise WhatsAppNetworkTimeoutError("Meta WhatsApp API request timed out.") from last_exc
        raise WhatsAppError("WhatsApp request failed after maximum retries.")

    @classmethod
    async def send_text_message(
        cls,
        recipient: str,
        text: str,
        preview_url: bool = False,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        graph_version: str | None = None,
    ) -> dict[str, Any]:
        """Send a free-form customer-service text message via Meta Cloud API.

        NOTE: Meta strictly limits free-form text messages to within 24 hours of the user's
        last inbound message. Attempting to send text outside this window will fail with
        error code 131030 (WhatsAppMessagingWindowError).

        Args:
            recipient: Destination phone number in E.164 format.
            text: Message body text (max 4096 characters per Meta specification).
            preview_url: Whether to generate link preview if URL is present.
            phone_number_id: Optional override for WhatsApp Phone Number ID.
            access_token: Optional override for access token.
            graph_version: Optional override for Graph API version.

        Returns:
            Normalized dictionary containing 'message_id', 'recipient', and 'status'.
        """
        norm_recipient = cls.normalize_phone_number(recipient)
        clean_text = text.strip() if text else ""
        if not clean_text:
            raise WhatsAppValidationError("Message body text cannot be empty.")
        if len(clean_text) > 4096:
            raise WhatsAppValidationError(
                f"Message body exceeds Meta limit of 4096 characters (length: {len(clean_text)})."
            )

        pid, token, version = cls._get_credentials(phone_number_id, access_token, graph_version)
        url = f"https://graph.facebook.com/{version}/{pid}/messages"

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": norm_recipient,
            "type": "text",
            "text": {
                "preview_url": bool(preview_url),
                "body": clean_text,
            },
        }

        logger.info(
            "Sending WhatsApp text message to recipient %s...%s [phone_id=%s]",
            norm_recipient[:3],
            norm_recipient[-4:] if len(norm_recipient) >= 7 else "",
            pid,
        )

        resp_data = await cls._post_with_retry(url, payload, token)

        # Meta success format: {"messaging_product": "whatsapp", "messages": [{"id": "wamid..."}]}
        messages = resp_data.get("messages", [])
        message_id = messages[0].get("id") if messages else None
        if not message_id:
            logger.warning("Meta accepted message but returned no message_id: %s", resp_data)

        return {
            "message_id": message_id,
            "recipient": norm_recipient,
            "status": "accepted",
            "messaging_product": "whatsapp",
            "type": "text",
            "raw_response": resp_data,
        }

    @classmethod
    async def send_template_message(
        cls,
        recipient: str,
        template_name: str,
        language_code: str = "en_US",
        components: list[dict[str, Any]] | None = None,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        graph_version: str | None = None,
    ) -> dict[str, Any]:
        """Send a pre-approved Meta WhatsApp template message.

        Template messages can be sent at any time with prior user opt-in/consent,
        even outside the 24-hour customer service window. Template approval is managed
        directly within Meta Business Suite.

        Args:
            recipient: Destination phone number in E.164 format.
            template_name: Exact name of the approved template in Meta Business Manager.
            language_code: Language code (e.g. 'en_US', 'es_LA').
            components: Optional parameter list (e.g. header, body, button parameters).
            phone_number_id: Optional override for WhatsApp Phone Number ID.
            access_token: Optional override for access token.
            graph_version: Optional override for Graph API version.

        Returns:
            Normalized dictionary containing message_id, recipient, template_name, and status.
        """
        norm_recipient = cls.normalize_phone_number(recipient)
        clean_template = template_name.strip() if template_name else ""
        if not clean_template:
            raise WhatsAppValidationError("Template name cannot be empty.")

        clean_lang = language_code.strip() if language_code else "en_US"

        pid, token, version = cls._get_credentials(phone_number_id, access_token, graph_version)
        url = f"https://graph.facebook.com/{version}/{pid}/messages"

        template_payload: dict[str, Any] = {
            "name": clean_template,
            "language": {"code": clean_lang},
        }
        if components:
            template_payload["components"] = components

        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": norm_recipient,
            "type": "template",
            "template": template_payload,
        }

        logger.info(
            "Sending WhatsApp template '%s' (%s) to recipient %s...%s [phone_id=%s]",
            clean_template,
            clean_lang,
            norm_recipient[:3],
            norm_recipient[-4:] if len(norm_recipient) >= 7 else "",
            pid,
        )

        resp_data = await cls._post_with_retry(url, payload, token)

        messages = resp_data.get("messages", [])
        message_id = messages[0].get("id") if messages else None

        return {
            "message_id": message_id,
            "recipient": norm_recipient,
            "template_name": clean_template,
            "language_code": clean_lang,
            "status": "accepted",
            "messaging_product": "whatsapp",
            "type": "template",
            "raw_response": resp_data,
        }

    @classmethod
    async def get_phone_number_details(
        cls,
        phone_number_id: str | None = None,
        access_token: str | None = None,
        graph_version: str | None = None,
    ) -> dict[str, Any]:
        """Fetch metadata and verification status for configured WhatsApp Phone Number ID.

        Returns:
            Dictionary with verified_name, display_phone_number, quality_rating, and status.
        """
        pid, token, version = cls._get_credentials(phone_number_id, access_token, graph_version)
        url = (
            f"https://graph.facebook.com/{version}/{pid}"
            "?fields=id,verified_name,display_phone_number,quality_rating,status,code_verification_status"
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=cls.DEFAULT_TIMEOUT) as client:
                resp = await client.get(url, headers=headers)

            if not resp.is_success:
                try:
                    err = resp.json().get("error", {})
                except Exception:
                    err = {"message": resp.text}
                raise cls._normalize_meta_error(resp.status_code, err)

            return resp.json()
        except httpx.TimeoutException as exc:
            raise WhatsAppNetworkTimeoutError(
                "Verification check timed out connecting to Meta API."
            ) from exc
        except (WhatsAppError, WhatsAppValidationError):
            raise
        except Exception as exc:
            raise WhatsAppError(f"Failed to fetch phone number details: {exc}") from exc

    @classmethod
    async def subscribe_waba_to_app(
        cls,
        waba_id: str | None = None,
        access_token: str | None = None,
        graph_version: str | None = None,
    ) -> dict[str, Any]:
        """Subscribe Meta App to the WhatsApp Business Account for real-time webhooks.

        Meta Cloud API requires an explicit subscribed_apps registration on the WABA
        so that delivery tracking webhooks (sent, delivered, read, failed) and inbound
        messages are dispatched to the application callback URL.

        Returns:
            Dictionary response from Meta Graph API (e.g., {"success": True}).
        """
        waba = waba_id or settings.WHATSAPP_BUSINESS_ACCOUNT_ID
        token = access_token or settings.WHATSAPP_ACCESS_TOKEN
        version = graph_version or settings.WHATSAPP_GRAPH_API_VERSION or "v21.0"

        if not waba:
            raise WhatsAppConfigurationError(
                "WhatsApp Business Account ID is not configured (WHATSAPP_BUSINESS_ACCOUNT_ID)."
            )
        if not token:
            raise WhatsAppConfigurationError(
                "WhatsApp Access Token is not configured (WHATSAPP_ACCESS_TOKEN)."
            )

        url = f"https://graph.facebook.com/{version}/{waba}/subscribed_apps"
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }

        try:
            async with httpx.AsyncClient(timeout=cls.DEFAULT_TIMEOUT) as client:
                resp = await client.post(url, headers=headers)

            if not resp.is_success:
                try:
                    err = resp.json().get("error", {})
                except Exception:
                    err = {"message": resp.text}
                raise cls._normalize_meta_error(resp.status_code, err)

            return resp.json()
        except httpx.TimeoutException as exc:
            raise WhatsAppNetworkTimeoutError(
                "Subscribing WABA to App timed out connecting to Meta API."
            ) from exc
        except (WhatsAppError, WhatsAppValidationError):
            raise
        except Exception as exc:
            raise WhatsAppError(f"Failed to subscribe WABA to Meta App: {exc}") from exc
