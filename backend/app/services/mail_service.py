"""Mail delivery facade for L3 and RM approval notifications (Gmail SMTP)."""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.models.l3_approval import L3ApprovalMailDraft
from app.services.gmail_mail_service import (
    GmailMailConfigurationError,
    GmailMailSendError,
    send_gmail_mail,
)

logger = logging.getLogger(__name__)

MailConfigurationError = GmailMailConfigurationError


def send_email(
    *,
    to: list[str],
    subject: str,
    body_text: str,
    body_html: str | None = None,
    settings: Settings | None = None,
) -> None:
    """Send an email via Gmail SMTP."""
    send_gmail_mail(
        to=to,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        settings=settings,
    )


def send_l3_approval_mail(
    mail_draft: L3ApprovalMailDraft,
    *,
    settings: Settings | None = None,
) -> bool:
    """Send the L3 approval notification email. Returns True if sent."""
    cfg = settings or get_settings()
    if not cfg.mail_enabled:
        logger.info("[MAIL] L3 approval mail not sent — MAIL_ENABLED is false")
        return False

    try:
        send_email(
            to=mail_draft.to,
            subject=mail_draft.subject,
            body_text=mail_draft.body_text,
            body_html=mail_draft.body_html,
            settings=cfg,
        )
        return True
    except GmailMailConfigurationError as exc:
        logger.error("[MAIL] L3 approval mail configuration error: %s", exc)
        return False
    except GmailMailSendError as exc:
        logger.error("[MAIL] Gmail error sending L3 approval mail: %s", exc)
        return False


def send_rm_approval_notification(
    notification_draft,
    *,
    settings: Settings | None = None,
) -> bool:
    """Send the RM approval notification email. Returns True if sent."""
    cfg = settings or get_settings()
    if not cfg.mail_enabled:
        logger.info("[MAIL] RM approval notification not sent — MAIL_ENABLED is false")
        return False

    try:
        send_email(
            to=notification_draft.to,
            subject=notification_draft.subject,
            body_text=notification_draft.body_text,
            body_html=notification_draft.body_html,
            settings=cfg,
        )
        return True
    except GmailMailConfigurationError as exc:
        logger.error("[MAIL] RM approval notification configuration error: %s", exc)
        return False
    except GmailMailSendError as exc:
        logger.error("[MAIL] Gmail error sending RM approval notification: %s", exc)
        return False
