"""Structured LLM output for JIRA–PR validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.models.validation import JiraChecks, ValidationStatus


class JiraRequirementMatrixRow(BaseModel):
    requirement_id: str
    jira_requirement: str
    pr_evidence: str = ""
    status: str
    remarks: str = ""


class JiraLLMValidationOutput(BaseModel):
    status: ValidationStatus
    validation_summary: str = ""
    jira_pr_relationship: str = ""
    validation_matrix: list[JiraRequirementMatrixRow] = Field(default_factory=list)
    checks: JiraChecks = Field(default_factory=JiraChecks)
    errors: list[str] = Field(default_factory=list)
    jira_description: str = ""
    github_pr_description: str = ""
    jira_comments: list[dict[str, Any]] = Field(default_factory=list)
