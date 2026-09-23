"""Call Barko for required QA: pass credentials/context, take passed/reasoning."""

from __future__ import annotations

import logging
from typing import Any

from app.config import Settings, get_settings
from app.models.validation import QAChecks, QAValidationResult, ValidationStatus
from app.services.barko_qa_client import (
    BarkoQAClient,
    BarkoQAClientError,
    BarkoQACredentials,
    BarkoQARequest,
    BarkoQAResult,
)
from app.services.qa_pr_test_gate import extract_github_metadata
from app.services.qa_signoff_service import QASignoffService, get_qa_signoff_service

logger = logging.getLogger(__name__)


class BarkoQAAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: BarkoQAClient | None = None,
        signoff_service: QASignoffService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.client = client or BarkoQAClient()
        self.signoff_service = signoff_service or get_qa_signoff_service()

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
        qa_mode: str | None = None,
        github_validation: Any | None = None,
    ) -> QAValidationResult:
        del qa_signoff_attachment, jira_validation
        if not qa_signoff_required or (qa_mode or "").strip().lower() == "not_required":
            result = self.signoff_service.validate_not_required(
                qa_signoff_not_required_reason=qa_signoff_not_required_reason,
            )
            result.metadata.setdefault("qa_workflow", "barko_agent")
            return result

        request = _build_barko_request(
            release_id=release_id,
            environment=environment,
            release_version=release_version,
            jira_issue_key=jira_issue_key,
            pr_title=pr_title,
            github_validation=github_validation,
        )
        logger.info(
            "[BARKO_QA] Invoking client for %s jira=%s github=%s/%s#%s",
            request.release_id,
            request.jira_issue_key or "-",
            request.github_owner or "-",
            request.github_repo or "-",
            request.github_pull_number or "-",
        )
        credentials = BarkoQACredentials(
            jira_email=self.settings.jira_email,
            jira_api_token=self.settings.jira_api_token,
            github_token=self.settings.github_personal_access_token,
        )
        try:
            barko_result = await self.client.run(request, credentials)
        except BarkoQAClientError as exc:
            logger.warning("[BARKO_QA] Client error for %s: %s", release_id, exc)
            return _to_qa_result(
                BarkoQAResult(passed=False, reasoning=str(exc)),
                status=ValidationStatus.ERROR,
            )
        except Exception:
            logger.exception("[BARKO_QA] Unexpected client failure for %s", release_id)
            return _to_qa_result(
                BarkoQAResult(
                    passed=False,
                    reasoning="Barko QA client failed unexpectedly.",
                ),
                status=ValidationStatus.ERROR,
            )
        return _to_qa_result(barko_result)


def _to_qa_result(
    result: BarkoQAResult,
    *,
    status: ValidationStatus | None = None,
) -> QAValidationResult:
    reasoning = (result.reasoning or "").strip()
    if status is None:
        status = ValidationStatus.PASS if result.passed else ValidationStatus.FAIL
    passed = status == ValidationStatus.PASS
    errors: list[str] = [] if passed else [reasoning or "Barko QA reported a failure."]
    return QAValidationResult(
        status=status,
        checks=QAChecks(signoff_required=True, signoff_completed=passed),
        errors=errors,
        metadata={
            "qa_workflow": "barko_agent",
            "barko_reasoning": reasoning,
        },
    )


def _build_barko_request(
    *,
    release_id: str,
    environment: str,
    release_version: str,
    jira_issue_key: str | None,
    pr_title: str | None,
    github_validation: Any | None,
) -> BarkoQARequest:
    github_meta = extract_github_metadata(github_validation)
    pull_number = github_meta.get("pull_number")
    try:
        pull_number_int = int(pull_number) if pull_number is not None else None
    except (TypeError, ValueError):
        pull_number_int = None
    title = pr_title or github_meta.get("pr_title")
    sha = github_meta.get("head_sha")
    return BarkoQARequest(
        release_id=release_id,
        environment=environment,
        release_version=release_version,
        jira_issue_key=jira_issue_key,
        github_pr_url=github_meta.get("github_pr_url")
        or github_meta.get("html_url")
        or github_meta.get("pr_url"),
        github_owner=github_meta.get("owner") or github_meta.get("github_owner"),
        github_repo=github_meta.get("repo") or github_meta.get("github_repo"),
        github_pull_number=pull_number_int,
        github_head_sha=str(sha) if sha else None,
        pr_title=str(title).strip() if title else None,
    )
