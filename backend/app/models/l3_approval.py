"""L3 approval request and mail draft models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from app.models.risk_score import ReleaseRiskScore


class L3ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class L3ApprovalRequest(BaseModel):
    release_id: str
    status: L3ApprovalStatus = L3ApprovalStatus.PENDING
    approval_url: str
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
    environment: str
    release_date: date
    raised_by: str | None = None
    pr_title: str | None = None
    qa_signoff_required: bool
    has_qa_attachment: bool = False
    qa_signoff_attachment_filename: str | None = None
    risk_score: ReleaseRiskScore | None = None


class L3ApprovalMailDraft(BaseModel):
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    subject: str
    body_text: str
    body_html: str
    approval_url: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class L3ApprovalActionRequest(BaseModel):
    approver_name: str = Field(..., min_length=1)
    approver_soe_id: str = Field(..., min_length=1)
    comment: str | None = Field(default=None)


class L3ApprovalRejectRequest(L3ApprovalActionRequest):
    remarks: str = Field(..., min_length=1)
