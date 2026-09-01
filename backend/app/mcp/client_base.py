"""Base MCP client abstractions using MCP Python SDK v2."""

from __future__ import annotations

import json
import logging
from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from typing import Any

from mcp.client import Client
from mcp_types import Tool

logger = logging.getLogger(__name__)


class MCPConnectionError(Exception):
    """Raised when MCP connection or authentication fails."""


class MCPToolNotFoundError(Exception):
    """Raised when a required MCP tool is unavailable."""


class MCPClientBase(ABC):
    """Reusable MCP client with dynamic tool discovery."""

    def __init__(self, name: str) -> None:
        self.name = name
        self._client: Client | None = None
        self._exit_stack = AsyncExitStack()
        self._tools: list[Tool] = []

    @abstractmethod
    async def _create_mcp_client(self) -> Client:
        """Create configured MCP Client instance."""

    async def connect(self) -> None:
        client = await self._create_mcp_client()
        self._client = await self._exit_stack.enter_async_context(client)
        tools_result = await self._client.list_tools()
        self._tools = tools_result.tools
        logger.info(
            "[%s] Connected. Discovered %d tools: %s",
            self.name.upper(),
            len(self._tools),
            ", ".join(tool.name for tool in self._tools),
        )

    async def disconnect(self) -> None:
        await self._exit_stack.aclose()
        self._client = None
        self._tools = []

    @property
    def tool_names(self) -> list[str]:
        return [tool.name for tool in self._tools]

    def find_tool(
        self,
        *,
        required_keywords: list[str],
        optional_keywords: list[str] | None = None,
        exclude_keywords: list[str] | None = None,
    ) -> str:
        optional_keywords = optional_keywords or []
        exclude_keywords = exclude_keywords or []
        candidates: list[tuple[int, str]] = []

        for tool in self._tools:
            name_lower = tool.name.lower()
            if any(excluded in name_lower for excluded in exclude_keywords):
                continue
            if not all(keyword in name_lower for keyword in required_keywords):
                continue
            score = sum(1 for keyword in optional_keywords if keyword in name_lower)
            candidates.append((score, tool.name))

        if not candidates:
            raise MCPToolNotFoundError(
                f"[{self.name}] No tool found matching keywords {required_keywords}. "
                f"Available tools: {self.tool_names}"
            )

        candidates.sort(key=lambda item: (-item[0], item[1]))
        selected = candidates[0][1]
        logger.debug("[%s] Selected tool %s", self.name.upper(), selected)
        return selected

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        if not self._client:
            raise MCPConnectionError(f"[{self.name}] MCP session is not connected")

        logger.info("[%s] Calling tool %s", self.name.upper(), name)
        result = await self._client.call_tool(name, arguments)

        if result.is_error:
            error_text = _extract_text_content(result.content)
            raise MCPConnectionError(
                f"[{self.name}] Tool {name} failed: {error_text or 'Unknown MCP error'}"
            )

        if result.structured_content is not None:
            return result.structured_content

        return _normalize_tool_result(result.content)

    async def __aenter__(self) -> MCPClientBase:
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.disconnect()


def _extract_text_content(content: list[Any]) -> str:
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _normalize_tool_result(content: list[Any]) -> Any:
    if not content:
        return None

    texts = [_extract_text_content([block]) for block in content]
    combined = "\n".join(part for part in texts if part).strip()
    if not combined:
        return None

    try:
        return json.loads(combined)
    except json.JSONDecodeError:
        return combined
