"""End-to-end workflow tests for the release orchestrator."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator_agent import build_release_orchestrator
from app.config import Settings
from app.models.release import OverallValidationStatus, WorkflowStatus
from app.models.validation import (
    JiraChecks,
    QAChecks,
    ValidationStatus,
)
from tests.agent_stubs import stub_jira_agent, stub_qa_agent


@pytest.fixture(autouse=True)
def llm_settings(monkeypatch):
    settings = Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4.1",
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
    )
    monkeypatch.setattr("app.agents.orchestrator_agent.get_settings", lambda: settings)
    monkeypatch.setattr("app.agents.jira_agent.get_settings", lambda: settings)
    monkeypatch.setattr("app.agents.qa_agent.get_settings", lambda: settings)
    monkeypatch.setattr("app.agents.llm_runner.resolve_chat_model", lambda settings=None: None)


def _build_github_client(should_fail_comment=False, source_branch="release/v2.4.0"):
    client = MagicMock()
    client.tool_names = ["add_issue_comment", "pull_request_read"]
    client.get_pull_request_tool_name.return_value = "pull_request_read"
    client.get_add_comment_tool_name.return_value = "add_issue_comment"
    client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "mergeable": True,
            "user": {"login": "dev1"},
            "head": {"ref": source_branch},
            "base": {"ref": "main"},
        }
    )
    client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    client.get_pull_request_files = AsyncMock(return_value=[])
    client.merge_pull_request = AsyncMock(return_value={"merged": True, "sha": "abc123def456"})
    client.get_merge_pull_request_tool_name.return_value = "merge_pull_request"
    client.add_pull_request_comment = AsyncMock(
        side_effect=Exception("failed") if should_fail_comment else AsyncMock(return_value=None)
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


def _base_state(**overrides):
    state = {
        "release_id": "REL-WF001",
        "release_branch": "release/v2.4.0",
        "release_version": "v2.4.0",
        "github_pr_url": "https://github.com/company/repository/pull/123",
        "github_owner": "company",
        "github_repo": "repository",
        "github_pr_number": 123,
        "jira_url": "https://company.atlassian.net/browse/ABC-123",
        "jira_issue_key": "ABC-123",
        "qa_signoff_required": True,
        "qa_signoff_not_required_reason": None,
        "environment": "UAT2",
        "release_date": date(2026, 8, 15),
    }
    state.update(overrides)
    return state


@pytest.mark.asyncio
async def test_workflow_jira_pass_qa_pass(medium_risk):
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(),
        qa_agent=stub_qa_agent(),
        github_client=_build_github_client(),
    )
    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True):
        result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["overall_validation_status"] == OverallValidationStatus.PASS.value
    assert result["workflow_status"] == WorkflowStatus.L3_APPROVAL_PENDING.value
    assert result["github_comment_posted"] is False


@pytest.mark.asyncio
async def test_workflow_low_risk_auto_merges_and_notifies_l3(low_risk):
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(),
        qa_agent=stub_qa_agent(),
        github_client=_build_github_client(),
    )
    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True) as send_mail:
        result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["overall_validation_status"] == OverallValidationStatus.PASS.value
    assert result["workflow_status"] == WorkflowStatus.MERGED.value
    assert result["l3_approval_request"]["status"] == "APPROVED"
    assert result.get("merge_result") is not None
    assert result["merge_result"]["merged"] is True
    send_mail.assert_called_once()
    mail_draft = send_mail.call_args[0][0]
    assert "PR Merged — Release" in mail_draft.subject
    assert "Approval URL" not in mail_draft.body_text
    assert "Open L3 Approval Page" not in mail_draft.body_html
    assert "The pull request has been merged" in mail_draft.body_text
    assert "Release ID" in mail_draft.body_text


@pytest.mark.asyncio
async def test_workflow_jira_fail_halts_and_posts_comment():
    github_client = _build_github_client()
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(
            status=ValidationStatus.FAIL,
            checks=JiraChecks(ticket_exists=True, status_valid=False, fix_version_match=True),
            errors=["Invalid Jira status"],
        ),
        qa_agent=stub_qa_agent(),
        github_client=github_client,
    )
    result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result["github_comment_posted"] is True
    github_client.add_pull_request_comment.assert_awaited()


@pytest.mark.asyncio
async def test_workflow_qa_missing_halts_and_posts_comment():
    github_client = _build_github_client()
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(),
        qa_agent=stub_qa_agent(
            status=ValidationStatus.FAIL,
            checks=QAChecks(signoff_required=True, signoff_completed=False),
            errors=["QA sign-off is required but has not been completed."],
        ),
        github_client=github_client,
    )
    result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result["github_comment_posted"] is True


@pytest.mark.asyncio
async def test_workflow_github_fail_halts_before_jira():
    github_client = _build_github_client(source_branch="feature/wrong-branch")
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(),
        qa_agent=stub_qa_agent(),
        github_client=github_client,
    )
    result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result.get("jira_validation") is None
    assert "source branch" in result["failure_reasons"][0].lower()


@pytest.mark.asyncio
async def test_workflow_jira_error_validation_error():
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(status=ValidationStatus.ERROR, errors=["auth failed"]),
        qa_agent=stub_qa_agent(),
        github_client=_build_github_client(),
    )
    result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["workflow_status"] == WorkflowStatus.VALIDATION_ERROR.value
    assert result["overall_validation_status"] == OverallValidationStatus.ERROR.value


@pytest.mark.asyncio
async def test_workflow_github_comment_failure():
    github_client = _build_github_client(should_fail_comment=True)
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(status=ValidationStatus.FAIL, errors=["Jira fail"]),
        qa_agent=stub_qa_agent(),
        github_client=github_client,
    )
    result = await build_release_orchestrator(orchestrator).ainvoke(_base_state())

    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result["github_comment_posted"] is False
