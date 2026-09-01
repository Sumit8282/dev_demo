"""Generate L3 approval notification mail drafts and support SMTP delivery."""

from __future__ import annotations

import html
from datetime import date

from app.models.l3_approval import L3ApprovalMailDraft
from app.models.risk_score import ReleaseRiskScore

_INTRO = (
    "A release request has successfully passed the required GitHub, Jira, and QA "
    "validations and is now awaiting L3 approval."
)
_MERGED_INTRO = (
    "A release request has successfully passed the required GitHub, Jira, and QA "
    "validations. Based on a LOW risk assessment, the pull request has been "
    "automatically merged."
)
_REVIEW_PROMPT = "Please review the release details and provide your approval."
_MERGED_MESSAGE = (
    "The pull request has been merged. No further L3 approval action is required."
)
_SIGNATURE = "Regards,\nRelease Automation System"
_FOOTER = "This is an automated notification. Please do not reply to this email."


def _build_release_detail_lines(
    *,
    release_id: str,
    release_branch: str,
    environment: str,
    release_date: date,
    raised_by_label: str,
    pr_title_label: str,
    github_pr_url: str,
    jira_issue_key: str,
    risk_score_label: str,
    risk_level_label: str,
    risk_reason_label: str,
    changes_label: str,
) -> list[tuple[str, str]]:
    return [
        ("Release ID", release_id),
        ("Release Branch", release_branch),
        ("Environment", environment),
        ("Release Date", release_date.isoformat()),
        ("Raised By", raised_by_label),
        ("PR Title", pr_title_label),
        ("GitHub PR", github_pr_url),
        ("Jira Ticket", jira_issue_key),
        ("Risk Score", risk_score_label),
        ("Risk Level", risk_level_label),
        ("Risk Reason", risk_reason_label),
        ("Release Summary", changes_label),
    ]


def _build_release_detail_table_html(
    *,
    release_id: str,
    release_branch: str,
    environment: str,
    release_date: date,
    raised_by_label: str,
    pr_title_label: str,
    github_pr_url: str,
    jira_url: str,
    jira_issue_key: str,
    risk_score_label: str,
    risk_level_label: str,
    risk_reason_html: str,
    changes_html: str,
) -> str:
    return (
        f"<tr><td><strong>Release ID</strong></td><td>{html.escape(release_id)}</td></tr>"
        f"<tr><td><strong>Release Branch</strong></td><td>{html.escape(release_branch)}</td></tr>"
        f"<tr><td><strong>Environment</strong></td><td>{html.escape(environment)}</td></tr>"
        f"<tr><td><strong>Release Date</strong></td><td>{release_date.isoformat()}</td></tr>"
        f"<tr><td><strong>Raised By</strong></td><td>{html.escape(raised_by_label)}</td></tr>"
        f"<tr><td><strong>PR Title</strong></td><td>{html.escape(pr_title_label)}</td></tr>"
        f"<tr><td><strong>GitHub PR</strong></td>"
        f"<td><a href=\"{github_pr_url}\">{html.escape(github_pr_url)}</a></td></tr>"
        f"<tr><td><strong>Jira Ticket</strong></td>"
        f"<td><a href=\"{jira_url}\">{html.escape(jira_issue_key)}</a></td></tr>"
        f"<tr><td><strong>Risk Score</strong></td><td>{html.escape(risk_score_label)}</td></tr>"
        f"<tr><td><strong>Risk Level</strong></td><td>{html.escape(risk_level_label)}</td></tr>"
        f"<tr><td><strong>Risk Reason</strong></td><td>{risk_reason_html}</td></tr>"
        f"<tr><td><strong>Release Summary</strong></td><td>{changes_html}</td></tr>"
    )


def build_l3_approval_mail_draft(
    *,
    release_id: str,
    release_branch: str,
    release_version: str,
    github_pr_url: str,
    github_pr_number: int,
    jira_url: str,
    jira_issue_key: str,
    environment: str,
    release_date: date,
    raised_by: str | None,
    pr_title: str | None,
    approval_url: str,
    recipient_emails: list[str],
    change_description: str | None = None,
    risk_score: ReleaseRiskScore | None = None,
) -> L3ApprovalMailDraft:
    raised_by_label = raised_by or "Unknown"
    pr_title_label = pr_title or f"PR #{github_pr_number}"
    changes_label = (change_description or "").strip() or "Not provided"
    changes_html = html.escape(changes_label).replace("\n", "<br>")
    risk_score_label = f"{risk_score.score:.2f}" if risk_score else "Not calculated"
    risk_level_label = risk_score.level if risk_score else "Not calculated"
    risk_reason_label = risk_score.reason() if risk_score else "Not calculated"
    risk_reason_html = html.escape(risk_reason_label)
    subject = f"L3 Approval Required: {release_id}"

    detail_lines = _build_release_detail_lines(
        release_id=release_id,
        release_branch=release_branch,
        environment=environment,
        release_date=release_date,
        raised_by_label=raised_by_label,
        pr_title_label=pr_title_label,
        github_pr_url=github_pr_url,
        jira_issue_key=jira_issue_key,
        risk_score_label=risk_score_label,
        risk_level_label=risk_level_label,
        risk_reason_label=risk_reason_label,
        changes_label=changes_label,
    )
    details_text = "\n".join(f"{label}\t{value}" for label, value in detail_lines)

    body_text = (
        "Hi L3 Team,\n\n"
        f"{_INTRO}\n\n"
        f"{details_text}\n\n"
        f"{_REVIEW_PROMPT}\n\n"
        f"Approval URL:\n{approval_url}\n\n"
        f"{_SIGNATURE}\n\n"
        f"{_FOOTER}"
    )

    table_rows = _build_release_detail_table_html(
        release_id=release_id,
        release_branch=release_branch,
        environment=environment,
        release_date=release_date,
        raised_by_label=raised_by_label,
        pr_title_label=pr_title_label,
        github_pr_url=github_pr_url,
        jira_url=jira_url,
        jira_issue_key=jira_issue_key,
        risk_score_label=risk_score_label,
        risk_level_label=risk_level_label,
        risk_reason_html=risk_reason_html,
        changes_html=changes_html,
    )

    body_html = (
        "<p>Hi L3 Team,</p>"
        f"<p>{html.escape(_INTRO)}</p>"
        f"<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;\">"
        f"{table_rows}"
        "</table>"
        f"<p>{html.escape(_REVIEW_PROMPT)}</p>"
        f"<p><a href=\"{approval_url}\">Open L3 Approval Page</a></p>"
        f"<p><strong>Approval URL:</strong><br><a href=\"{approval_url}\">"
        f"{html.escape(approval_url)}</a></p>"
        "<p>Regards,<br>Release Automation System</p>"
        f"<p><em>{html.escape(_FOOTER)}</em></p>"
    )

    return L3ApprovalMailDraft(
        to=recipient_emails,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        approval_url=approval_url,
        metadata={
            "approval_link": approval_url,
            "release_id": release_id,
            "release_branch": release_branch,
            "release_version": release_version,
            "github_pr_url": github_pr_url,
            "github_pr_number": github_pr_number,
            "jira_url": jira_url,
            "jira_issue_key": jira_issue_key,
            "environment": environment,
            "release_date": release_date.isoformat(),
            "raised_by": raised_by_label,
            "pr_title": pr_title_label,
            "release_summary": changes_label,
            "change_description": changes_label,
            "risk_score": risk_score.score if risk_score else None,
            "risk_level": risk_score.level if risk_score else None,
            "risk_reason": risk_reason_label if risk_score else None,
            "approval_url": approval_url,
            "mail_status": "draft",
        },
    )


def build_l3_merged_notification_mail_draft(
    *,
    release_id: str,
    release_branch: str,
    release_version: str,
    github_pr_url: str,
    github_pr_number: int,
    jira_url: str,
    jira_issue_key: str,
    environment: str,
    release_date: date,
    raised_by: str | None,
    pr_title: str | None,
    recipient_emails: list[str],
    change_description: str | None = None,
    risk_score: ReleaseRiskScore | None = None,
) -> L3ApprovalMailDraft:
    """Build an informational L3 mail after a low-risk PR is auto-merged."""
    raised_by_label = raised_by or "Unknown"
    pr_title_label = pr_title or f"PR #{github_pr_number}"
    changes_label = (change_description or "").strip() or "Not provided"
    changes_html = html.escape(changes_label).replace("\n", "<br>")
    risk_score_label = f"{risk_score.score:.2f}" if risk_score else "Not calculated"
    risk_level_label = risk_score.level if risk_score else "Not calculated"
    risk_reason_label = risk_score.reason() if risk_score else "Not calculated"
    risk_reason_html = html.escape(risk_reason_label)
    subject = f"PR Merged — Release: {release_id}"

    detail_lines = _build_release_detail_lines(
        release_id=release_id,
        release_branch=release_branch,
        environment=environment,
        release_date=release_date,
        raised_by_label=raised_by_label,
        pr_title_label=pr_title_label,
        github_pr_url=github_pr_url,
        jira_issue_key=jira_issue_key,
        risk_score_label=risk_score_label,
        risk_level_label=risk_level_label,
        risk_reason_label=risk_reason_label,
        changes_label=changes_label,
    )
    details_text = "\n".join(f"{label}\t{value}" for label, value in detail_lines)

    body_text = (
        "Hi L3 Team,\n\n"
        f"{_MERGED_INTRO}\n\n"
        f"{details_text}\n\n"
        f"{_MERGED_MESSAGE}\n\n"
        f"{_SIGNATURE}\n\n"
        f"{_FOOTER}"
    )

    table_rows = _build_release_detail_table_html(
        release_id=release_id,
        release_branch=release_branch,
        environment=environment,
        release_date=release_date,
        raised_by_label=raised_by_label,
        pr_title_label=pr_title_label,
        github_pr_url=github_pr_url,
        jira_url=jira_url,
        jira_issue_key=jira_issue_key,
        risk_score_label=risk_score_label,
        risk_level_label=risk_level_label,
        risk_reason_html=risk_reason_html,
        changes_html=changes_html,
    )

    body_html = (
        "<p>Hi L3 Team,</p>"
        f"<p>{html.escape(_MERGED_INTRO)}</p>"
        f"<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\" "
        "style=\"border-collapse:collapse;\">"
        f"{table_rows}"
        "</table>"
        f"<p>{html.escape(_MERGED_MESSAGE)}</p>"
        "<p>Regards,<br>Release Automation System</p>"
        f"<p><em>{html.escape(_FOOTER)}</em></p>"
    )

    return L3ApprovalMailDraft(
        to=recipient_emails,
        subject=subject,
        body_text=body_text,
        body_html=body_html,
        approval_url="",
        metadata={
            "release_id": release_id,
            "release_branch": release_branch,
            "release_version": release_version,
            "github_pr_url": github_pr_url,
            "github_pr_number": github_pr_number,
            "jira_url": jira_url,
            "jira_issue_key": jira_issue_key,
            "environment": environment,
            "release_date": release_date.isoformat(),
            "raised_by": raised_by_label,
            "pr_title": pr_title_label,
            "release_summary": changes_label,
            "change_description": changes_label,
            "risk_score": risk_score.score if risk_score else None,
            "risk_level": risk_score.level if risk_score else None,
            "risk_reason": risk_reason_label if risk_score else None,
            "mail_status": "draft",
            "notification_type": "pr_merged",
        },
    )
