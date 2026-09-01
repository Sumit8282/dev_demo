"""Debug GitHub PR file change stats via MCP."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.mcp.github_mcp import GitHubMCPClient


async def try_methods(owner: str, repo: str, pull_number: int) -> None:
    settings = get_settings()
    async with GitHubMCPClient(settings) as client:
        tool = client.get_pull_request_tool_name()
        print(f"Tool: {tool}")
        for method in (
            "get_files",
            "get_files_changed",
            "list_files",
            "get_diff",
            "get",
        ):
            for args in (
                {
                    "owner": owner,
                    "repo": repo,
                    "pullNumber": pull_number,
                    "method": method,
                },
                {
                    "owner": owner,
                    "repo": repo,
                    "pull_number": pull_number,
                    "method": method,
                },
            ):
                try:
                    result = await client.call_tool(tool, args)
                    print(f"\n=== method={method} args keys={list(args.keys())} ===")
                    print(json.dumps(result, indent=2)[:3000])
                    break
                except Exception as exc:
                    print(f"method={method} failed: {exc}")


if __name__ == "__main__":
    owner = sys.argv[1] if len(sys.argv) > 1 else "satalkar21"
    repo = sys.argv[2] if len(sys.argv) > 2 else "AI_Studio_Main"
    pull = int(sys.argv[3]) if len(sys.argv) > 3 else 11
    asyncio.run(try_methods(owner, repo, pull))
