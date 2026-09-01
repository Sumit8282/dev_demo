"""Live Jira agent validation against real Atlassian Rovo MCP.

Optionally fetches the GitHub PR description first (same as the orchestrator flow).

Examples (from backend/):

  # Jira only — no PR description (description_match will fail)
  python scripts/test_jira_agent.py SCRUM-6 feature/SCRUM-6-offerings

  # With GitHub PR — fetches PR body via GitHub MCP
  python scripts/test_jira_agent.py SCRUM-6 feature/SCRUM-6-offerings ^
    --github-pr-url https://github.com/satalkar21/AI_Studio_Main/pull/1

  # Manual PR description override
  python scripts/test_jira_agent.py SCRUM-6 feature/SCRUM-6-offerings ^
    --pr-description "Fix offerings dropdown navigation"
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from _bootstrap import BACKEND_ROOT  # noqa: F401 — adds backend to sys.path

from app.agents.jira_agent import JiraAgent
from app.config import get_settings
from app.logging_config import setup_logging
from app.mcp.github_mcp import GitHubMCPClient
from app.utils.github_fields import extract_pr_description
from app.utils.parsers import extract_github_pr_parts


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Jira agent validation via real MCP.")
    parser.add_argument("issue_key", help="Jira issue key, e.g. SCRUM-6")
    parser.add_argument(
        "expected_release_version",
        help="Release version / branch to match against Jira Fix Version",
    )
    parser.add_argument(
        "--github-pr-url",
        help="GitHub PR URL — fetches PR body via GitHub MCP for description validation",
    )
    parser.add_argument(
        "--pr-description",
        help="Override PR description text (skips GitHub MCP fetch)",
    )
    return parser.parse_args()


async def _fetch_pr_description(github_pr_url: str) -> str | None:
    owner, repo, pull_number = extract_github_pr_parts(github_pr_url)
    async with GitHubMCPClient() as client:
        pr_data = await client.get_pull_request(owner, repo, pull_number)
    return extract_pr_description(pr_data)


async def _resolve_pr_description(args: argparse.Namespace) -> str | None:
    if args.pr_description:
        return args.pr_description.strip() or None
    if args.github_pr_url:
        print(f"Fetching PR description from GitHub MCP: {args.github_pr_url}")
        return await _fetch_pr_description(args.github_pr_url)
    return None


async def _run(args: argparse.Namespace) -> int:
    setup_logging(get_settings().log_level)

    pr_description = await _resolve_pr_description(args)
    if pr_description:
        preview = pr_description[:120] + ("..." if len(pr_description) > 120 else "")
        print(f"Using PR description ({len(pr_description)} chars): {preview!r}\n")
    else:
        print(
            "No PR description provided. Pass --github-pr-url or --pr-description "
            "for semantic description validation.\n"
        )

    agent = JiraAgent()
    result = await agent.validate(
        issue_key=args.issue_key,
        expected_release_version=args.expected_release_version,
        pr_description=pr_description,
    )
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.status.value == "PASS" else 1


def main() -> int:
    args = _parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
