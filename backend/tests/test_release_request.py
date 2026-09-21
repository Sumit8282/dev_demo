"""Release request model validation tests."""

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.release import ReleaseRequest


def test_release_request_requires_qa_reason_when_signoff_not_required():
    with pytest.raises(ValidationError) as exc_info:
        ReleaseRequest(
            release_branch="release/v2.4.0",
            github_pr_url="https://github.com/company/repo/pull/1",
            jira_url="https://company.atlassian.net/browse/ABC-1",
            qa_signoff_required=False,
            environment="UAT",
            release_date=date(2026, 8, 13),
        )
    assert "qa_signoff_not_required_reason" in str(exc_info.value)


def test_release_request_accepts_qa_reason_when_signoff_not_required():
    request = ReleaseRequest(
        release_branch="release/v2.4.0",
        github_pr_url="https://github.com/company/repo/pull/1",
        jira_url="https://company.atlassian.net/browse/ABC-1",
        qa_signoff_required=False,
        qa_signoff_not_required_reason="Documentation-only change",
        environment="UAT",
        release_date=date(2026, 8, 13),
    )
    assert request.qa_signoff_not_required_reason == "Documentation-only change"
    assert request.qa_mode.value == "not_required"


def test_release_request_pr_tests_mode_does_not_need_attachment_reason():
    request = ReleaseRequest(
        release_branch="release/v2.4.0",
        github_pr_url="https://github.com/company/repo/pull/1",
        jira_url="https://company.atlassian.net/browse/ABC-1",
        qa_signoff_required=True,
        qa_mode="pr_tests",
        environment="UAT",
        release_date=date(2026, 8, 13),
    )
    assert request.qa_mode.value == "pr_tests"
    assert request.qa_signoff_required is True


def test_release_request_github_issues_mode_does_not_need_attachment_reason():
    request = ReleaseRequest(
        release_branch="release/v2.4.0",
        github_pr_url="https://github.com/company/repo/pull/1",
        jira_url="https://company.atlassian.net/browse/ABC-1",
        qa_signoff_required=True,
        qa_mode="github_issues",
        environment="UAT",
        release_date=date(2026, 8, 13),
    )
    assert request.qa_mode.value == "github_issues"
    assert request.qa_signoff_required is True


def test_release_request_github_issues_allows_empty_jira():
    request = ReleaseRequest(
        release_branch="release/v2.4.0",
        github_pr_url="https://github.com/company/repo/pull/1",
        jira_url="",
        qa_signoff_required=True,
        qa_mode="github_issues",
        environment="UAT",
        release_date=date(2026, 8, 13),
    )
    assert request.jira_url is None
    assert request.qa_mode.value == "github_issues"


def test_release_request_pr_tests_rejects_empty_jira():
    with pytest.raises(ValidationError) as exc_info:
        ReleaseRequest(
            release_branch="release/v2.4.0",
            github_pr_url="https://github.com/company/repo/pull/1",
            jira_url="",
            qa_signoff_required=True,
            qa_mode="pr_tests",
            environment="UAT",
            release_date=date(2026, 8, 13),
        )
    assert "jira_url" in str(exc_info.value)


def test_release_request_upload_rejects_missing_jira():
    with pytest.raises(ValidationError) as exc_info:
        ReleaseRequest(
            release_branch="release/v2.4.0",
            github_pr_url="https://github.com/company/repo/pull/1",
            qa_signoff_required=True,
            qa_mode="upload",
            environment="UAT",
            release_date=date(2026, 8, 13),
        )
    assert "jira_url" in str(exc_info.value)
