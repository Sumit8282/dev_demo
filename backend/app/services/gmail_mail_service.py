"""Gmail SMTP mail delivery for approval notifications."""

from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class GmailMailConfigurationError(Exception):
    """Raised when Gmail mail settings are incomplete."""


class GmailMailSendError(Exception):
    """Raised when Gmail SMTP send fails."""


def _format_smtp_error(exc: smtplib.SMTPException) -> str:
    message = str(exc)
    if "535" in message or "BadCredentials" in message or "Username and Password not accepted" in message:
        return (
            f"{message}\n"
            "Gmail rejected the login. Use a Google App Password (16 characters), "
            "not your regular Gmail password. Enable 2-Step Verification, then create one at "
            "https://myaccount.google.com/apppasswords"
        )
    return message


def validate_gmail_mail_settings(settings: Settings) -> None:
    if not settings.mail_enabled:
        return
    missing: list[str] = []
    if not settings.gmail_user.strip():
        missing.append("GMAIL_USER")
    if not settings.gmail_app_password_normalized:
        missing.append("GMAIL_APP_PASSWORD")
    if not settings.mail_from_address.strip():
        missing.append("GMAIL_USER or MAIL_FROM")
    if missing:
        raise GmailMailConfigurationError(
            f"MAIL_ENABLED is true but missing: {', '.join(missing)}"
        )


def send_gmail_mail(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    body_html: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Send email via Gmail SMTP (TLS on port 587)."""
    cfg = settings or get_settings()
    validate_gmail_mail_settings(cfg)

    if not cfg.mail_enabled:
        logger.info("[GMAIL] Skipped send — MAIL_ENABLED is false")
        return

    recipients = [email.strip() for email in to if email.strip()]
    if not recipients:
        raise GmailMailConfigurationError("No recipient email addresses provided.")

    sender = cfg.mail_from_address
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.attach(MIMEText(body_text, "plain", "utf-8"))
    if body_html:
        message.attach(MIMEText(body_html, "html", "utf-8"))

    password = cfg.gmail_app_password_normalized
    gmail_user = cfg.gmail_user.strip()
    logger.info(
        "[GMAIL] Sending email to %d recipient(s): %s (from %s)",
        len(recipients),
        ", ".join(recipients),
        sender,
    )
    try:
        with smtplib.SMTP(cfg.gmail_smtp_host, cfg.gmail_smtp_port, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(gmail_user, password)
            smtp.sendmail(sender, recipients, message.as_string())
    except smtplib.SMTPException as exc:
        raise GmailMailSendError(_format_smtp_error(exc)) from exc

    logger.info(
        "[GMAIL] Email accepted by SMTP for %d recipient(s): %s",
        len(recipients),
        ", ".join(recipients),
    )
