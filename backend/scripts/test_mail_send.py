"""Preview or send a test L3 approval email using Gmail SMTP settings from .env.

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
from app.services.l3_mail_service import build_l3_approval_mail_draft
from app.services.mail_service import MailConfigurationError, send_l3_approval_mail


def _print_config(settings) -> bool:
    print(f"MAIL_ENABLED: {settings.mail_enabled}")
    print(f"GMAIL_USER: {settings.gmail_user or '(not set)'}")
    print(f"MAIL_FROM: {settings.mail_from_address or '(not set)'}")
    print(
        "GMAIL_APP_PASSWORD: "
        f"{'(set)' if settings.gmail_app_password.get_secret_value() else '(not set)'}"
    )
    print(f"L3_MANAGER_EMAIL: {settings.l3_manager_email or '(not set)'}")
    print(f"PORTAL_BASE_URL: {settings.portal_base_url}")

    if not settings.mail_configured:
        print(
            "\nFAIL: Mail is not fully configured. Set MAIL_ENABLED=true and Gmail values in .env:"
        )
        print("  GMAIL_USER, GMAIL_APP_PASSWORD")
        return False

    if not settings.l3_manager_emails:
        print("\nFAIL: L3_MANAGER_EMAIL is not set.")
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or send a test L3 approval email.")
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send the email (default is dry-run preview only)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if not _print_config(settings):
        return 1

    recipients = settings.l3_manager_emails
    approval_url = f"{settings.portal_base_url.rstrip('/')}/approvals/l3/REL-MAIL-TEST"
    mail_draft = build_l3_approval_mail_draft(
        release_id="REL-MAIL-TEST",
        release_branch="feature/mail-test",
        release_version="feature/mail-test",
        github_pr_url="https://github.com/example/repo/pull/1",
        github_pr_number=1,
        jira_url="https://example.atlassian.net/browse/TEST-1",
        jira_issue_key="TEST-1",
        environment="UAT",
        release_date=date.today(),
        raised_by="Gauri Satalkar",
        pr_title="Mail connectivity test",
        approval_url=approval_url,
        recipient_emails=recipients,
        change_description=(
            "Fixed offerings dropdown navigation bug.\n"
            "Updated click handler to route to the correct offerings page."
        ),
    )
    mail_draft.subject = "[TEST] " + mail_draft.subject

    print(f"\nSubject: {mail_draft.subject}")
    print(f"To: {', '.join(recipients)}")
    print("\n--- Plain text preview ---")
    print(mail_draft.body_text)
    print("--- End preview ---")

    if not args.send:
        print("\nDry-run only — no email sent.")
        print("To send this test email, re-run with: python -m scripts.test_mail_send --send")
        return 0

    print(f"\nSending test email to: {', '.join(recipients)}")
    try:
        sent = send_l3_approval_mail(mail_draft, settings=settings)
    except MailConfigurationError as exc:
        print(f"\nFAIL: {exc}")
        return 1

    if sent:
        print("\nSUCCESS: Test L3 approval email sent via Gmail SMTP.")
        return 0

    print("\nFAIL: Email was not sent. Check backend logs for Gmail SMTP errors.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
