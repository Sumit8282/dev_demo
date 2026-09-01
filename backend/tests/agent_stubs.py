"""Stub agents for workflow tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from app.models.validation import (
    GitHubChecks,
    GitHubValidationResult,
    JiraChecks,
    JiraValidationResult,
    QAChecks,
    QAValidationResult,
    ValidationStatus,
)


def stub_jira_agent(
    *,
    status: ValidationStatus = ValidationStatus.PASS,
    errors: list[str] | None = None,
    checks: JiraChecks | None = None,
) -> MagicMock:
    agent = MagicMock()
    agent.validate = AsyncMock(
        return_value=JiraValidationResult(
            status=status,
            checks=checks
            or JiraChecks(ticket_exists=True, status_valid=True, fix_version_match=True),
            errors=errors or [],
        )
    )
    return agent


def stub_qa_agent(
    *,
    status: ValidationStatus = ValidationStatus.PASS,
    errors: list[str] | None = None,
    checks: QAChecks | None = None,
) -> MagicMock:
    agent = MagicMock()
    result = QAValidationResult(
        status=status,
        checks=checks or QAChecks(signoff_required=True, signoff_completed=True),
        errors=errors or [],
    )
    agent.validate = MagicMock(return_value=result)
    agent.validate_async = AsyncMock(return_value=result)
    return agent


def github_pass_result() -> GitHubValidationResult:
    return GitHubValidationResult(
        status=ValidationStatus.PASS,
        checks=GitHubChecks(
            pr_exists=True,
            pr_is_open=True,
            source_branch_match=True,
            target_branch_present=True,
            comments_retrieved=True,
        ),
        metadata={
            "source_branch": "release/v2.4.0",
            "target_branch": "main",
            "pull_number": 123,
            "author": "dev1",
            "raised_by": "dev1",
        },
    )
