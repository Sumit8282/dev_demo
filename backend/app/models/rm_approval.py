"""RM approval request and notification draft models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class RMApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ApprovalStatusSummary(BaseModel):
    github_validation: str | None = None
    jira_validation: str | None = None
    qa_validation: str | None = None
    l3_approval: str | None = None
    merge: str | None = None
    build: str | None = None


class RMApprovalRequest(BaseModel):
    release_id: str
    status: RMApprovalStatus = RMApprovalStatus.PENDING
    approval_url: str
    approval_queue_url: str
    created_at: datetime
    approved_by: str | None = None
    approver_soe_id: str | None = None
    approved_at: datetime | None = None
    approval_comment: str | None = None
    rejection_remarks: str | None = None
    release_branch: str
    release_version: str
    github_pr_url: str
    github_pr_number: int
    jira_url: str
    jira_issue_key: str
    build_id: str
    target_environment: str
    deployment_window: str
    approval_statuses: ApprovalStatusSummary
    raised_by: str | None = None
    pr_title: str | None = None
    l3_approved_by: str | None = None


class RMApprovalNotificationDraft(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str
    body_text: str
    body_html: str
    approval_url: str
    approval_queue_url: str
    notification_channels: list[str] = Field(default_factory=lambda: ["mail"])
    metadata: dict[str, Any] = Field(default_factory=dict)


class RMApprovalActionRequest(BaseModel):
    approver_name: str = Field(..., min_length=1)
    approver_soe_id: str = Field(..., min_length=1)
    comment: str | None = Field(default=None)


class RMApprovalRejectRequest(RMApprovalActionRequest):
    remarks: str = Field(..., min_length=1)
