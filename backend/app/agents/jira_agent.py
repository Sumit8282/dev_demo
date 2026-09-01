"""Jira Release Validation Agent — LLM JIRA–PR alignment + Jira MCP."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_structured_agent
from app.agents.tools.mcp_tools import build_jira_mcp_tools, _with_jira_client
from app.config import Settings, get_settings
from app.mcp.jira_mcp import JiraMCPClient
from app.models.jira_llm_validation import JiraLLMValidationOutput, JiraRequirementMatrixRow
from app.models.validation import JiraChecks, JiraValidationResult, ValidationStatus
from app.prompts import format_prompt, load_prompt
from app.utils.jira_fields import (
    extract_acceptance_criteria,
    extract_fix_versions,
    extract_issue_description,
    format_jira_ticket_snapshot,
    extract_issue_status,
    issue_exists,
    is_jira_ticket_not_found_message,
    resolve_jira_ticket_not_found_message,
)

logger = logging.getLogger(__name__)

_RELEASE_AUTOMATION_COMMENT_MARKERS = (
    "Release Validation Failed",
    "Release workflow has been HALTED",
    "L3 approval will not be triggered",
    "Failed Checks:",
    "Posting validation failure comment",
)


class JiraTicketNotFoundError(Exception):
    def __init__(self, issue_key: str) -> None:
        self.issue_key = issue_key
        super().__init__(resolve_jira_ticket_not_found_message(issue_key))


class JiraAgent:
    def __init__(
        self,
        jira_client: JiraMCPClient | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._jira_client = jira_client

    async def validate(
        self,
        *,
        issue_key: str,
        expected_release_version: str,
        pr_description: str | None = None,
        pr_title: str | None = None,
        pr_comments: list[dict[str, Any]] | None = None,
        code_change_summary: str | None = None,
    ) -> JiraValidationResult:
        logger.info("[JIRA_AGENT] Starting LLM validation for %s", issue_key)

        if not self.settings.llm_enabled:
            return self._error_result(
                "LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL."
            )

        agent = self.build_langchain_agent()
        if agent is None:
            return self._error_result("Failed to initialize Jira LLM agent.")

        try:
            jira_ticket_snapshot, parsed_acs = await self._prefetch_jira_ticket_context(issue_key)
        except JiraTicketNotFoundError as exc:
            return self._ticket_not_found_result(exc.issue_key)

        filtered_comments = _filter_release_automation_pr_comments(pr_comments)
        user_message = format_prompt(
            "jira_agent_user",
            issue_key=issue_key,
            expected_release_version=expected_release_version,
            allowed_statuses=", ".join(self.settings.allowed_jira_statuses),
            jira_ticket_snapshot=jira_ticket_snapshot,
            pr_title=(pr_title or "").strip() or "(not provided)",
            pr_description=(pr_description or "").strip() or "(not provided)",
            pr_comments=_format_pr_comments(filtered_comments),
            code_change_summary=(code_change_summary or "").strip() or "(not provided)",
        )
        llm_result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=JiraLLMValidationOutput,
        )
        if llm_result is None:
            return self._error_result("Jira LLM agent did not return a structured validation result.")

        llm_result = _apply_authoritative_ac_constraints(llm_result, parsed_acs)
        result = _to_jira_validation_result(
            llm_result,
            issue_key=issue_key,
            fallback_pr_description=pr_description,
            acceptance_criteria=parsed_acs,
        )
        logger.info("[JIRA_AGENT] LLM validation result: %s", result.status.value)
        _log_jira_validation_matrix(result)
        return result

    def get_mcp_tools(self) -> list:
        """Return LangChain tools backed by the real Jira Rovo MCP client."""
        return build_jira_mcp_tools(self._jira_client)

    def build_langchain_agent(self, llm: BaseChatModel | None = None):
        """Build a LangChain agent with Jira MCP tools."""
        return create_langchain_agent(
            settings=self.settings,
            tools=self.get_mcp_tools(),
            system_prompt=load_prompt("jira_agent_system"),
            name="jira_agent",
            response_format=JiraLLMValidationOutput,
            llm=llm,
        )

    @staticmethod
    def _error_result(message: str) -> JiraValidationResult:
        return JiraValidationResult(
            status=ValidationStatus.ERROR,
            checks=JiraChecks(),
            errors=[message],
        )

    @staticmethod
    def _ticket_not_found_result(issue_key: str) -> JiraValidationResult:
        message = resolve_jira_ticket_not_found_message(issue_key)
        return JiraValidationResult(
            status=ValidationStatus.FAIL,
            checks=JiraChecks(ticket_exists=False),
            errors=[message],
            metadata={"issue_key": issue_key},
        )

    async def _prefetch_jira_ticket_context(
        self,
        issue_key: str,
    ) -> tuple[str, list[str]]:
        """Fetch Jira issue up front so the LLM validates only ticket ACs."""

        async def _fetch(client: JiraMCPClient) -> tuple[str, list[str]]:
            issue = await client.get_issue(issue_key)
            if not issue_exists(issue):
                raise JiraTicketNotFoundError(issue_key)
            description = extract_issue_description(issue) or ""
            parsed_acs = extract_acceptance_criteria(description)
            snapshot = format_jira_ticket_snapshot(
                issue_key=issue_key,
                description=description,
                acceptance_criteria=parsed_acs,
                status=extract_issue_status(issue),
                fix_versions=extract_fix_versions(issue),
            )
            logger.info(
                "[JIRA_AGENT] Prefetched %s — %d acceptance criteria on ticket",
                issue_key,
                len(parsed_acs),
            )
            return snapshot, parsed_acs

        try:
            return await _with_jira_client(self._jira_client, _fetch)
        except Exception as exc:
            logger.warning("[JIRA_AGENT] Unable to prefetch Jira ticket %s: %s", issue_key, exc)
            return (
                "(Jira ticket could not be pre-fetched — use MCP get_jira_issue; "
                "evaluate only acceptance criteria present on the ticket.)",
                [],
            )


def _filter_release_automation_pr_comments(
    comments: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    """Drop prior Release Automation failure comments that reinforce old AC failures."""
    if not comments:
        return comments

    filtered: list[dict[str, Any]] = []
    for item in comments:
        if not isinstance(item, dict):
            continue
        body = str(item.get("body") or item.get("text") or "")
        if any(marker in body for marker in _RELEASE_AUTOMATION_COMMENT_MARKERS):
            continue
        filtered.append(item)
    return filtered


def _ac_number(requirement_id: str) -> int | None:
    normalized = str(requirement_id or "").strip().upper()
    if not normalized.startswith("AC-"):
        return None
    suffix = normalized.split("-", 1)[1]
    if not suffix.isdigit():
        return None
    return int(suffix)


def _apply_authoritative_ac_constraints(
    llm_result: JiraLLMValidationOutput,
    parsed_acs: list[str],
) -> JiraLLMValidationOutput:
    """Strip invented REQ/extra AC rows and recompute alignment from ticket ACs only."""
    max_ac = len(parsed_acs)
    filtered_matrix: list[JiraRequirementMatrixRow] = []

    for row in llm_result.validation_matrix:
        requirement_id = str(row.requirement_id or "").strip().upper()
        if requirement_id.startswith("REQ-"):
            continue
        ac_number = _ac_number(requirement_id)
        if ac_number is None:
            continue
        if max_ac and ac_number > max_ac:
            continue
        filtered_matrix.append(row)

    llm_result.validation_matrix = filtered_matrix

    release_gates_ok = (
        llm_result.checks.ticket_exists
        and llm_result.checks.status_valid
        and llm_result.checks.fix_version_match
    )
    if not release_gates_ok:
        return llm_result

    blocking_rows = [
        row
        for row in filtered_matrix
        if str(row.status or "").strip().lower() != "fully addressed"
    ]
    llm_result.checks.description_match = not blocking_rows
    if blocking_rows:
        if llm_result.status != ValidationStatus.FAIL:
            llm_result.status = ValidationStatus.FAIL
        blocking_ids = ", ".join(row.requirement_id for row in blocking_rows[:5])
        llm_result.errors = [
            error
            for error in llm_result.errors
            if not _error_references_removed_ac(error, max_ac)
        ]
        if not any("not fully addressed" in error.lower() for error in llm_result.errors):
            llm_result.errors.append(
                f"One or more JIRA acceptance criteria are not fully addressed: {blocking_ids}."
            )
    else:
        llm_result.status = ValidationStatus.PASS
        llm_result.checks.description_match = True
        llm_result.errors = [
            error
            for error in llm_result.errors
            if not _error_references_removed_ac(error, max_ac)
            and "screenshot" not in error.lower()
            and "cross-browser" not in error.lower()
        ]

    return llm_result


def _error_references_removed_ac(error: str, max_ac: int) -> bool:
    if max_ac <= 0:
        return False
    normalized = error.upper()
    for ac_number in range(max_ac + 1, max_ac + 8):
        token = f"AC-{ac_number:02d}"
        if token in normalized or f"AC-{ac_number}" in normalized:
            return True
    return False


def _normalize_matrix_cell(value: Any, *, max_len: int = 48) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= max_len:
        return text
    return f"{text[: max_len - 3]}..."


def _log_jira_validation_matrix(result: JiraValidationResult) -> None:
    """Log the JIRA–PR validation matrix as a readable table in terminal output."""
    matrix = (result.metadata or {}).get("validation_matrix") or []
    if not matrix:
        logger.info("[JIRA_AGENT] JIRA–PR validation matrix: (no rows returned)")
        return

    col_ac = 10
    col_jira = 52
    col_pr = 52
    col_status = 20
    separator = (
        f"{'-' * col_ac}-+-{'-' * col_jira}-+-{'-' * col_pr}-+-{'-' * col_status}"
    )
    header = (
        f"{'AC':<{col_ac}} | "
        f"{'JIRA requirement':<{col_jira}} | "
        f"{'PR evidence':<{col_pr}} | "
        f"{'Status':<{col_status}}"
    )

    logger.info("[JIRA_AGENT] JIRA–PR validation matrix:")
    logger.info("[JIRA_AGENT] %s", header)
    logger.info("[JIRA_AGENT] %s", separator)
    for row in matrix:
        if not isinstance(row, dict):
            continue
        logger.info(
            "[JIRA_AGENT] %s | %s | %s | %s",
            _normalize_matrix_cell(row.get("requirement_id"), max_len=col_ac).ljust(col_ac),
            _normalize_matrix_cell(row.get("jira_requirement"), max_len=col_jira).ljust(col_jira),
            _normalize_matrix_cell(row.get("pr_evidence"), max_len=col_pr).ljust(col_pr),
            _normalize_matrix_cell(row.get("status"), max_len=col_status).ljust(col_status),
        )
        remarks = str(row.get("remarks") or "").strip()
        if remarks:
            logger.info(
                "[JIRA_AGENT] %s remarks: %s",
                _normalize_matrix_cell(row.get("requirement_id"), max_len=col_ac),
                remarks,
            )

    relationship = (result.metadata or {}).get("jira_pr_relationship")
    if relationship:
        logger.info("[JIRA_AGENT] JIRA–PR relationship: %s", relationship)
    if result.errors:
        logger.info("[JIRA_AGENT] Validation errors: %s", "; ".join(result.errors))


def _format_pr_comments(comments: list[dict[str, Any]] | None) -> str:
    if not comments:
        return "(none provided)"
    lines: list[str] = []
    for item in comments:
        if not isinstance(item, dict):
            lines.append(f"- {item}")
            continue
        author = item.get("author") or item.get("user") or "unknown"
        body = item.get("body") or item.get("text") or ""
        lines.append(f"- {author}: {body}")
    return "\n".join(lines) if lines else "(none provided)"


def _to_jira_validation_result(
    llm_result: JiraLLMValidationOutput,
    *,
    issue_key: str,
    fallback_pr_description: str | None,
    acceptance_criteria: list[str] | None = None,
) -> JiraValidationResult:
    parsed_acs = [item.strip() for item in (acceptance_criteria or []) if item and item.strip()]
    metadata: dict[str, Any] = {
        "issue_key": issue_key,
        "validation_summary": llm_result.validation_summary,
        "jira_pr_relationship": llm_result.jira_pr_relationship,
        "validation_matrix": [row.model_dump() for row in llm_result.validation_matrix],
        "jira_description": llm_result.jira_description,
        "github_pr_description": llm_result.github_pr_description or (fallback_pr_description or ""),
        "jira_comments": llm_result.jira_comments,
        "acceptance_criteria": parsed_acs,
    }

    errors = list(llm_result.errors)
    if not llm_result.checks.ticket_exists:
        errors = [resolve_jira_ticket_not_found_message(issue_key, errors)]
        if llm_result.status != ValidationStatus.FAIL:
            llm_result.status = ValidationStatus.FAIL
    elif llm_result.status == ValidationStatus.FAIL and not errors:
        errors = ["JIRA–PR validation failed."]

    return JiraValidationResult(
        status=llm_result.status,
        checks=llm_result.checks,
        errors=errors,
        metadata=metadata,
    )


def format_github_code_change_summary(metadata: dict[str, Any] | None) -> str:
    if not metadata:
        return "(not provided)"

    files_changed = metadata.get("files_changed_count", 0)
    lines_added = metadata.get("lines_added", 0)
    lines_deleted = metadata.get("lines_deleted", 0)
    changed_files = metadata.get("changed_files") or []
    changed_file_names = metadata.get("changed_file_names") or []

    lines = [
        f"Files changed: {files_changed}",
        f"Lines added: {lines_added}",
        f"Lines deleted: {lines_deleted}",
    ]

    if changed_files:
        lines.append("Changed files:")
        for entry in changed_files[:30]:
            if not isinstance(entry, dict):
                continue
            lines.append(
                f"- {entry.get('filename', 'unknown')} "
                f"({entry.get('status', 'modified')}): "
                f"+{entry.get('additions', 0)} / -{entry.get('deletions', 0)}"
            )
    elif changed_file_names:
        lines.append("Changed file names:")
        for name in changed_file_names[:30]:
            lines.append(f"- {name}")

    return "\n".join(lines)


def extract_github_metadata(github_validation: Any | None) -> dict[str, Any]:
    if github_validation is None:
        return {}
    if hasattr(github_validation, "metadata"):
        metadata = github_validation.metadata or {}
    elif isinstance(github_validation, dict):
        metadata = github_validation.get("metadata") or {}
    else:
        metadata = {}
    return metadata if isinstance(metadata, dict) else {}
