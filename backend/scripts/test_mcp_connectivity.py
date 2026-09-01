"""Developer MCP connectivity verification."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Allow `python scripts/test_mcp_connectivity.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.logging_config import setup_logging
from app.mcp.github_mcp import GitHubMCPClient
from app.mcp.jira_mcp import JiraMCPClient


async def test_jira_mcp() -> bool:
    settings = get_settings()
    print("\n=== Jira Rovo MCP Connectivity ===")
    print(f"URL: {settings.jira_mcp_url}")
    print(f"Email configured: {'yes' if settings.jira_email else 'no'}")
    print(f"API token configured: {'yes' if settings.jira_api_token.get_secret_value() else 'no'}")

    if not settings.jira_email or not settings.jira_api_token.get_secret_value():
        print("SKIP: JIRA_EMAIL and JIRA_API_TOKEN are required.")
        return False

    try:
        async with JiraMCPClient(settings) as client:
            print("Authentication: OK")
            print(f"Discovered {len(client.tool_names)} tools:")
            for name in client.tool_names:
                print(f"  - {name}")
            issue_tool = client.get_issue_tool_name()
            print(f"Issue retrieval tool selected: {issue_tool}")
            return True
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False


async def test_github_mcp() -> bool:
    settings = get_settings()
    print("\n=== GitHub MCP Connectivity ===")
    print(f"Transport: {settings.github_mcp_transport}")
    if settings.github_mcp_transport == "http":
        print(f"URL: {settings.github_mcp_url}")
    else:
        print(f"Docker image: {settings.github_mcp_docker_image}")
    print(
        "Token configured: "
        f"{'yes' if settings.github_personal_access_token.get_secret_value() else 'no'}"
    )

    if not settings.github_personal_access_token.get_secret_value():
        print("SKIP: GITHUB_PERSONAL_ACCESS_TOKEN is required.")
        return False

    try:
        async with GitHubMCPClient(settings) as client:
            print("Authentication: OK")
            print(f"Discovered {len(client.tool_names)} tools:")
            for name in client.tool_names:
                print(f"  - {name}")
            pr_tool = client.get_pull_request_tool_name()
            comment_tool = client.get_add_comment_tool_name()
            print(f"PR read tool selected: {pr_tool}")
            print(f"PR comment tool selected: {comment_tool}")
            return True
    except Exception as exc:
        print(f"FAILED: {exc}")
        return False


async def main() -> int:
    setup_logging(get_settings().log_level)
    jira_ok = await test_jira_mcp()
    github_ok = await test_github_mcp()

    print("\n=== Summary ===")
    print(f"Jira MCP: {'PASS' if jira_ok else 'FAIL/SKIP'}")
    print(f"GitHub MCP: {'PASS' if github_ok else 'FAIL/SKIP'}")

    if jira_ok and github_ok:
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
