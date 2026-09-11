"""Collect acceptance criteria from GitHub issues linked on a PR."""

from __future__ import annotations

import logging
from typing import Any, Protocol

from app.models.qa_llm_validation import QAAcceptanceCriterion
from app.services.qa_pr_test_gate import extract_github_metadata
from app.utils.github_fields import GitHubIssueRef, extract_linked_issue_refs
from app.utils.jira_fields import extract_acceptance_criteria

logger = logging.getLogger(__name__)


class GitHubIssueReader(Protocol):
    async def get_issue(self, owner: str, repo: str, issue_number: int) -> dict[str, Any]: ...

    async def get_issue_comments(
        self, owner: str, repo: str, issue_number: int
    ) -> list[Any]: ...


def _coerce_pr_number(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value > 0:
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _link_texts(metadata: dict[str, Any]) -> list[str]:
    texts = [
        str(metadata.get("pr_title") or ""),
        str(metadata.get("pr_description") or ""),
    ]
    comments = metadata.get("comments") or []
    if isinstance(comments, list):
        for item in comments:
            if isinstance(item, dict):
                texts.append(str(item.get("body") or ""))
            elif isinstance(item, str):
                texts.append(item)
    return [text for text in texts if text.strip()]


def _comment_bodies(comments: list[Any]) -> list[str]:
    bodies: list[str] = []
    for item in comments:
        if isinstance(item, dict):
            body = item.get("body") or item.get("text") or ""
            if isinstance(body, str) and body.strip():
                bodies.append(body)
        elif isinstance(item, str) and item.strip():
            bodies.append(item)
    return bodies


def _unique_texts(items: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for item in items:
        text = item.strip()
        key = text.lower()
        if not text or key in seen:
            continue
        seen.add(key)
        unique.append(text)
    return unique


def criteria_from_github_issue(
    *,
    number: int,
    title: str,
    body: str,
    comment_bodies: list[str] | None = None,
) -> list[QAAcceptanceCriterion]:
    texts = extract_acceptance_criteria(body)
    if not texts:
        for comment in comment_bodies or []:
            texts.extend(extract_acceptance_criteria(comment))
        texts = _unique_texts(texts)
    if not texts:
        fallback = (title or "").strip()
        if fallback:
            texts = [fallback]
    return [
        QAAcceptanceCriterion(ac_id=f"GH-{number}-{index:02d}", text=text)
        for index, text in enumerate(texts, start=1)
    ]


def linked_issue_refs_from_github_validation(
    github_validation: Any | None,
) -> list[GitHubIssueRef]:
    metadata = extract_github_metadata(github_validation)
    owner = str(metadata.get("owner") or "").strip()
    repo = str(metadata.get("repo") or "").strip()
    pr_number = _coerce_pr_number(
        metadata.get("pull_number") or metadata.get("pr_number") or metadata.get("number")
    )
    return extract_linked_issue_refs(
        owner=owner,
        repo=repo,
        texts=_link_texts(metadata),
        pr_number=pr_number,
    )


async def collect_github_issue_acceptance_criteria(
    github_validation: Any | None,
    client: GitHubIssueReader,
) -> dict[str, Any]:
    refs = linked_issue_refs_from_github_validation(github_validation)
    fetched: list[dict[str, Any]] = []
    criteria: list[QAAcceptanceCriterion] = []
    for ref in refs:
        try:
            issue = await client.get_issue(ref.owner, ref.repo, ref.number)
        except Exception as exc:
            logger.warning(
                "[GITHUB_ISSUES] Failed to fetch %s/%s#%s: %s",
                ref.owner,
                ref.repo,
                ref.number,
                exc,
            )
            continue
        if not isinstance(issue, dict) or issue.get("error"):
            continue
        if issue.get("pull_request"):
            logger.info(
                "[GITHUB_ISSUES] Skipping %s/%s#%s because it is a pull request",
                ref.owner,
                ref.repo,
                ref.number,
            )
            continue
        try:
            comments = await client.get_issue_comments(ref.owner, ref.repo, ref.number)
        except Exception as exc:
            logger.warning(
                "[GITHUB_ISSUES] Failed to fetch comments for %s/%s#%s: %s",
                ref.owner,
                ref.repo,
                ref.number,
                exc,
            )
            comments = []
        title = str(issue.get("title") or "").strip()
        body = str(issue.get("body") or "")
        issue_criteria = criteria_from_github_issue(
            number=ref.number,
            title=title,
            body=body,
            comment_bodies=_comment_bodies(comments if isinstance(comments, list) else []),
        )
        criteria.extend(issue_criteria)
        fetched.append(
            {
                "owner": ref.owner,
                "repo": ref.repo,
                "number": ref.number,
                "title": title,
                "ac_count": len(issue_criteria),
            }
        )
    return {
        "refs": refs,
        "fetched": fetched,
        "criteria": criteria,
        "github_issue_numbers": [f"{ref.owner}/{ref.repo}#{ref.number}" for ref in refs],
    }
