"""WhatsApp Business Platform (Cloud API) integration adapter and client."""

from flowpilot.integrations.whatsapp.client import (
    WhatsAppAuthenticationError,
    WhatsAppClient,
    WhatsAppConfigurationError,
    WhatsAppError,
    WhatsAppMessagingWindowError,
    WhatsAppNetworkTimeoutError,
    WhatsAppRateLimitError,
    WhatsAppRecipientError,
    WhatsAppValidationError,
)

__all__ = [
    "WhatsAppClient",
    "WhatsAppError",
    "WhatsAppConfigurationError",
    "WhatsAppAuthenticationError",
    "WhatsAppRateLimitError",
    "WhatsAppMessagingWindowError",
    "WhatsAppRecipientError",
    "WhatsAppValidationError",
    "WhatsAppNetworkTimeoutError",
]
