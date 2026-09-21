"""Orchestrator agent tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.orchestrator import Orchestrator
from app.agents.orchestrator_agent import ReleaseOrchestratorAgent, build_release_orchestrator
from app.config import Settings
from app.models.release import WorkflowStatus
from tests.agent_stubs import stub_jira_agent, stub_qa_agent


@pytest.fixture(autouse=True)
def disable_orchestrator_llm(monkeypatch):
    monkeypatch.setattr("app.agents.llm_runner.resolve_chat_model", lambda settings=None: None)



@pytest.fixture
def llm_settings():
    return Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4.1",
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
    )


@pytest.mark.asyncio
async def test_orchestrator_runs_validations_in_order(sample_state, llm_settings, medium_risk):
    github_client = MagicMock()
    github_client.tool_names = ["pull_request_read"]
    github_client.get_pull_request_tool_name.return_value = "pull_request_read"
    github_client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
            "title": "Test PR",
        }
    )
    github_client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    github_client.get_pull_request_files = AsyncMock(return_value=[])
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)

    jira_agent = stub_jira_agent()
    qa_agent = stub_qa_agent()
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )
    release_agent = ReleaseOrchestratorAgent(orchestrator=orchestrator, settings=llm_settings)

    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True):
        result = await release_agent.ainvoke(sample_state)

    jira_agent.validate.assert_awaited_once()
    qa_agent.validate_async.assert_awaited_once()
    assert result["workflow_status"] == WorkflowStatus.L3_APPROVAL_PENDING.value
    assert result.get("github_validation") is not None
    assert result.get("jira_validation") is not None
    assert result.get("qa_validation") is not None


@pytest.mark.asyncio
async def test_orchestrator_low_risk_auto_merge(sample_state, llm_settings, low_risk):
    github_client = MagicMock()
    github_client.tool_names = ["pull_request_read", "merge_pull_request"]
    github_client.get_pull_request_tool_name.return_value = "pull_request_read"
    github_client.get_merge_pull_request_tool_name.return_value = "merge_pull_request"
    github_client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "mergeable": True,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
            "title": "Test PR",
        }
    )
    github_client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    github_client.get_pull_request_files = AsyncMock(return_value=[])
    github_client.merge_pull_request = AsyncMock(
        return_value={"merged": True, "sha": "abc123def456"}
    )
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)

    jira_agent = stub_jira_agent()
    qa_agent = stub_qa_agent()
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )
    release_agent = ReleaseOrchestratorAgent(orchestrator=orchestrator, settings=llm_settings)

    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True):
        result = await release_agent.ainvoke(sample_state)

    assert result["workflow_status"] == WorkflowStatus.MERGED.value
    assert result["l3_approval_request"]["status"] == "APPROVED"
    github_client.merge_pull_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_orchestrator_skips_jira_and_qa_when_github_fails(sample_state, llm_settings):
    github_client = MagicMock()
    github_client.tool_names = ["pull_request_read"]
    github_client.get_pull_request_tool_name.return_value = "pull_request_read"
    github_client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "user": {"login": "dev1"},
            "head": {"ref": "feature/wrong-branch"},
            "base": {"ref": "main"},
        }
    )
    github_client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    github_client.get_pull_request_files = AsyncMock(return_value=[])
    github_client.add_pull_request_comment = AsyncMock(return_value=None)
    github_client.get_add_comment_tool_name.return_value = "add_issue_comment"
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)

    jira_agent = stub_jira_agent()
    qa_agent = stub_qa_agent()
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )

    result = await build_release_orchestrator(orchestrator).ainvoke(sample_state)

    jira_agent.validate.assert_not_awaited()
    qa_agent.validate_async.assert_not_awaited()
    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result.get("jira_validation") is None


@pytest.mark.asyncio
async def test_orchestrator_skips_qa_when_jira_fails(sample_state, llm_settings):
    github_client = MagicMock()
    github_client.tool_names = ["pull_request_read"]
    github_client.get_pull_request_tool_name.return_value = "pull_request_read"
    github_client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
        }
    )
    github_client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    github_client.get_pull_request_files = AsyncMock(return_value=[])
    github_client.add_pull_request_comment = AsyncMock(return_value=None)
    github_client.get_add_comment_tool_name.return_value = "add_issue_comment"
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)

    from app.models.validation import JiraChecks, ValidationStatus

    jira_agent = stub_jira_agent(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(ticket_exists=True, status_valid=False, fix_version_match=True),
        errors=["Invalid Jira status"],
    )
    qa_agent = stub_qa_agent()
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )

    result = await build_release_orchestrator(orchestrator).ainvoke(sample_state)

    jira_agent.validate.assert_awaited_once()
    qa_agent.validate_async.assert_not_awaited()
    assert result["workflow_status"] == WorkflowStatus.HALTED.value
    assert result.get("qa_validation") is None


def _open_pr_github_client():
    github_client = MagicMock()
    github_client.tool_names = ["pull_request_read", "add_issue_comment"]
    github_client.get_pull_request_tool_name.return_value = "pull_request_read"
    github_client.get_add_comment_tool_name.return_value = "add_issue_comment"
    github_client.get_pull_request = AsyncMock(
        return_value={
            "number": 123,
            "state": "open",
            "merged": False,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
            "title": "Test PR",
        }
    )
    github_client.get_pull_request_comments = AsyncMock(return_value={"comments": []})
    github_client.get_pull_request_files = AsyncMock(return_value=[])
    github_client.add_pull_request_comment = AsyncMock(return_value=None)
    github_client.__aenter__ = AsyncMock(return_value=github_client)
    github_client.__aexit__ = AsyncMock(return_value=None)
    return github_client


@pytest.mark.asyncio
async def test_skips_failure_comment_after_github_pass(sample_state):
    from app.agents.tools.orchestrator_tools import build_orchestrator_tools
    from app.agents.workflow_context import WorkflowRunContext
    from app.models.validation import ValidationStatus

    github_client = _open_pr_github_client()
    orchestrator = Orchestrator(
        jira_agent=stub_jira_agent(),
        qa_agent=stub_qa_agent(),
        github_client=github_client,
    )
    ctx = WorkflowRunContext(state=sample_state)
    tools = {item.name: item for item in build_orchestrator_tools(orchestrator, ctx)}

    github_payload = await tools["validate_github_pull_request"].ainvoke({})
    assert github_payload["status"] == ValidationStatus.PASS.value
    assert github_payload["next_action"] == "validate_jira_ticket"

    comment_result = await tools["post_release_failure_comment"].ainvoke(
        {"comment_body": "Release Validation Failed"}
    )
    assert "Skipped" in comment_result
    assert ctx.github_comment_posted is False
    github_client.add_pull_request_comment.assert_not_awaited()


@pytest.mark.asyncio
async def test_recovers_when_llm_skips_jira_after_github_pass(sample_state, medium_risk):
    from app.agents.tools.orchestrator_tools import (
        build_orchestrator_tools,
        run_orchestrator_tool_sequence,
    )
    from app.agents.workflow_context import WorkflowRunContext
    from app.models.validation import ValidationStatus

    github_client = _open_pr_github_client()
    jira_agent = stub_jira_agent()
    qa_agent = stub_qa_agent()
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )
    ctx = WorkflowRunContext(state=sample_state)
    tools = {item.name: item for item in build_orchestrator_tools(orchestrator, ctx)}

    await tools["validate_github_pull_request"].ainvoke({})
    assert ctx.github_validation.status == ValidationStatus.PASS
    ctx.github_comment_posted = True
    ctx.tool_calls.append("post_release_failure_comment")

    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True):
        await run_orchestrator_tool_sequence(orchestrator, ctx)

    jira_agent.validate.assert_awaited_once()
    qa_agent.validate_async.assert_awaited_once()
    assert ctx.jira_validation is not None
    assert ctx.qa_validation is not None
    assert ctx.l3_flow is not None
    assert ctx.l3_flow["workflow_status"] == WorkflowStatus.L3_APPROVAL_PENDING.value


@pytest.mark.asyncio
async def test_skips_jira_when_qa_mode_is_github_issues(sample_state, medium_risk):
    from app.agents.tools.orchestrator_tools import (
        build_orchestrator_tools,
        run_orchestrator_tool_sequence,
    )
    from app.agents.workflow_context import WorkflowRunContext
    from app.models.validation import ValidationStatus

    github_client = _open_pr_github_client()
    jira_agent = stub_jira_agent()
    qa_agent = stub_qa_agent()
    state = {
        **sample_state,
        "qa_mode": "github_issues",
        "jira_url": "",
        "jira_issue_key": "",
    }
    orchestrator = Orchestrator(
        jira_agent=jira_agent,
        qa_agent=qa_agent,
        github_client=github_client,
    )
    ctx = WorkflowRunContext(state=state)
    tools = {item.name: item for item in build_orchestrator_tools(orchestrator, ctx)}

    github_payload = await tools["validate_github_pull_request"].ainvoke({})
    assert github_payload["next_action"] == "validate_qa_signoff"

    with patch("app.agents.orchestrator.send_l3_approval_mail", return_value=True):
        await run_orchestrator_tool_sequence(orchestrator, ctx)

    jira_agent.validate.assert_not_awaited()
    qa_agent.validate_async.assert_awaited_once()
    assert ctx.jira_validation is None
    assert ctx.qa_validation is not None
    assert ctx.l3_flow is not None
    messages = [event["message"] for event in ctx.workflow_events]
    assert "GitHub issues scope validation started" in messages
    assert "GitHub issues scope validation completed — PASS" in messages
    assert not any("Failed to transition Jira" in message for message in messages)
