"""Tests for LLM-generated L3 release summary."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.l3_change_summary_service import L3ChangeSummaryService


@pytest.fixture
def summary_service():
    return L3ChangeSummaryService(settings=MagicMock(llm_enabled=True))


@pytest.mark.asyncio
async def test_generate_summary_uses_llm_output(summary_service):
    github_validation = {
        "metadata": {
            "pr_title": "Implement SCRUM-6 offerings",
            "pr_description": "Fix Offerings dropdown navigation.",
            "comments": [{"author": "qa1", "body": "Verified in UAT"}],
        }
    }
    jira_validation = {
        "metadata": {
            "jira_description": "Offerings dropdown does not navigate correctly.",
        }
    }

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(
        content="- Fix Offerings dropdown navigation.\n- QA verified in UAT."
    )

    with patch("app.services.l3_change_summary_service.get_llm", return_value=mock_llm), patch.object(
        summary_service,
        "_fetch_jira_context",
        new=AsyncMock(return_value=(None, [])),
    ):
        summary = await summary_service.generate_summary(
            release_id="REL-001",
            jira_issue_key="SCRUM-6",
            github_validation=github_validation,
            jira_validation=jira_validation,
        )

    assert "Offerings dropdown" in summary
    mock_llm.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_generate_summary_fallback_when_llm_unavailable():
    service = L3ChangeSummaryService(settings=MagicMock(llm_enabled=False))
    github_validation = {
        "metadata": {
            "pr_title": "Implement SCRUM-6 offerings",
            "pr_description": "Fix Offerings dropdown navigation.",
            "comments": [],
        }
    }

    with patch.object(service, "_fetch_jira_context", new=AsyncMock(return_value=(None, []))):
        summary = await service.generate_summary(
            release_id="REL-001",
            jira_issue_key="SCRUM-6",
            github_validation=github_validation,
            jira_validation={},
        )

    assert "Implement SCRUM-6 offerings" in summary
    assert summary.startswith("- ")


@pytest.mark.asyncio
async def test_generate_summary_includes_jira_comments_in_prompt(summary_service):
    github_validation = {"metadata": {"pr_title": "Test", "pr_description": "Change", "comments": []}}
    jira_validation = {
        "metadata": {
            "jira_description": "Bug in navigation",
            "jira_comments": [{"author": "dev", "body": "Ready for release"}],
        }
    }

    mock_llm = AsyncMock()
    mock_llm.ainvoke.return_value = MagicMock(content="- Summary bullet")

    with patch("app.services.l3_change_summary_service.get_llm", return_value=mock_llm), patch.object(
        summary_service,
        "_fetch_jira_context",
        new=AsyncMock(return_value=(None, [])),
    ):
        await summary_service.generate_summary(
            release_id="REL-002",
            jira_issue_key="SCRUM-6",
            github_validation=github_validation,
            jira_validation=jira_validation,
        )

    user_message = mock_llm.ainvoke.await_args.args[0][1].content
    assert "Ready for release" in user_message
    assert "Bug in navigation" in user_message
