"""URL and branch parsing utilities."""

import re
from urllib.parse import urlparse

RELEASE_BRANCH_PATTERN = re.compile(r"^release/(?P<version>.+)$", re.IGNORECASE)
JIRA_ISSUE_PATTERN = re.compile(r"/browse/(?P<key>[A-Z][A-Z0-9]+-\d+)", re.IGNORECASE)
GITHUB_PR_PATTERN = re.compile(
    r"github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)/pull/(?P<number>\d+)",
    re.IGNORECASE,
)


def extract_release_version(release_branch: str) -> str:
    """Derive release version from branch name.

    ``release/v2.4.0`` -> ``v2.4.0``; any other non-empty branch name is used as-is.
    """
    branch = release_branch.strip()
    if not branch:
        raise ValueError("Release branch cannot be empty")
    match = RELEASE_BRANCH_PATTERN.match(branch)
    if match:
        return match.group("version")
    return branch


def extract_jira_issue_key(jira_url: str) -> str:
    match = JIRA_ISSUE_PATTERN.search(jira_url)
    if match:
        return match.group("key").upper()
    parsed = urlparse(jira_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    if path_parts:
        candidate = path_parts[-1].upper()
        if re.fullmatch(r"[A-Z][A-Z0-9]+-\d+", candidate):
            return candidate
    raise ValueError(f"Invalid Jira URL: {jira_url!r}. Could not extract issue key.")


def extract_github_pr_parts(github_pr_url: str) -> tuple[str, str, int]:
    match = GITHUB_PR_PATTERN.search(github_pr_url)
    if not match:
        raise ValueError(
            f"Invalid GitHub PR URL: {github_pr_url!r}. "
            "Expected https://github.com/owner/repo/pull/123"
        )
    return match.group("owner"), match.group("repo"), int(match.group("number"))
