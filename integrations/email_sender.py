"""CertBrain — Email sender integration.

Sends emails via SMTP (aiosmtplib) when configured, or falls back to
logging the email content for development / demo scenarios.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from config import get_logger

logger = get_logger(__name__)


@dataclass
class EmailMessage:
    """A simple email payload."""

    to: str
    subject: str
    body: str
    html: bool = False


class EmailSender:
    """Async email sender with SMTP or logging fallback.

    Environment variables (optional):
        ``SMTP_HOST``, ``SMTP_PORT``, ``SMTP_USER``, ``SMTP_PASSWORD``,
        ``SMTP_FROM``.

    When any of these are missing the sender operates in **log-only** mode:
    messages are logged at INFO level instead of being sent.
    """

    def __init__(self) -> None:
        self._host = os.getenv("SMTP_HOST", "")
        self._port = int(os.getenv("SMTP_PORT", "587"))
        self._user = os.getenv("SMTP_USER", "")
        self._password = os.getenv("SMTP_PASSWORD", "")
        self._from_addr = os.getenv("SMTP_FROM", "certbrain@noreply.local")
        self._smtp_configured = bool(self._host and self._user and self._password)

        if self._smtp_configured:
            logger.info("Email sender: SMTP mode (%s:%d)", self._host, self._port)
        else:
            logger.info("Email sender: log-only mode (SMTP not configured)")

    async def send(self, message: EmailMessage) -> bool:
        """Send an email or log it.

        Returns *True* if the message was sent/logged successfully.
        """
        if self._smtp_configured:
            return await self._send_smtp(message)
        return self._log_message(message)

    async def _send_smtp(self, message: EmailMessage) -> bool:
        """Send via aiosmtplib."""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText

            mime_type = "html" if message.html else "plain"
            msg = MIMEText(message.body, mime_type)
            msg["Subject"] = message.subject
            msg["From"] = self._from_addr
            msg["To"] = message.to

            await aiosmtplib.send(
                msg,
                hostname=self._host,
                port=self._port,
                username=self._user,
                password=self._password,
                start_tls=True,
            )
            logger.info("Email sent to %s: %s", message.to, message.subject)
            return True
        except ImportError:
            logger.warning("aiosmtplib not installed — falling back to log mode")
            return self._log_message(message)
        except Exception as exc:
            logger.error("Failed to send email to %s: %s", message.to, exc)
            return False

    @staticmethod
    def _log_message(message: EmailMessage) -> bool:
        """Log the email instead of sending it."""
        logger.info(
            "EMAIL [to=%s] subject=%s\n%s",
            message.to,
            message.subject,
            message.body[:500],
        )
        return True
