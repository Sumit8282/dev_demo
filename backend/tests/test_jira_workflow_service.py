"""Jira workflow service unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.config import Settings
from app.services.jira_workflow_service import JiraWorkflowService


@pytest.fixture
def jira_settings():
    return Settings(
        JIRA_L3_APPROVED_STATUS="Released",
        JIRA_DEPLOYMENT_COMPLETED_STATUS="Resolved",
    )


@pytest.fixture
def jira_client():
    client = MagicMock()
    client.tool_names = ["getTransitionsForJiraIssue", "transitionJiraIssue", "addCommentToJiraIssue"]
    client.get_transitions = AsyncMock(
        return_value=[
            {"id": "11", "name": "Release", "to": {"name": "Release"}},
            {"id": "21", "name": "Resolve", "to": {"name": "Resolved"}},
        ]
    )
    client.transition_issue = AsyncMock(return_value={"ok": True})
    client.add_comment = AsyncMock(return_value={"id": "10001"})
    client.connect = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_on_build_completed_adds_comment(jira_settings, jira_client):
    service = JiraWorkflowService(settings=jira_settings, jira_client=jira_client)

    with patch("app.services.jira_workflow_service.emit_workflow_event"):
        result = await service.on_build_completed(
            issue_key="SCRUM-6",
            release_id="REL-001",
            build_id="BUILD-20260817-001",
            environment="UAT2",
        )

    assert result is True
    jira_client.add_comment.assert_awaited_once()
    comment_body = jira_client.add_comment.await_args.args[1]
    assert "BUILD-20260817-001" in comment_body


@pytest.mark.asyncio
async def test_on_deployment_completed_transitions_and_comments(jira_settings, jira_client):
    service = JiraWorkflowService(settings=jira_settings, jira_client=jira_client)

    with patch("app.services.jira_workflow_service.emit_workflow_event"):
        result = await service.on_deployment_completed(
            issue_key="SCRUM-6",
            release_id="REL-001",
            environment="UAT2",
            build_id="BUILD-20260817-001",
        )

    assert result is True
    jira_client.transition_issue.assert_awaited_once_with("SCRUM-6", "21")
    jira_client.add_comment.assert_awaited_once()
    comment_body = jira_client.add_comment.await_args.args[1]
    assert "Deployment completed successfully" in comment_body
