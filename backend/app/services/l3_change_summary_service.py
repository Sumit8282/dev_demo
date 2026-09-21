"""LLM-generated release summary for L3 approval mail."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.config import Settings, get_settings
from app.mcp.jira_mcp import JiraMCPClient
from app.prompts import format_prompt, load_prompt
from app.services.llm_service import get_llm
from app.utils.github_fields import extract_pull_request_comments
from app.utils.jira_fields import extract_issue_comments, extract_issue_description

logger = logging.getLogger(__name__)

L3_SUMMARY_JIRA_FIELDS = ["description", "comment"]


class L3ChangeSummaryService:
    """Build a concise L3 mail summary from PR and Jira context via LLM."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    async def generate_summary(
        self,
        *,
        release_id: str,
        jira_issue_key: str,
        github_validation: dict[str, Any] | Any | None = None,
        jira_validation: dict[str, Any] | Any | None = None,
    ) -> str:
        github_metadata = _validation_metadata(github_validation)
        jira_metadata = _validation_metadata(jira_validation)

        pr_title = _metadata_str(github_metadata, "pr_title") or "Not provided"
        pr_description = _metadata_str(github_metadata, "pr_description") or "Not provided"
        pr_comments = _format_comment_lines(
            extract_pull_request_comments(github_metadata.get("comments") or [])
        )

        jira_description = (
            _metadata_str(jira_metadata, "jira_description")
            or _metadata_str(jira_metadata, "issue_description")
            or _metadata_str(jira_metadata, "description")
        )
        jira_comments = _format_jira_comment_lines(jira_metadata.get("jira_comments"))

        if (jira_issue_key or "").strip() and (not jira_description or not jira_comments):
            fetched_description, fetched_comments = await self._fetch_jira_context(jira_issue_key)
            jira_description = jira_description or fetched_description or "Not provided"
            if not jira_comments:
                jira_comments = _format_jira_comment_lines(fetched_comments)
        else:
            jira_description = jira_description or "Not provided"

        if not jira_comments:
            jira_comments = "None"

        summary = await self._generate_with_llm(
            release_id=release_id,
            pr_title=pr_title,
            pr_description=pr_description,
            pr_comments=pr_comments,
            jira_description=jira_description,
            jira_comments=jira_comments,
        )
        if summary:
            logger.info(
                "[L3_SUMMARY] Generated LLM release summary for %s (%d chars)",
                release_id,
                len(summary),
            )
            return summary

        logger.warning("[L3_SUMMARY] LLM summary unavailable for %s — using fallback", release_id)
        return self._fallback_summary(
            pr_title=pr_title,
            pr_description=pr_description,
            jira_description=jira_description,
        )

    async def _fetch_jira_context(self, issue_key: str) -> tuple[str | None, list[dict[str, str]]]:
        try:
            async with JiraMCPClient(self.settings) as client:
                issue = await client.get_issue(issue_key, fields=L3_SUMMARY_JIRA_FIELDS)
            return extract_issue_description(issue), extract_issue_comments(issue)
        except Exception:
            logger.exception("[L3_SUMMARY] Failed to fetch Jira context for %s", issue_key)
            return None, []

    async def _generate_with_llm(
        self,
        *,
        release_id: str,
        pr_title: str,
        pr_description: str,
        pr_comments: str,
        jira_description: str,
        jira_comments: str,
    ) -> str | None:
        if not self.settings.llm_enabled:
            return None

        llm = get_llm(self.settings)
        if llm is None:
            return None

        user_message = format_prompt(
            "l3_change_summary_user",
            release_id=release_id,
            pr_title=pr_title,
            pr_description=pr_description,
            pr_comments=pr_comments,
            jira_description=jira_description,
            jira_comments=jira_comments,
        )
        try:
            response = await llm.ainvoke(
                [
                    SystemMessage(content=load_prompt("l3_change_summary_system")),
                    HumanMessage(content=user_message),
                ]
            )
        except Exception:
            logger.exception("[L3_SUMMARY] LLM invocation failed for %s", release_id)
            return None

        content = response.content
        if isinstance(content, str) and content.strip():
            return content.strip()
        if isinstance(content, list):
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("text")
            ]
            text = "\n".join(part.strip() for part in parts if part.strip()).strip()
            if text:
                return text
        return None

    @staticmethod
    def _fallback_summary(
        *,
        pr_title: str,
        pr_description: str,
        jira_description: str,
    ) -> str:
        lines = [f"- Release covers: {pr_title}"]
        if pr_description and pr_description != "Not provided":
            preview = pr_description.strip().splitlines()[0][:160]
            lines.append(f"- PR scope: {preview}")
        if jira_description and jira_description != "Not provided":
            preview = jira_description.strip().splitlines()[0][:160]
            lines.append(f"- Jira scope: {preview}")
        lines.append("- See linked GitHub PR and Jira ticket for full details.")
        return "\n".join(lines)


def _validation_metadata(validation: dict[str, Any] | Any | None) -> dict[str, Any]:
    if validation is None:
        return {}
    if hasattr(validation, "metadata"):
        raw = validation.metadata
        return raw if isinstance(raw, dict) else {}
    if isinstance(validation, dict):
        raw = validation.get("metadata")
        return raw if isinstance(raw, dict) else {}
    return {}


def _metadata_str(metadata: dict[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _format_comment_lines(comments: list[dict[str, str]]) -> str:
    if not comments:
        return "None"
    lines: list[str] = []
    for comment in comments[:10]:
        author = comment.get("author") or "unknown"
        body = (comment.get("body") or "").strip()
        if body:
            lines.append(f"- {author}: {body}")
    return "\n".join(lines) if lines else "None"


def _format_jira_comment_lines(comments: Any) -> str:
    if not comments:
        return "None"
    if isinstance(comments, list):
        normalized = [
            item
            for item in comments
            if isinstance(item, dict) and isinstance(item.get("body"), str) and item["body"].strip()
        ]
        return _format_comment_lines(normalized)
    if isinstance(comments, str) and comments.strip():
        return comments.strip()
    return "None"
