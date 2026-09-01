"""Release workflow state model."""

from datetime import date
from typing import Any, TypedDict

from app.models.release import OverallValidationStatus, WorkflowStatus
from app.models.validation import (
    GitHubValidationResult,
    JiraValidationResult,
    MergeResult,
    QAValidationResult,
)

class ReleaseState(TypedDict, total=False):
    release_id: str
    release_branch: str
    release_version: str
    github_pr_url: str
    github_owner: str
    github_repo: str
    github_pr_number: int
    jira_url: str
    jira_issue_key: str
    qa_signoff_required: bool
    qa_signoff_not_required_reason: str | None
    qa_signoff_attachment: dict[str, Any] | None
    environment: str
    release_date: date
    created_by: str | None

    github_validation: GitHubValidationResult | dict[str, Any] | None
    jira_validation: JiraValidationResult | dict[str, Any] | None
    qa_validation: QAValidationResult | dict[str, Any] | None

    overall_validation_status: OverallValidationStatus | str | None
    workflow_status: WorkflowStatus | str
    failure_reasons: list[str]
    github_comment_posted: bool
    l3_approval_request: dict[str, Any] | None
    l3_approval_mail_path: str | None
    risk_score: dict[str, Any] | None
    build_result: dict[str, Any] | None
    rm_approval_request: dict[str, Any] | None
    rm_approval_notification_path: str | None
    merge_result: MergeResult | dict[str, Any] | None
    workflow_events: list[dict[str, Any]]

    created_at: Any
    updated_at: Any
