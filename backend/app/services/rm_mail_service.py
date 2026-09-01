"""Generate RM approval notification emails."""

from __future__ import annotations

import html
from datetime import date, timedelta

from app.models.rm_approval import RMApprovalNotificationDraft

_INTRO = (
    "A release build has been generated and is awaiting Release Manager approval "
    "before deployment."
)
_REVIEW_PROMPT = "Please review the release details and provide your approval."
_SIGNATURE = "Regards,\nRelease Automation System"
_FOOTER = "This is an automated notification. Please do not reply to this email."


def format_deployment_window(release_date: date) -> str:
    """Return a standard overnight deployment window for the release date."""
    next_day = release_date + timedelta(days=1)
    return f"{release_date.isoformat()} 22:00 - {next_day.isoformat()} 02:00 UTC"


def build_rm_approval_notification_draft(
    *,
    release_id: str,
    release_branch: str,
    release_version: str,
    github_pr_url: str,
    github_pr_number: int,
    jira_url: str,
    jira_issue_key: str,
    build_id: str,
    environment: str,
    release_date: date,
    raised_by: str | None,
    pr_title: str | None,
    l3_approved_by: str | None,
    approval_url: str,
    approval_queue_url: str,
    recipient_emails: list[str],
) -> RMApprovalNotificationDraft:
    raised_by_label = raised_by or "Unknown"
    pr_title_label = pr_title or f"PR #{github_pr_number}"
    l3_approver_label = l3_approved_by or "Unknown"
    subject = f"RM Approval Required: {release_id}"

    detail_lines = [
        ("Release ID", release_id),
        ("Release Branch", release_branch),
        ("Build ID", build_id),
        ("Environment", environment),
        ("Release Date", release_date.isoformat()),
        ("Raised By", raised_by_label),
        ("PR Title", pr_title_label),
        ("GitHub PR", github_pr_url),
        ("Jira Ticket", jira_issue_key),
        ("L3 Approved By", l3_approver_label),
    ]
    details_text = "\n".join(f"{label}\t{value}" for label, value in detail_lines)

    body_text = (
        "Hi RM Team,\n\n"
        f"{_INTRO}\n\n"
        f"{details_text}\n\n"
        f"{_REVIEW_PROMPT}\n\n"
    
        f"Approval URL:\n{approval_url}\n\n"
        f"{_SIGNATURE}\n\n"
        f"{_FOOTER}"
    )

    table_rows = (
        f"<tr><td><strong>Release ID</strong></td><td>{html.escape(release_id)}</td></tr>"
        f"<tr><td><strong>Release Branch</strong></td><td>{html.escape(release_branch)}</td></tr>"
        f"<tr><td><strong>Build ID</strong></td><td>{html.escape(build_id)}</td></tr>"
        f"<tr><td><strong>Environment</strong></td><td>{html.escape(environment)}</td></tr>"
        f"<tr><td><strong>Release Date</strong></td><td>{release_date.isoformat()}</td></tr>"
        f"<tr><td><strong>Raised By</strong></td><td>{html.escape(raised_by_label)}</td></tr>"
        f"<tr><td><strong>PR Title</strong></td><td>{html.escape(pr_title_label)}</td></tr>"
        f"<tr><td><strong>GitHub PR</strong></td>"
        f"<td><a href=\"{github_pr_url}\">{html.escape(github_pr_url)}</a></td></tr>"
        f"<tr><td><strong>Jira Ticket</strong></td>"
        f"<td><a href=\"{jira_url}\">{html.escape(jira_issue_key)}</a></td></tr>"
        f"<tr><td><strong>L3 Approved By</strong></td><td>{html.escape(l3_approver_label)}</td></tr>"
    )

    body_html = (
        "<p>Hi RM Team,</p>"
        f"<p>{html.escape(_INTRO)}</p>"
        f"<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;\">"
        f"{table_rows}"
        "</table>"
        f"<p>{html.escape(_REVIEW_PROMPT)}</p>"
        f"<p><a href=\"{approval_url}\">Open RM Approval Page</a></p>"
        f"<p><strong>Approval URL:</strong><br><a href=\"{approval_url}\">"
        f"{html.escape(approval_url)}</a></p>"
        "<p>Regards,<br>Release Automation System</p>"
        f"<p><em>{html.escape(_FOOTER)}</em></p>"
    )

    return RMApprovalNotificationDraft(
        to=recipient_emails,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        approval_url=approval_url,
        approval_queue_url=approval_queue_url,
        notification_channels=["mail"],
        metadata={
            "approval_link": approval_url,
            "approval_queue_url": approval_queue_url,
            "release_id": release_id,
            "release_branch": release_branch,
            "release_version": release_version,
            "github_pr_url": github_pr_url,
            "github_pr_number": github_pr_number,
            "jira_url": jira_url,
            "jira_issue_key": jira_issue_key,
            "build_id": build_id,
            "environment": environment,
            "release_date": release_date.isoformat(),
            "raised_by": raised_by_label,
            "pr_title": pr_title_label,
            "l3_approved_by": l3_approver_label,
            "approval_url": approval_url,
            "notification_channels": ["mail"],
        },
    )
