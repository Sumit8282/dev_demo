"""Jira MCP client unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.mcp.jira_mcp import GET_JIRA_ISSUE_FIELDS, JiraMCPClient, find_transition_id_for_status


@pytest.fixture
def jira_client():
    client = JiraMCPClient()
    client._tools = [MagicMock(name="getJiraIssue")]
    client._tools[0].name = "getJiraIssue"
    client._cloud_id = "cloud-123"
    client.call_tool = AsyncMock(
        return_value={
            "key": "SCRUM-6",
            "fields": {
                "status": {"name": "Resolved"},
                "fixVersions": [{"name": "feature/SCRUM-6-offering"}],
            },
        }
    )
    return client


@pytest.mark.asyncio
async def test_get_issue_requests_fix_versions_and_status(jira_client):
    await jira_client.get_issue("SCRUM-6")

    jira_client.call_tool.assert_awaited_once_with(
        "getJiraIssue",
        {
            "cloudId": "cloud-123",
            "issueIdOrKey": "SCRUM-6",
            "fields": GET_JIRA_ISSUE_FIELDS,
        },
    )


@pytest.mark.asyncio
async def test_get_issue_returns_issue_payload(jira_client):
    issue = await jira_client.get_issue("SCRUM-6")

    assert issue["key"] == "SCRUM-6"
    assert issue["fields"]["fixVersions"][0]["name"] == "feature/SCRUM-6-offering"


@pytest.mark.asyncio
async def test_get_transitions_requests_rovo_payload(jira_client):
    jira_client._tools = [
        MagicMock(name="getJiraIssue"),
        MagicMock(name="getTransitionsForJiraIssue"),
    ]
    jira_client._tools[0].name = "getJiraIssue"
    jira_client._tools[1].name = "getTransitionsForJiraIssue"
    jira_client.call_tool = AsyncMock(
        return_value={"transitions": [{"id": "11", "name": "Release", "to": {"name": "Release"}}]}
    )

    transitions = await jira_client.get_transitions("SCRUM-6")

    assert transitions[0]["id"] == "11"
    jira_client.call_tool.assert_awaited()


@pytest.mark.asyncio
async def test_add_comment_requests_rovo_payload(jira_client):
    jira_client.call_tool = AsyncMock(return_value={"id": "10001"})
    jira_client._tools = [
        MagicMock(name="getJiraIssue"),
        MagicMock(name="addCommentToJiraIssue"),
    ]
    jira_client._tools[0].name = "getJiraIssue"
    jira_client._tools[1].name = "addCommentToJiraIssue"

    result = await jira_client.add_comment("SCRUM-6", "Build complete")

    assert result["id"] == "10001"
    jira_client.call_tool.assert_awaited()


def test_find_transition_id_matches_released_alias():
    transitions = [{"id": "52", "name": "Released", "to": {"name": "Released"}}]
    assert find_transition_id_for_status(transitions, "Release") == "52"
    assert find_transition_id_for_status(transitions, "Released") == "52"
