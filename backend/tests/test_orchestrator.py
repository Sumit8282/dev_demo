"""Orchestrator unit tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.orchestrator import Orchestrator
from app.models.release import OverallValidationStatus, WorkflowStatus
from app.models.validation import (
    GitHubChecks,
    GitHubValidationResult,
    JiraChecks,
    JiraValidationResult,
    QAChecks,
    QAValidationResult,
    ValidationStatus,
)


def _pass_github() -> GitHubValidationResult:
    return GitHubValidationResult(
        status=ValidationStatus.PASS,
        checks=GitHubChecks(
            pr_exists=True,
            source_branch_match=True,
            target_branch_present=True,
            comments_retrieved=True,
        ),
    )


def test_evaluate_pass():
    orchestrator = Orchestrator()
    github = _pass_github()
    jira = JiraValidationResult(
        status=ValidationStatus.PASS,
        checks=JiraChecks(ticket_exists=True, status_valid=True, fix_version_match=True),
    )
    qa = QAValidationResult(
        status=ValidationStatus.PASS,
        checks=QAChecks(signoff_required=True, signoff_completed=True),
    )
    overall, reasons = orchestrator.evaluate_validation(github, jira, qa)
    assert overall == OverallValidationStatus.PASS
    assert reasons == []


def test_evaluate_fail_collects_all_errors():
    orchestrator = Orchestrator()
    github = GitHubValidationResult(
        status=ValidationStatus.FAIL,
        checks=GitHubChecks(pr_exists=True, source_branch_match=False),
        errors=["GitHub PR source branch mismatch"],
    )
    jira = JiraValidationResult(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(ticket_exists=True, status_valid=True, fix_version_match=False),
        errors=["Jira Fix Version mismatch"],
    )
    qa = QAValidationResult(
        status=ValidationStatus.FAIL,
        checks=QAChecks(signoff_required=True, signoff_completed=False),
        errors=["QA sign-off is missing"],
    )
    overall, reasons = orchestrator.evaluate_validation(github, jira, qa)
    assert overall == OverallValidationStatus.FAIL
    assert len(reasons) == 3


def test_evaluate_pass_when_jira_skipped():
    orchestrator = Orchestrator()
    github = _pass_github()
    qa = QAValidationResult(
        status=ValidationStatus.PASS,
        checks=QAChecks(signoff_required=True, signoff_completed=True),
    )
    overall, reasons = orchestrator.evaluate_validation(github, None, qa)
    assert overall == OverallValidationStatus.PASS
    assert reasons == []


def test_deterministic_workflow_status_pass():
    orchestrator = Orchestrator()
    assert (
        orchestrator.determine_workflow_status(OverallValidationStatus.PASS)
        == WorkflowStatus.L3_APPROVAL_PENDING
    )


def test_deterministic_workflow_status_fail():
    orchestrator = Orchestrator()
    assert (
        orchestrator.determine_workflow_status(OverallValidationStatus.FAIL)
        == WorkflowStatus.HALTED
    )


def test_failure_comment_includes_all_validations(sample_state):
    orchestrator = Orchestrator()
    github = _pass_github()
    jira = JiraValidationResult(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(),
        errors=["Jira Fix Version does not match release version v2.4.0."],
    )
    qa = QAValidationResult(
        status=ValidationStatus.FAIL,
        checks=QAChecks(signoff_required=True, signoff_completed=False),
        errors=["QA sign-off is missing."],
    )
    comment = orchestrator.build_failure_comment(
        sample_state,
        github,
        jira,
        qa,
        github.errors + jira.errors + qa.errors,
    )
    assert "GitHub PR Validation: PASS" in comment
    assert "Jira Validation: FAIL" in comment
    assert "QA Validation: FAIL" in comment


@pytest.mark.asyncio
async def test_github_comment_failure_not_reported_as_posted(sample_state):
    github_client = MagicMock()
    github_client.tool_names = ["github_rest"]
    github_client.add_pull_request_comment = AsyncMock(
        side_effect=Exception("comment failed")
    )
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)

    orchestrator = Orchestrator(github_client=github_client)
    posted = await orchestrator.post_github_failure_comment(sample_state, "test comment")
    assert posted is False


@pytest.mark.asyncio
async def test_github_comment_posts_via_rest(sample_state):
    import httpx
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.github_pr_client import GitHubPRClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/issues/123/comments"):
            return httpx.Response(201, json={"id": 99, "body": "test comment"})
        return httpx.Response(404, text="missing")

    rest_client = GitHubPRClient(
        Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("test-token")),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    orchestrator = Orchestrator(github_client=rest_client)
    posted = await orchestrator.post_github_failure_comment(sample_state, "test comment")
    assert posted is True


def test_failure_comment_appends_lane2(sample_state):
    orchestrator = Orchestrator()
    qa = QAValidationResult(
        status=ValidationStatus.FAIL,
        checks=QAChecks(signoff_required=True, signoff_completed=False),
        errors=["QA coverage failed"],
        metadata={"lane2_comment": "Suggested test: cover AC-01 empty dropdown."},
    )
    comment = orchestrator.build_failure_comment(
        sample_state,
        _pass_github(),
        JiraValidationResult(status=ValidationStatus.PASS, checks=JiraChecks()),
        qa,
        qa.errors,
    )
    assert "Suggested test: cover AC-01 empty dropdown." in comment
