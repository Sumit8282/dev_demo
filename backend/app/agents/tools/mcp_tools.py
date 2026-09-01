"""LangChain tool adapters for existing MCP clients."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain.tools import tool

from app.mcp.github_mcp import GitHubMCPClient
from app.mcp.jira_mcp import JiraMCPClient


async def _with_github_client(
    github_client: GitHubMCPClient | None,
    operation: Callable[[GitHubMCPClient], Awaitable[Any]],
) -> Any:
    if github_client is not None:
        if not github_client.tool_names:
            await github_client.connect()
        return await operation(github_client)

    async with GitHubMCPClient() as client:
        return await operation(client)


async def _with_jira_client(
    jira_client: JiraMCPClient | None,
    operation: Callable[[JiraMCPClient], Awaitable[Any]],
) -> Any:
    if jira_client is not None:
        if not jira_client.tool_names:
            await jira_client.connect()
        return await operation(jira_client)

    async with JiraMCPClient() as client:
        return await operation(client)


def build_github_mcp_tools(
    github_client: GitHubMCPClient | None = None,
) -> list:
    """Expose GitHub MCP operations as LangChain tools for the orchestrator."""

    @tool
    async def get_pull_request(owner: str, repo: str, pull_number: int) -> dict:
        """Read a GitHub pull request using GitHub MCP."""

        async def _read(client: GitHubMCPClient) -> dict:
            return await client.get_pull_request(owner, repo, pull_number)

        result = await _with_github_client(github_client, _read)
        return result if isinstance(result, dict) else {"raw": result}

    @tool
    async def post_pull_request_comment(
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
    ) -> str:
        """Post a comment on a GitHub pull request using GitHub MCP."""

        async def _comment(client: GitHubMCPClient) -> str:
            await client.add_pull_request_comment(owner, repo, pull_number, body)
            return "Comment posted successfully."

        return await _with_github_client(github_client, _comment)

    @tool
    async def merge_pull_request(owner: str, repo: str, pull_number: int) -> dict:
        """Merge a GitHub pull request using GitHub MCP."""

        async def _merge(client: GitHubMCPClient) -> dict:
            result = await client.merge_pull_request(owner, repo, pull_number)
            return result if isinstance(result, dict) else {"raw": result}

        return await _with_github_client(github_client, _merge)

    return [get_pull_request, post_pull_request_comment, merge_pull_request]


def build_jira_mcp_tools(jira_client: JiraMCPClient | None = None) -> list:
    """Expose Jira Rovo MCP operations as LangChain tools for the Jira agent."""

    @tool
    async def get_jira_issue(issue_key: str) -> dict:
        """Retrieve a Jira issue by key using Jira Rovo MCP."""

        async def _fetch(client: JiraMCPClient) -> dict:
            return await client.get_issue(issue_key)

        result = await _with_jira_client(jira_client, _fetch)
        return result if isinstance(result, dict) else {"raw": result}

    return [get_jira_issue]
