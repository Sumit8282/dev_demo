"""Log GitHub PR change stats for a pull request (testing helper)."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.orchestrator import Orchestrator
from app.mcp.github_mcp import GitHubMCPClient
from app.utils.github_fields import extract_source_branch
from app.utils.parsers import extract_github_pr_parts


async def main(pr_url: str) -> None:
    owner, repo, pull_number = extract_github_pr_parts(pr_url)

    release_branch = "feature/test"
    async with GitHubMCPClient() as client:
        pr_data = await client.get_pull_request(owner, repo, pull_number)
        release_branch = extract_source_branch(pr_data) or release_branch

    state = {
        "release_id": "REL-TEST-PR-STATS",
        "release_branch": release_branch,
        "release_version": "test",
        "github_pr_url": pr_url,
        "github_owner": owner,
        "github_repo": repo,
        "github_pr_number": pull_number,
        "jira_url": "https://example.atlassian.net/browse/TEST-1",
        "jira_issue_key": "TEST-1",
        "qa_signoff_required": False,
        "environment": "UAT",
    }

    result = await Orchestrator().run_github_validation(state)
    print("Release branch used:", release_branch)
    print("Validation status:", result.status.value)
    if result.errors:
        print("Validation errors:")
        for error in result.errors:
            print(f"  - {error}")
    print("Files changed:", result.metadata.get("files_changed_count"))
    print("Lines added:", result.metadata.get("lines_added"))
    print("Lines deleted:", result.metadata.get("lines_deleted"))
    print("Changed files:", result.metadata.get("changed_file_names"))


if __name__ == "__main__":
    url = (
        sys.argv[1]
        if len(sys.argv) > 1
        else "https://github.com/satalkar21/AI_Studio_Main/pull/11"
    )
    asyncio.run(main(url))
