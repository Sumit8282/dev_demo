"""Auto-merge agent tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.merge_agent import MergeAgent
from app.models.l3_approval import L3ApprovalStatus
from app.models.validation import MergeResultStatus, ValidationStatus


@pytest.fixture(autouse=True)
def disable_merge_llm(monkeypatch):
    monkeypatch.setattr("app.agents.llm_runner.resolve_chat_model", lambda settings=None: None)


def _approved_state(sample_state):
    return {
        **sample_state,
        "workflow_status": "L3_APPROVED",
        "l3_approval_request": {
            "release_id": sample_state["release_id"],
            "status": L3ApprovalStatus.APPROVED.value,
            "approval_url": "http://localhost/approvals/l3/REL-TEST001",
            "created_at": "2026-08-14T10:00:00+00:00",
            "release_branch": sample_state["release_branch"],
            "release_version": sample_state["release_version"],
            "github_pr_url": sample_state["github_pr_url"],
            "github_pr_number": sample_state["github_pr_number"],
            "jira_url": sample_state["jira_url"],
            "jira_issue_key": sample_state["jira_issue_key"],
            "environment": sample_state["environment"],
            "release_date": sample_state["release_date"].isoformat(),
            "qa_signoff_required": sample_state["qa_signoff_required"],
        },
        "jira_validation": {
            "agent": "jira",
            "status": ValidationStatus.PASS.value,
            "checks": {
                "ticket_exists": True,
                "status_valid": True,
                "fix_version_match": True,
                "description_match": True,
            },
            "errors": [],
            "metadata": {},
        },
    }


def _build_github_client(
    *,
    pr_payload: dict | None = None,
    merge_payload: dict | None = None,
):
    client = MagicMock()
    client.tool_names = ["pull_request_read", "merge_pull_request"]
    client.get_pull_request_tool_name.return_value = "pull_request_read"
    client.get_merge_pull_request_tool_name.return_value = "merge_pull_request"
    client.get_pull_request = AsyncMock(
        return_value=pr_payload
        or {
            "number": 123,
            "state": "open",
            "merged": False,
            "mergeable": True,
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
        }
    )
    client.merge_pull_request = AsyncMock(
        return_value=merge_payload or {"merged": True, "sha": "abc123def456"}
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_merge_agent_success(sample_state):
    agent = MergeAgent(github_client=_build_github_client())
    result = await agent.execute_merge(_approved_state(sample_state))

    assert result.status == MergeResultStatus.MERGED
    assert result.merged is True
    assert result.merge_sha == "abc123def456"
    assert result.merge_method == "squash"
    assert result.started_at is not None
    assert result.merged_at is not None
    assert result.checks.l3_approved is True
    assert result.checks.jira_validation_pass is True
    assert result.checks.pr_is_open is True
    assert result.checks.pr_not_merged is True
    assert result.checks.pr_not_closed is True
    assert result.checks.pr_is_mergeable is True


@pytest.mark.asyncio
async def test_merge_agent_fails_when_workflow_not_l3_approved(sample_state):
    state = _approved_state(sample_state)
    state["workflow_status"] = "L3_APPROVAL_PENDING"

    agent = MergeAgent(github_client=_build_github_client())
    result = await agent.execute_merge(state)

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.checks.l3_approved is False
    assert any("release workflow is not l3 approved" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_merge_agent_fails_when_l3_not_approved(sample_state):
    state = _approved_state(sample_state)
    state["l3_approval_request"]["status"] = L3ApprovalStatus.PENDING.value

    agent = MergeAgent(github_client=_build_github_client())
    result = await agent.execute_merge(state)

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.merged is False
    assert result.checks.l3_approved is False
    assert any("L3 approval" in error for error in result.errors)


@pytest.mark.asyncio
async def test_merge_agent_fails_when_jira_not_pass(sample_state):
    state = _approved_state(sample_state)
    state["jira_validation"]["status"] = ValidationStatus.FAIL.value

    agent = MergeAgent(github_client=_build_github_client())
    result = await agent.execute_merge(state)

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.checks.jira_validation_pass is False
    assert any("Jira validation" in error for error in result.errors)


def test_merge_agent_skips_jira_when_github_issues_qa(sample_state):
    state = _approved_state(sample_state)
    state["qa_mode"] = "github_issues"
    state["jira_validation"] = None
    state["jira_url"] = ""
    state["jira_issue_key"] = ""

    agent = MergeAgent(github_client=_build_github_client())
    assert agent._validate_jira_pass(state) == (True, [])


@pytest.mark.asyncio
async def test_merge_agent_fails_when_pr_closed(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "state": "closed",
            "merged": False,
            "mergeable": False,
        }
    )
    agent = MergeAgent(github_client=client)
    result = await agent.execute_merge(_approved_state(sample_state))

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.checks.pr_is_open is False
    assert result.checks.pr_not_closed is False
    assert any("pr is closed" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_merge_agent_fails_when_pr_already_merged(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "state": "closed",
            "merged": True,
            "mergeable": False,
        }
    )
    agent = MergeAgent(github_client=client)
    result = await agent.execute_merge(_approved_state(sample_state))

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.checks.pr_not_merged is False
    assert any("already merged" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_merge_agent_fails_when_pr_not_mergeable(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "state": "open",
            "merged": False,
            "mergeable": False,
        }
    )
    agent = MergeAgent(github_client=client)
    result = await agent.execute_merge(_approved_state(sample_state))

    assert result.status == MergeResultStatus.VALIDATION_FAILED
    assert result.checks.pr_is_mergeable is False
    assert any("not mergeable" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_merge_agent_merge_api_failure(sample_state):
    client = _build_github_client(
        merge_payload={"merged": False, "message": "Pull Request is not mergeable"}
    )
    agent = MergeAgent(github_client=client)
    result = await agent.execute_merge(_approved_state(sample_state))

    assert result.status == MergeResultStatus.MERGE_FAILED
    assert result.merged is False
    assert "not mergeable" in result.errors[0].lower()
    assert "auto merge failed" in result.errors[0].lower()
