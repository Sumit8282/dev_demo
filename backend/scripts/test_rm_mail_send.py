"""Preview or send a test RM approval email using Gmail SMTP settings from .env.

By default this script only previews the email (dry-run). Pass --send to deliver it.
Production releases send mail automatically when the full UI workflow completes.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.config import get_settings
from app.services.mail_service import MailConfigurationError, send_rm_approval_notification
from app.services.rm_mail_service import build_rm_approval_notification_draft


def _print_config(settings) -> bool:
    print(f"MAIL_ENABLED: {settings.mail_enabled}")
    print(f"GMAIL_USER: {settings.gmail_user or '(not set)'}")
    print(f"MAIL_FROM: {settings.mail_from_address or '(not set)'}")
    print(
        "GMAIL_APP_PASSWORD: "
        f"{'(set)' if settings.gmail_app_password.get_secret_value() else '(not set)'}"
    )
    print(f"RM_MANAGER_EMAIL: {settings.rm_manager_email or '(not set)'}")
    print(f"PORTAL_BASE_URL: {settings.portal_base_url}")

    if not settings.mail_configured:
        print(
            "\nFAIL: Mail is not fully configured. Set MAIL_ENABLED=true and Gmail values in .env:"
        )
        print("  GMAIL_USER, GMAIL_APP_PASSWORD")
        return False

    if not settings.rm_manager_emails:
        print("\nFAIL: RM_MANAGER_EMAIL is not set.")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or send a test RM approval email.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the email (default is dry-run preview only)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not _print_config(settings):
        return 1

    recipients = settings.rm_manager_emails
    approval_url = f"{settings.portal_base_url.rstrip('/')}/approvals/rm/REL-RM-MAIL-TEST"
    approval_queue_url = f"{settings.portal_base_url.rstrip('/')}/approvals?tab=rm"
    notification_draft = build_rm_approval_notification_draft(
        release_id="REL-RM-MAIL-TEST",
        release_branch="feature/mail-test",
        release_version="feature/mail-test",
        github_pr_url="https://github.com/example/repo/pull/1",
        github_pr_number=1,
        jira_url="https://example.atlassian.net/browse/TEST-1",
        jira_issue_key="TEST-1",
        build_id="BUILD-20260817-001",
        environment="UAT",
        release_date=date.today(),
        raised_by="Gauri Satalkar",
        pr_title="Mail connectivity test",
        l3_approved_by="L3 Manager Name",
        approval_url=approval_url,
        approval_queue_url=approval_queue_url,
        recipient_emails=recipients,
    )
    notification_draft.subject = "[TEST] " + notification_draft.subject

    print(f"\nSubject: {notification_draft.subject}")
    print(f"To: {', '.join(recipients)}")
    print("\n--- Plain text preview ---")
    print(notification_draft.body_text)
    print("--- End preview ---")

    if not args.send:
        print("\nDry-run only — no email sent.")
        print("To send this test email, re-run with: python -m scripts.test_rm_mail_send --send")
        return 0

    print(f"\nSending test email to: {', '.join(recipients)}")
    try:
        sent = send_rm_approval_notification(notification_draft, settings=settings)
    except MailConfigurationError as exc:
        print(f"\nFAIL: {exc}")
        return 1

    if sent:
        print("\nSUCCESS: Test RM approval email sent via Gmail SMTP.")
        return 0

    print("\nFAIL: Email was not sent. Check backend logs for Gmail SMTP errors.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
