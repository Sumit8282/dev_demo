"""QA Validation Agent — LLM acceptance-criteria coverage vs QA test document."""

from __future__ import annotations

import logging
from typing import Any

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_structured_agent
from app.agents.tools.mcp_tools import build_jira_mcp_tools
from app.config import Settings, get_settings
from app.mcp.jira_mcp import JiraMCPClient
from app.models.qa_llm_validation import QALLMValidationOutput
from app.models.validation import QAChecks, QAValidationResult, ValidationStatus
from app.prompts import format_prompt, load_prompt
from app.services.qa_signoff_service import QASignoffService, get_qa_signoff_service

logger = logging.getLogger(__name__)


class QAAgent:
    def __init__(
        self,
        signoff_service: QASignoffService | None = None,
        settings: Settings | None = None,
        jira_client: JiraMCPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.signoff_service = signoff_service or get_qa_signoff_service()
        self._jira_client = jira_client

    async def validate_async(
        self,
        *,
        release_id: str,
        qa_signoff_required: bool,
        environment: str,
        release_version: str,
        qa_signoff_not_required_reason: str | None = None,
        pr_title: str | None = None,
        qa_signoff_attachment: dict | None = None,
        jira_issue_key: str | None = None,
        jira_validation: Any | None = None,
    ) -> QAValidationResult:
        logger.info(
            "[QA_AGENT] Starting sign-off validation for release %s (required=%s)",
            release_id,
            qa_signoff_required,
        )

        if not qa_signoff_required:
            result = self.signoff_service.validate_not_required(
                qa_signoff_not_required_reason=qa_signoff_not_required_reason,
            )
            result.metadata.setdefault("environment", environment)
            result.metadata.setdefault("release_version", release_version)
            logger.info("[QA_AGENT] Sign-off validation result: %s", result.status.value)
            return result

        checks = QAChecks(signoff_required=True, signoff_completed=False)
        metadata: dict[str, Any] = {
            "environment": environment,
            "release_version": release_version,
            "expected_pr_title": pr_title or "",
            "jira_issue_key": jira_issue_key or "",
        }

        if not qa_signoff_attachment or not qa_signoff_attachment.get("filename"):
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=checks,
                errors=["QA sign-off attachment is required but was not provided."],
                metadata=metadata,
            )

        try:
            filename, qa_document_text = self.signoff_service.load_qa_document_text(
                release_id=release_id,
                attachment=qa_signoff_attachment,
            )
            metadata["attachment_filename"] = filename
            metadata["qa_document_text_length"] = len(qa_document_text)
        except ValueError as exc:
            return QAValidationResult(
                status=ValidationStatus.FAIL,
                checks=checks,
                errors=[str(exc)],
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("[QA_AGENT] Failed to read attachment for %s", release_id)
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[f"Failed to process QA sign-off attachment: {exc}"],
                metadata=metadata,
            )

        if not self.settings.llm_enabled:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[
                    "LLM is not configured. Set LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, and LLM_BASE_URL."
                ],
                metadata=metadata,
            )

        agent = self.build_langchain_agent()
        if agent is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["Failed to initialize QA LLM agent."],
                metadata=metadata,
            )

        jira_description, jira_comments, acceptance_criteria = _extract_jira_context(
            jira_validation
        )
        if not acceptance_criteria and jira_issue_key:
            fetched_description, fetched_comments, fetched_acs = (
                await self._prefetch_jira_acceptance_criteria(jira_issue_key)
            )
            acceptance_criteria = fetched_acs
            jira_description = jira_description or fetched_description
            jira_comments = jira_comments or fetched_comments

        logger.info(
            "[QA_AGENT] Using %d acceptance criteria from Jira %s",
            len(acceptance_criteria),
            jira_issue_key or "(none)",
        )
        user_message = format_prompt(
            "qa_agent_user",
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            qa_signoff_required=qa_signoff_required,
            pr_title=(pr_title or "").strip() or "(not provided)",
            jira_issue_key=(jira_issue_key or "").strip() or "(not provided)",
            jira_description=jira_description or "(not provided)",
            jira_comments=jira_comments or "(none provided)",
            acceptance_criteria=_format_acceptance_criteria(acceptance_criteria),
            attachment_filename=filename,
            qa_document_text=qa_document_text,
        )

        llm_result = await invoke_structured_agent(
            agent,
            user_message=user_message,
            response_model=QALLMValidationOutput,
        )
        if llm_result is None:
            return QAValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=["QA LLM agent did not return a structured validation result."],
                metadata=metadata,
            )

        return _to_qa_validation_result(
            llm_result,
            checks=checks,
            metadata=metadata,
            provided_acceptance_criteria=acceptance_criteria,
        )

    async def _prefetch_jira_acceptance_criteria(
        self,
        issue_key: str,
    ) -> tuple[str, str, list[str]]:
        """Fetch Jira ACs when the Jira agent did not pass them through."""
        from app.agents.tools.mcp_tools import _with_jira_client
        from app.utils.jira_fields import (
            extract_acceptance_criteria,
            extract_issue_comments,
            extract_issue_description,
        )

        async def _fetch(client: JiraMCPClient) -> tuple[str, str, list[str]]:
            issue = await client.get_issue(issue_key)
            description = extract_issue_description(issue) or ""
            comments = extract_issue_comments(issue)
            comment_lines = [
                f"- {item.get('author', 'unknown')}: {item.get('body', '')}"
                for item in comments
                if isinstance(item, dict)
            ]
            return description, "\n".join(comment_lines), extract_acceptance_criteria(description)

        try:
            return await _with_jira_client(self._jira_client, _fetch)
        except Exception as exc:
            logger.warning("[QA_AGENT] Unable to prefetch Jira ACs for %s: %s", issue_key, exc)
            return "", "", []

    def get_mcp_tools(self) -> list:
        return build_jira_mcp_tools(self._jira_client)

    def build_langchain_agent(self, llm: BaseChatModel | None = None):
        return create_langchain_agent(
            settings=self.settings,
            tools=self.get_mcp_tools(),
            system_prompt=load_prompt("qa_agent_system"),
            name="qa_agent",
            response_format=QALLMValidationOutput,
            llm=llm,
        )


def _extract_jira_context(jira_validation: Any | None) -> tuple[str, str, list[str]]:
    if jira_validation is None:
        return "", "", []

    if hasattr(jira_validation, "metadata"):
        metadata = jira_validation.metadata or {}
    elif isinstance(jira_validation, dict):
        metadata = jira_validation.get("metadata") or {}
    else:
        metadata = {}

    description = metadata.get("jira_description")
    if not isinstance(description, str):
        description = metadata.get("description") or ""

    comments = metadata.get("jira_comments") or metadata.get("comments") or []
    if isinstance(comments, list):
        comment_lines = []
        for item in comments:
            if isinstance(item, dict):
                author = item.get("author") or item.get("displayName") or "unknown"
                body = item.get("body") or item.get("text") or ""
                comment_lines.append(f"- {author}: {body}")
            else:
                comment_lines.append(f"- {item}")
        comments_text = "\n".join(comment_lines)
    elif isinstance(comments, str):
        comments_text = comments
    else:
        comments_text = ""

    return (
        str(description).strip(),
        comments_text.strip(),
        _acceptance_criteria_from_jira_metadata(metadata, str(description)),
    )


def _acceptance_criteria_from_jira_metadata(
    metadata: dict[str, Any],
    description: str = "",
) -> list[str]:
    raw = metadata.get("acceptance_criteria")
    if isinstance(raw, list):
        parsed = [str(item).strip() for item in raw if str(item).strip()]
        if parsed:
            return parsed

    matrix = metadata.get("validation_matrix") or []
    criteria: list[str] = []
    seen: set[str] = set()
    for row in matrix:
        if not isinstance(row, dict):
            continue
        text = str(row.get("jira_requirement") or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        criteria.append(text)
    if criteria:
        return criteria

    from app.utils.jira_fields import extract_acceptance_criteria

    return extract_acceptance_criteria(description)


def _format_acceptance_criteria(criteria: list[str]) -> str:
    if not criteria:
        return (
            "None extracted from the Jira ticket yet. Fetch issue details with Jira MCP "
            "if needed. Only then may you set no_acceptance_criteria_found."
        )
    lines = [
        "These criteria were already extracted from the JIRA ticket. They exist. "
        "Use this list. Do not report them as missing. Do not invent extra ACs."
    ]
    for index, criterion in enumerate(criteria, start=1):
        lines.append(f"- AC-{index:02d}: {criterion}")
    return "\n".join(lines)


_MISSING_AC_MARKERS = (
    "no explicit acceptance criteria",
    "missing explicit acceptance criteria",
    "no acceptance criteria found",
)


def _is_missing_ac_error(error: str) -> bool:
    lowered = error.lower()
    return any(marker in lowered for marker in _MISSING_AC_MARKERS)


def _to_qa_validation_result(
    llm_result: QALLMValidationOutput,
    *,
    checks: QAChecks,
    metadata: dict[str, Any],
    provided_acceptance_criteria: list[str] | None = None,
) -> QAValidationResult:
    provided = [item for item in (provided_acceptance_criteria or []) if item]
    no_ac_found = llm_result.no_acceptance_criteria_found
    errors = list(llm_result.errors)
    status = llm_result.status

    if provided:
        no_ac_found = False
        errors = [error for error in errors if not _is_missing_ac_error(error)]
        if status == ValidationStatus.FAIL and not llm_result.coverage_matrix:
            logger.warning(
                "[QA_AGENT] LLM reported missing ACs despite %d provided criteria",
                len(provided),
            )
            if not errors:
                errors = [
                    "QA agent did not map the acceptance criteria already found on the Jira ticket."
                ]

    metadata = {
        **metadata,
        "validation_summary": llm_result.validation_summary,
        "coverage_matrix": [row.model_dump() for row in llm_result.coverage_matrix],
        "acceptance_criteria_coverage_percent": llm_result.acceptance_criteria_coverage_percent,
        "passed_acceptance_criteria_percent": llm_result.passed_acceptance_criteria_percent,
        "no_acceptance_criteria_found": no_ac_found,
        "provided_acceptance_criteria": provided,
    }

    if status == ValidationStatus.PASS:
        return QAValidationResult(
            status=ValidationStatus.PASS,
            checks=QAChecks(
                signoff_required=True,
                signoff_completed=True,
            ),
            metadata=metadata,
        )

    if status == ValidationStatus.FAIL and not errors:
        errors = ["QA acceptance-criteria validation failed."]

    return QAValidationResult(
        status=status,
        checks=checks,
        errors=errors,
        metadata=metadata,
    )
