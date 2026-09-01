"""Official GitHub MCP client (remote HTTP or local stdio via Docker)."""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx2
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings, get_settings
from app.mcp.client_base import MCPClientBase, MCPConnectionError

logger = logging.getLogger(__name__)

INVALID_PR_URL_MESSAGE = (
    "pull_request_read failed: Provide the valid url this url is invalid"
)

_INVALID_PR_READ_MARKERS = (
    "missing required parameter",
    "not found",
    "404",
    "does not exist",
    "could not find",
    "unknown pull request",
    "no pull request found",
    "pull request not found",
    "provide the valid url",
)


def is_invalid_pr_read_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return any(marker in text for marker in _INVALID_PR_READ_MARKERS)


class GitHubMCPClient(MCPClientBase):
    """Real GitHub MCP integration – no direct REST fallback."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__("github_mcp")
        self.settings = settings or get_settings()
        self._http_client: httpx2.AsyncClient | None = None

    def _token(self) -> str:
        token = self.settings.github_personal_access_token.get_secret_value().strip()
        if not token:
            raise MCPConnectionError(
                "[GITHUB_MCP] GITHUB_PERSONAL_ACCESS_TOKEN must be configured"
            )
        return token

    async def _create_mcp_client(self) -> Client:
        if self.settings.github_mcp_transport == "stdio":
            return self._create_stdio_client()
        return self._create_http_client()

    def _create_http_client(self) -> Client:
        headers = {"Authorization": f"Bearer {self._token()}"}
        self._http_client = httpx2.AsyncClient(
            headers=headers,
            timeout=httpx2.Timeout(30.0, read=300.0),
            follow_redirects=True,
        )
        transport = streamable_http_client(
            self.settings.github_mcp_url,
            http_client=self._http_client,
        )
        return Client(transport)

    def _create_stdio_client(self) -> Client:
        token = self._token()
        env = os.environ.copy()
        env["GITHUB_PERSONAL_ACCESS_TOKEN"] = token
        env["GITHUB_TOOLSETS"] = self.settings.github_mcp_toolsets

        server_params = StdioServerParameters(
            command="docker",
            args=[
                "run",
                "-i",
                "--rm",
                "-e",
                "GITHUB_PERSONAL_ACCESS_TOKEN",
                "-e",
                "GITHUB_TOOLSETS",
                self.settings.github_mcp_docker_image,
            ],
            env=env,
        )
        return Client(stdio_client(server_params))

    def get_pull_request_tool_name(self) -> str:
        for required in [("pull_request", "read"), ("pull", "request"), ("pr", "read")]:
            try:
                return self.find_tool(required_keywords=list(required))
            except Exception:
                continue

        for tool in self._tools:
            name = tool.name.lower()
            if "pull_request" in name or name == "pull_request_read":
                return tool.name

        raise MCPConnectionError(
            "[GITHUB_MCP] No pull request read tool available. "
            f"Discovered tools: {self.tool_names}"
        )

    def get_add_comment_tool_name(self) -> str:
        preferred_tools = ("add_issue_comment", "add_reply_to_pull_request_comment")
        for preferred in preferred_tools:
            for tool in self._tools:
                if tool.name == preferred:
                    return tool.name

        for required in [
            ("add", "issue", "comment"),
            ("issue", "comment"),
        ]:
            try:
                return self.find_tool(
                    required_keywords=list(required),
                    exclude_keywords=["pending", "review"],
                )
            except Exception:
                continue

        for tool in self._tools:
            name = tool.name.lower()
            if "pending" in name or "review" in name:
                continue
            if "comment" in name and ("add" in name or "issue" in name):
                return tool.name

        raise MCPConnectionError(
            "[GITHUB_MCP] No PR comment tool available. "
            f"Discovered tools: {self.tool_names}"
        )

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        tool_name = self.get_pull_request_tool_name()
        argument_sets = [
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get",
            },
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "method": "get",
            },
            {
                "owner": owner,
                "repo": repo,
                "issue_number": pull_number,
                "method": "get",
            },
        ]
        last_error: Exception | None = None
        for arguments in argument_sets:
            try:
                result = await self.call_tool(tool_name, arguments)
                if isinstance(result, dict):
                    return result
                if isinstance(result, str) and result.strip():
                    return {"raw": result}
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            if is_invalid_pr_read_error(last_error):
                raise MCPConnectionError(INVALID_PR_URL_MESSAGE) from last_error
            raise last_error
        raise MCPConnectionError(INVALID_PR_URL_MESSAGE)

    async def get_pull_request_comments(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any] | list[Any]:
        tool_name = self.get_pull_request_tool_name()
        argument_sets = [
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_comments",
            },
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "method": "get_comments",
            },
            {
                "owner": owner,
                "repo": repo,
                "issue_number": pull_number,
                "method": "get_comments",
            },
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_review_comments",
            },
        ]
        last_error: Exception | None = None
        for arguments in argument_sets:
            try:
                result = await self.call_tool(tool_name, arguments)
                if isinstance(result, (dict, list)):
                    return result
                if isinstance(result, str) and result.strip():
                    return {"raw": result}
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise MCPConnectionError(
            f"[GITHUB_MCP] Unable to read comments for PR {owner}/{repo}#{pull_number}"
        )

    async def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any] | list[Any]:
        """Return changed files for a pull request (filename, additions, deletions, status)."""
        tool_name = self.get_pull_request_tool_name()
        argument_sets = [
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "method": "get_files",
            },
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "method": "get_files",
            },
            {
                "owner": owner,
                "repo": repo,
                "issue_number": pull_number,
                "method": "get_files",
            },
        ]
        last_error: Exception | None = None
        for arguments in argument_sets:
            try:
                result = await self.call_tool(tool_name, arguments)
                if isinstance(result, (dict, list)):
                    return result
                if isinstance(result, str) and result.strip():
                    return {"raw": result}
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise MCPConnectionError(
            f"[GITHUB_MCP] Unable to read changed files for PR {owner}/{repo}#{pull_number}"
        )

    async def add_pull_request_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
    ) -> None:
        tool_name = self.get_add_comment_tool_name()
        argument_sets = [
            {
                "owner": owner,
                "repo": repo,
                "issue_number": pull_number,
                "body": body,
            },
            {
                "owner": owner,
                "repo": repo,
                "pullNumber": pull_number,
                "body": body,
            },
            {
                "owner": owner,
                "repo": repo,
                "pull_number": pull_number,
                "body": body,
            },
        ]
        last_error: Exception | None = None
        for arguments in argument_sets:
            try:
                await self.call_tool(tool_name, arguments)
                return
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        raise MCPConnectionError(
            f"[GITHUB_MCP] Unable to post comment on PR {owner}/{repo}#{pull_number}"
        )

    def get_merge_pull_request_tool_name(self) -> str:
        preferred_tools = ("merge_pull_request", "githubMergePullRequest")
        for preferred in preferred_tools:
            for tool in self._tools:
                if tool.name == preferred:
                    return tool.name

        for required in [
            ("merge", "pull", "request"),
            ("merge", "pull_request"),
        ]:
            try:
                return self.find_tool(required_keywords=list(required))
            except Exception:
                continue

        for tool in self._tools:
            name = tool.name.lower()
            if "merge" in name and "pull" in name:
                return tool.name

        raise MCPConnectionError(
            "[GITHUB_MCP] No pull request merge tool available. "
            f"Discovered tools: {self.tool_names}"
        )

    async def merge_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        *,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        tool_name = self.get_merge_pull_request_tool_name()
        arguments: dict[str, Any] = {
            "owner": owner,
            "repo": repo,
            "pullNumber": int(pull_number),
            "merge_method": merge_method,
        }
        if commit_title:
            arguments["commit_title"] = commit_title
        if commit_message:
            arguments["commit_message"] = commit_message

        result = await self.call_tool(tool_name, arguments)
        if isinstance(result, dict):
            return result
        if isinstance(result, str) and result.strip():
            return {"raw": result}
        raise MCPConnectionError(
            f"[GITHUB_MCP] Unable to merge PR {owner}/{repo}#{pull_number}"
        )
