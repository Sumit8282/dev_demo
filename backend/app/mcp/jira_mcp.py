"""Atlassian Rovo MCP client using streamable HTTP and Basic auth."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx2
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings, get_settings
from app.mcp.client_base import MCPClientBase, MCPConnectionError

logger = logging.getLogger(__name__)

# Rovo getJiraIssue returns a minimal payload by default; request fields explicitly.
GET_JIRA_ISSUE_FIELDS = ["status", "fixVersions", "description"]


class JiraMCPClient(MCPClientBase):
    """Real Atlassian Rovo MCP integration."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__("jira_mcp")
        self.settings = settings or get_settings()
        self._http_client: httpx2.AsyncClient | None = None
        self._cloud_id: str | None = None

    def _build_auth_header(self) -> str:
        settings = self.settings
        email = settings.jira_email.strip()
        token = settings.jira_api_token.get_secret_value().strip()
        if not email or not token:
            settings = get_settings()
            email = settings.jira_email.strip()
            token = settings.jira_api_token.get_secret_value().strip()
        if not email or not token:
            raise MCPConnectionError(
                "[JIRA_MCP] JIRA_EMAIL and JIRA_API_TOKEN must be configured"
            )
        credentials = f"{email}:{token}".encode("utf-8")
        encoded = base64.b64encode(credentials).decode("ascii")
        return f"Basic {encoded}"

    async def _create_mcp_client(self) -> Client:
        headers = {"Authorization": self._build_auth_header()}
        self._http_client = httpx2.AsyncClient(
            headers=headers,
            timeout=httpx2.Timeout(30.0, read=300.0),
            follow_redirects=True,
        )
        transport = streamable_http_client(
            self.settings.jira_mcp_url,
            http_client=self._http_client,
        )
        return Client(transport)

    async def resolve_cloud_id(self) -> str:
        """Resolve Atlassian cloud ID required by Rovo MCP Jira tools."""
        if self._cloud_id:
            return self._cloud_id

        configured = self.settings.jira_cloud_id.strip()
        if configured:
            self._cloud_id = configured
            return configured

        resources = await self.call_tool("getAccessibleAtlassianResources", {})
        cloud_id = _extract_cloud_id(resources)
        if not cloud_id:
            raise MCPConnectionError(
                "[JIRA_MCP] Unable to resolve Atlassian cloudId via "
                "getAccessibleAtlassianResources. Set JIRA_CLOUD_ID in .env."
            )

        self._cloud_id = cloud_id
        logger.info("[JIRA_MCP] Resolved cloudId")
        return cloud_id

    def get_issue_tool_name(self) -> str:
        """Resolve the real Jira issue retrieval tool."""
        exclude_keywords = [
            "comment",
            "create",
            "edit",
            "transition",
            "search",
            "link",
            "worklog",
        ]

        for tool in self._tools:
            if tool.name == "getJiraIssue":
                return tool.name

        tool_name_candidates: list[tuple[list[str], list[str]]] = [
            (["get", "jira", "issue"], ["get"]),
            (["get", "issue"], ["get"]),
            (["read", "issue"], ["read"]),
        ]
        for required, optional in tool_name_candidates:
            try:
                return self.find_tool(
                    required_keywords=required,
                    optional_keywords=optional,
                    exclude_keywords=exclude_keywords,
                )
            except Exception:
                continue

        for tool in self._tools:
            name = tool.name.lower()
            if any(excluded in name for excluded in exclude_keywords):
                continue
            if "issue" in name and any(
                keyword in name for keyword in ("get", "read", "fetch", "retrieve")
            ):
                return tool.name

        raise MCPConnectionError(
            "[JIRA_MCP] No Jira issue retrieval tool available. "
            f"Discovered tools: {self.tool_names}"
        )

    async def get_issue(self, issue_key: str, *, fields: list[str] | None = None) -> dict[str, Any]:
        tool_name = self.get_issue_tool_name()
        issue_fields = fields or GET_JIRA_ISSUE_FIELDS
        argument_sets: list[dict[str, Any]] = []

        if tool_name == "getJiraIssue":
            cloud_id = await self.resolve_cloud_id()
            argument_sets = [
                {
                    "cloudId": cloud_id,
                    "issueIdOrKey": issue_key,
                    "fields": issue_fields,
                },
            ]
        else:
            argument_sets = [
                {"issueKey": issue_key},
                {"issue_key": issue_key},
                {"issueIdOrKey": issue_key},
                {"key": issue_key},
                {"issue": issue_key},
                {"issueId": issue_key},
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
            raise last_error
        raise MCPConnectionError(
            f"[JIRA_MCP] Unable to retrieve issue {issue_key} using tool {tool_name}"
        )

    def _transitions_tool_name(self) -> str:
        for tool in self._tools:
            if tool.name == "getTransitionsForJiraIssue":
                return tool.name
        return self.find_tool(
            required_keywords=["transition"],
            optional_keywords=["get", "jira"],
            exclude_keywords=["add", "comment", "create"],
        )

    def _transition_issue_tool_name(self) -> str:
        for tool in self._tools:
            if tool.name == "transitionJiraIssue":
                return tool.name
        return self.find_tool(
            required_keywords=["transition"],
            optional_keywords=["jira", "issue"],
            exclude_keywords=["get", "comment"],
        )

    def _add_comment_tool_name(self) -> str:
        for tool in self._tools:
            if tool.name == "addCommentToJiraIssue":
                return tool.name
        return self.find_tool(
            required_keywords=["comment"],
            optional_keywords=["add", "jira"],
            exclude_keywords=["get", "transition"],
        )

    async def get_transitions(self, issue_key: str) -> list[dict[str, Any]]:
        """Return available workflow transitions for a Jira issue."""
        tool_name = self._transitions_tool_name()
        cloud_id = await self.resolve_cloud_id()
        argument_sets: list[dict[str, Any]] = [
            {"cloudId": cloud_id, "issueIdOrKey": issue_key},
            {"cloudId": cloud_id, "issueKey": issue_key},
            {"issueIdOrKey": issue_key},
            {"issueKey": issue_key},
        ]

        last_error: Exception | None = None
        for arguments in argument_sets:
            try:
                result = await self.call_tool(tool_name, arguments)
                transitions = _extract_transitions(result)
                if transitions:
                    return transitions
            except Exception as exc:
                last_error = exc
                continue

        if last_error:
            raise last_error
        return []

    async def transition_issue(self, issue_key: str, transition_id: str) -> dict[str, Any]:
        """Transition a Jira issue using a transition ID from get_transitions."""
        tool_name = self._transition_issue_tool_name()
        cloud_id = await self.resolve_cloud_id()
        argument_sets: list[dict[str, Any]] = [
            {
                "cloudId": cloud_id,
                "issueIdOrKey": issue_key,
                "transition": {"id": transition_id},
            },
            {
                "cloudId": cloud_id,
                "issueIdOrKey": issue_key,
                "transitionId": transition_id,
            },
            {
                "issueIdOrKey": issue_key,
                "transition": {"id": transition_id},
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
            raise last_error
        raise MCPConnectionError(
            f"[JIRA_MCP] Unable to transition issue {issue_key} using tool {tool_name}"
        )

    async def add_comment(self, issue_key: str, body: str) -> dict[str, Any]:
        """Add a comment to a Jira issue."""
        tool_name = self._add_comment_tool_name()
        cloud_id = await self.resolve_cloud_id()
        argument_sets: list[dict[str, Any]] = [
            {
                "cloudId": cloud_id,
                "issueIdOrKey": issue_key,
                "commentBody": body,
            },
            {
                "cloudId": cloud_id,
                "issueIdOrKey": issue_key,
                "body": body,
            },
            {
                "issueIdOrKey": issue_key,
                "commentBody": body,
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
            raise last_error
        raise MCPConnectionError(
            f"[JIRA_MCP] Unable to add comment on issue {issue_key} using tool {tool_name}"
        )


def _extract_transitions(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []

    for key in ("transitions", "values", "items"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
    return []


def find_transition_id_for_status(
    transitions: list[dict[str, Any]],
    target_status: str,
) -> str | None:
    """Match a transition by destination status name (case-insensitive)."""
    targets = _expand_status_aliases(target_status)
    if not targets:
        return None

    for transition in transitions:
        transition_id = transition.get("id")
        if transition_id is None:
            continue
        transition_id_str = str(transition_id).strip()
        if not transition_id_str:
            continue

        candidates: list[str] = []
        name = transition.get("name")
        if isinstance(name, str):
            candidates.append(name)
        to_status = transition.get("to")
        if isinstance(to_status, dict):
            to_name = to_status.get("name")
            if isinstance(to_name, str):
                candidates.append(to_name)

        normalized_candidates = {candidate.strip().lower() for candidate in candidates}
        if normalized_candidates.intersection(targets):
            return transition_id_str

    return None


def _expand_status_aliases(target_status: str) -> set[str]:
    """Include common Jira status aliases (e.g. Release vs Released)."""
    target = target_status.strip().lower()
    if not target:
        return set()

    aliases = {target}
    if target == "release":
        aliases.add("released")
    elif target == "released":
        aliases.add("release")
    return aliases


def _extract_cloud_id(resources: Any) -> str | None:
    if isinstance(resources, list):
        for item in resources:
            if isinstance(item, dict):
                for key in ("id", "cloudId", "cloud_id"):
                    value = item.get(key)
                    if isinstance(value, str) and value.strip():
                        return value.strip()
    if isinstance(resources, dict):
        for key in ("id", "cloudId", "cloud_id"):
            value = resources.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        for container_key in ("resources", "values", "items"):
            nested = resources.get(container_key)
            nested_id = _extract_cloud_id(nested)
            if nested_id:
                return nested_id
    return None
