"""Application-owned transactional email service for password recovery and notifications."""

import asyncio
import smtplib
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from flowpilot.core.config import get_settings
from flowpilot.core.logging import get_logger

logger = get_logger("services.email")


@dataclass(frozen=True)
class EmailDeliveryResult:
    """Result of an email dispatch attempt."""

    delivered: bool
    configured: bool
    message: str


class EmailService:
    """Dispatches application-owned transactional emails via configured SMTP provider."""

    @staticmethod
    def is_configured() -> bool:
        """Check if an application-owned SMTP provider is configured."""
        settings = get_settings()
        return bool(settings.SMTP_HOST and settings.SMTP_HOST.strip())

    @classmethod
    async def send_password_reset_email(
        cls,
        recipient_email: str,
        reset_url: str,
    ) -> EmailDeliveryResult:
        """Send a password recovery email containing the secure reset URL.

        If SMTP is unconfigured, reports the missing configuration without pretending
        the email was sent.
        """
        settings = get_settings()

        if not cls.is_configured():
            logger.warning(
                "Transactional email provider is not configured (SMTP_HOST is not set). "
                "Password reset email to %s was not sent.",
                recipient_email,
            )
            return EmailDeliveryResult(
                delivered=False,
                configured=False,
                message="Transactional email provider is not configured in this environment.",
            )

        # Build email content
        subject = f"Reset your {settings.EMAILS_FROM_NAME} password"
        from_address = (
            f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
            if settings.EMAILS_FROM_EMAIL
            else f"{settings.EMAILS_FROM_NAME} <noreply@flowpilot.local>"
        )

        text_content = (
            f"Hello,\n\n"
            f"We received a request to reset your password for FlowPilot AI.\n"
            f"Click the link below to set a new password:\n\n"
            f"{reset_url}\n\n"
            f"This link will expire in {settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes.\n"
            f"If you did not request a password reset, you can safely ignore this email.\n\n"
            f"Best regards,\n"
            f"The FlowPilot AI Team"
        )

        html_content = (
            "<!DOCTYPE html>\n"
            "<html>\n"
            "<head>\n"
            '  <meta charset="utf-8">\n'
            "  <title>Reset Your Password</title>\n"
            "</head>\n"
            "<body style=\"font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, "
            "Helvetica, Arial, sans-serif; background-color: #0b0f17; color: #f3f4f6; margin: 0; "
            'padding: 40px 20px;">\n'
            '  <div style="max-width: 520px; margin: 0 auto; background: #111827; '
            "border: 1px solid #1f2937; border-radius: 12px; padding: 32px; "
            'box-shadow: 0 10px 25px rgba(0,0,0,0.5);">\n'
            '    <div style="text-align: center; margin-bottom: 24px;">\n'
            '      <h1 style="font-size: 20px; font-weight: 700; color: #6366f1; margin: 0;">'
            "FlowPilot AI</h1>\n"
            '      <p style="font-size: 14px; color: #9ca3af; margin-top: 4px;">'
            "Password Recovery Request</p>\n"
            "    </div>\n"
            '    <p style="font-size: 14px; line-height: 1.6; color: #d1d5db;">Hello,</p>\n'
            '    <p style="font-size: 14px; line-height: 1.6; color: #d1d5db;">\n'
            "      We received a request to reset your FlowPilot AI account password. "
            "Click the button below to choose a new password:\n"
            "    </p>\n"
            '    <div style="text-align: center; margin: 32px 0;">\n'
            f'      <a href="{reset_url}" style="display: inline-block; background-color: #4f46e5; '
            "color: #ffffff; text-decoration: none; font-weight: 600; font-size: 14px; "
            "padding: 12px 28px; border-radius: 8px; "
            'box-shadow: 0 4px 12px rgba(79, 70, 229, 0.4);">\n'
            "        Reset Password\n"
            "      </a>\n"
            "    </div>\n"
            '    <p style="font-size: 13px; line-height: 1.5; color: #9ca3af;">\n'
            f"      This link will expire in <strong>"
            f"{settings.PASSWORD_RESET_TOKEN_EXPIRE_MINUTES} minutes</strong>.\n"
            "      If you did not request this, no action is needed.\n"
            "    </p>\n"
            '    <hr style="border: none; border-top: 1px solid #1f2937; margin: 24px 0;" />\n'
            '    <p style="font-size: 12px; color: #6b7280; text-align: center; margin: 0;">\n'
            "      &copy; 2026 FlowPilot AI. All rights reserved.\n"
            "    </p>\n"
            "  </div>\n"
            "</body>\n"
            "</html>"
        )

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_address
        msg["To"] = recipient_email
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        def _sync_send() -> None:
            if settings.SMTP_PORT == 465:
                server = smtplib.SMTP_SSL(
                    settings.SMTP_HOST or "", settings.SMTP_PORT, timeout=10.0
                )
            else:
                server = smtplib.SMTP(settings.SMTP_HOST or "", settings.SMTP_PORT, timeout=10.0)
                if settings.SMTP_TLS:
                    server.starttls()

            try:
                if settings.SMTP_USER and settings.SMTP_PASSWORD:
                    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.send_message(msg)
            finally:
                server.quit()

        try:
            await asyncio.to_thread(_sync_send)
            logger.info("Password reset email sent to recipient.")
            return EmailDeliveryResult(
                delivered=True,
                configured=True,
                message="Password reset instructions sent to your email.",
            )
        except Exception as exc:
            logger.error("Failed to send transactional password reset email: %s", exc)
            return EmailDeliveryResult(
                delivered=False,
                configured=True,
                message="Unable to dispatch email through the configured SMTP provider.",
            )
