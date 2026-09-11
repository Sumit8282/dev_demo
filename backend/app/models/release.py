"""Release request and response models."""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

from app.models.l3_approval import L3ApprovalRequest
from app.models.risk_score import ReleaseRiskScore
from app.models.rm_approval import RMApprovalRequest
from app.models.workflow_event import WorkflowEvent


class WorkflowStatus(str, Enum):
    PENDING = "PENDING"
    VALIDATING = "VALIDATING"
    L3_APPROVAL_PENDING = "L3_APPROVAL_PENDING"
    L3_APPROVED = "L3_APPROVED"
    L3_REJECTED = "L3_REJECTED"
    MERGE_PENDING = "MERGE_PENDING"
    MERGED = "MERGED"
    MERGE_FAILED = "MERGE_FAILED"
    BUILD_PENDING = "BUILD_PENDING"
    BUILD_COMPLETED = "BUILD_COMPLETED"
    BUILD_FAILED = "BUILD_FAILED"
    RM_APPROVAL_PENDING = "RM_APPROVAL_PENDING"
    RM_APPROVED = "RM_APPROVED"
    RM_REJECTED = "RM_REJECTED"
    DEPLOYMENT_COMPLETED = "DEPLOYMENT_COMPLETED"
    HALTED = "HALTED"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class OverallValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class QAMode(str, Enum):
    NOT_REQUIRED = "not_required"
    UPLOAD = "upload"
    PR_TESTS = "pr_tests"
    GITHUB_ISSUES = "github_issues"


def jira_required(qa_mode: str | QAMode | None) -> bool:
    value = qa_mode.value if isinstance(qa_mode, QAMode) else (qa_mode or "")
    return value.strip().lower() != QAMode.GITHUB_ISSUES.value


class ReleaseRequest(BaseModel):
    release_branch: str = Field(..., min_length=1)
    github_pr_url: HttpUrl
    jira_url: HttpUrl | None = None
    qa_signoff_required: bool
    qa_signoff_not_required_reason: str | None = Field(default=None)
    qa_mode: QAMode | None = None
    environment: str = Field(..., min_length=1)
    release_date: date
    created_by: str | None = Field(default=None)

    @field_validator("release_branch", "environment")
    @classmethod
    def strip_and_validate_non_empty(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("Field cannot be empty")
        return stripped

    @field_validator("qa_signoff_not_required_reason")
    @classmethod
    def strip_qa_reason(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("created_by")
    @classmethod
    def strip_created_by(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("jira_url", mode="before")
    @classmethod
    def empty_jira_url(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def validate_qa_fields(self) -> ReleaseRequest:
        if self.qa_mode is None:
            self.qa_mode = QAMode.UPLOAD if self.qa_signoff_required else QAMode.NOT_REQUIRED

        if self.qa_mode == QAMode.NOT_REQUIRED:
            self.qa_signoff_required = False
            if not self.qa_signoff_not_required_reason:
                raise ValueError(
                    "qa_signoff_not_required_reason is required when QA is not required"
                )
        elif self.qa_mode in {QAMode.PR_TESTS, QAMode.GITHUB_ISSUES}:
            self.qa_signoff_required = True
        else:
            self.qa_signoff_required = True

        if self.qa_mode == QAMode.GITHUB_ISSUES:
            if self.jira_url is None:
                return self
        elif self.jira_url is None:
            raise ValueError("jira_url is required unless QA mode is github_issues")
        return self


class QASignoffAttachment(BaseModel):
    filename: str
    content_type: str
    size_bytes: int


class ReleaseCreateResponse(BaseModel):
    release_id: str
    workflow_status: WorkflowStatus
    message: str


class ReleaseStateResponse(BaseModel):
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
    qa_signoff_not_required_reason: str | None = None
    qa_mode: QAMode | None = None
    qa_signoff_attachment: QASignoffAttachment | None = None
    environment: str
    release_date: date
    created_by: str | None = None
    github_validation: dict[str, Any] | None = None
    jira_validation: dict[str, Any] | None = None
    qa_validation: dict[str, Any] | None = None
    overall_validation_status: OverallValidationStatus | None = None
    workflow_status: WorkflowStatus
    failure_reasons: list[str] = Field(default_factory=list)
    github_comment_posted: bool = False
    l3_approval_request: L3ApprovalRequest | None = None
    risk_score: ReleaseRiskScore | None = None
    build_result: dict[str, Any] | None = None
    rm_approval_request: RMApprovalRequest | None = None
    merge_result: dict[str, Any] | None = None
    workflow_events: list[WorkflowEvent] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
