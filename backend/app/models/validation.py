"""Validation result models."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ValidationStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    ERROR = "ERROR"


class JiraChecks(BaseModel):
    ticket_exists: bool = False
    status_valid: bool = False
    fix_version_match: bool = False
    description_match: bool = False


class JiraValidationResult(BaseModel):
    agent: str = "jira"
    status: ValidationStatus
    checks: JiraChecks
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class QAChecks(BaseModel):
    signoff_required: bool
    signoff_completed: bool
    signoff_not_required_reason: str | None = None


class QAValidationResult(BaseModel):
    agent: str = "qa"
    status: ValidationStatus
    checks: QAChecks
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class GitHubChecks(BaseModel):
    pr_exists: bool = False
    pr_is_open: bool = False
    source_branch_match: bool = False
    target_branch_present: bool = False
    comments_retrieved: bool = False


class GitHubValidationResult(BaseModel):
    agent: str = "orchestrator"
    status: ValidationStatus
    checks: GitHubChecks
    errors: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MergeResultStatus(str, Enum):
    MERGED = "MERGED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    MERGE_FAILED = "MERGE_FAILED"
    ERROR = "ERROR"


class MergeChecks(BaseModel):
    pr_is_open: bool = False
    pr_not_merged: bool = False
    pr_not_closed: bool = False
    pr_is_mergeable: bool = False
    l3_approved: bool = False
    jira_validation_pass: bool = False


class MergeResult(BaseModel):
    agent: str = "merge"
    status: MergeResultStatus
    merged: bool = False
    checks: MergeChecks
    errors: list[str] = Field(default_factory=list)
    merge_sha: str | None = None
    merge_method: str | None = None
    started_at: datetime | None = None
    merged_at: datetime | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
