"""RM Approval Agent — LangChain agent for RM approval queue entries and notifications."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_langchain_agent
from app.config import Settings, get_settings
from app.models.build_result import BuildResult
from app.models.l3_approval import L3ApprovalRequest, L3ApprovalStatus
from app.models.rm_approval import (
    ApprovalStatusSummary,
    RMApprovalNotificationDraft,
    RMApprovalRequest,
    RMApprovalStatus,
)
from app.models.validation import GitHubValidationResult, MergeResult, MergeResultStatus
from app.prompts import format_prompt, load_prompt
from app.services.rm_mail_service import build_rm_approval_notification_draft, format_deployment_window
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)


@dataclass
class _RMAgentRun:
    state: ReleaseState
    build_result: BuildResult
    github_validation: GitHubValidationResult | dict | None = None
    result: tuple[RMApprovalRequest, RMApprovalNotificationDraft] | None = None


class RMAgent:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def build_langchain_agent(self, run: _RMAgentRun | None = None, llm: BaseChatModel | None = None):
        """Build the RM LangChain agent with an approval-request tool."""
        if run is None:
            return create_langchain_agent(
                settings=self.settings,
                tools=[],
                system_prompt=load_prompt("rm_agent_system"),
                name="rm_agent",
                llm=llm,
            )

        @tool
        async def create_rm_approval_request() -> dict:
            """Create an RM approval queue entry and notification draft after build completes."""
            approval_request, notification_draft = self._create_approval_request_impl(
                run.state,
                build_result=run.build_result,
                github_validation=run.github_validation,
            )
            run.result = (approval_request, notification_draft)
            return {
                "status": approval_request.status.value,
                "approval_url": approval_request.approval_url,
                "build_id": approval_request.build_id,
            }

        return create_langchain_agent(
            settings=self.settings,
            tools=[create_rm_approval_request],
            system_prompt=load_prompt("rm_agent_system"),
            name="rm_agent",
            llm=llm,
        )

    async def create_approval_request(
        self,
        state: ReleaseState,
        *,
        build_result: BuildResult,
        github_validation: GitHubValidationResult | dict | None = None,
    ) -> tuple[RMApprovalRequest, RMApprovalNotificationDraft]:
        run = _RMAgentRun(
            state=state,
            build_result=build_result,
            github_validation=github_validation,
        )
        agent = self.build_langchain_agent(run)
        if agent is not None:
            await invoke_langchain_agent(
                agent,
                user_message=format_prompt(
                    "rm_agent_user",
                    release_id=state["release_id"],
                    build_id=build_result.build_id,
                    environment=state["environment"],
                    jira_issue_key=state["jira_issue_key"],
                ),
            )
            if run.result is not None:
                return run.result
        return self._create_approval_request_impl(
            state,
            build_result=build_result,
            github_validation=github_validation,
        )

    def _create_approval_request_impl(
        self,
        state: ReleaseState,
        *,
        build_result: BuildResult,
        github_validation: GitHubValidationResult | dict | None = None,
    ) -> tuple[RMApprovalRequest, RMApprovalNotificationDraft]:
        logger.info("[RM_AGENT] Creating RM approval request for release %s", state["release_id"])

        metadata: dict = {}
        if github_validation is not None:
            if hasattr(github_validation, "metadata"):
                metadata = github_validation.metadata or {}
            elif isinstance(github_validation, dict):
                metadata = github_validation.get("metadata") or {}

        raised_by = state.get("created_by") or _metadata_str(metadata, "raised_by")
        pr_title = _metadata_str(metadata, "pr_title")
        l3_approved_by = _l3_approver_name(state.get("l3_approval_request"))
        approval_url = self._build_approval_url(state["release_id"])
        approval_queue_url = self._build_approval_queue_url()
        deployment_window = format_deployment_window(state["release_date"])
        approval_statuses = self._collect_approval_statuses(state, build_result)

        now = datetime.now(timezone.utc)
        approval_request = RMApprovalRequest(
            release_id=state["release_id"],
            status=RMApprovalStatus.PENDING,
            approval_url=approval_url,
            approval_queue_url=approval_queue_url,
            created_at=now,
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            build_id=build_result.build_id,
            target_environment=state["environment"],
            deployment_window=deployment_window,
            approval_statuses=approval_statuses,
            raised_by=raised_by,
            pr_title=pr_title,
            l3_approved_by=l3_approved_by,
        )

        notification_draft = build_rm_approval_notification_draft(
            release_id=state["release_id"],
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            build_id=build_result.build_id,
            environment=state["environment"],
            release_date=state["release_date"],
            raised_by=raised_by,
            pr_title=pr_title,
            l3_approved_by=l3_approved_by,
            approval_url=approval_url,
            approval_queue_url=approval_queue_url,
            recipient_emails=self.settings.rm_manager_emails,
        )

        logger.info(
            "[RM_AGENT] RM approval request created for %s (notification to %s)",
            state["release_id"],
            ", ".join(notification_draft.to) or "(no recipients configured)",
        )
        return approval_request, notification_draft

    def _collect_approval_statuses(
        self,
        state: ReleaseState,
        build_result: BuildResult,
    ) -> ApprovalStatusSummary:
        github_status = _validation_status(state.get("github_validation"))
        jira_status = _validation_status(state.get("jira_validation"))
        qa_status = _validation_status(state.get("qa_validation"))
        l3_status = _l3_approval_status(state.get("l3_approval_request"))
        merge_status = _merge_status(state.get("merge_result"))
        build_status = build_result.status.value

        return ApprovalStatusSummary(
            github_validation=github_status,
            jira_validation=jira_status,
            qa_validation=qa_status,
            l3_approval=l3_status,
            merge=merge_status,
            build=build_status,
        )

    def _build_approval_url(self, release_id: str) -> str:
        base = self.settings.portal_base_url.rstrip("/")
        return f"{base}/approvals/rm/{release_id}"

    def _build_approval_queue_url(self) -> str:
        base = self.settings.portal_base_url.rstrip("/")
        return f"{base}/approvals?tab=rm"


def _metadata_str(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _l3_approver_name(raw: dict | L3ApprovalRequest | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, L3ApprovalRequest):
        return raw.approved_by
    if isinstance(raw, dict):
        approved_by = raw.get("approved_by")
        if isinstance(approved_by, str) and approved_by.strip():
            return approved_by.strip()
    return None


def _validation_status(raw: dict | object | None) -> str | None:
    if raw is None:
        return None
    if hasattr(raw, "status"):
        status = raw.status
        return status.value if hasattr(status, "value") else str(status)
    if isinstance(raw, dict):
        return raw.get("status")
    return None


def _l3_approval_status(raw: dict | L3ApprovalRequest | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, L3ApprovalRequest):
        return raw.status.value
    if isinstance(raw, dict):
        status = raw.get("status")
        if isinstance(status, L3ApprovalStatus):
            return status.value
        return str(status) if status else None
    return None


def _merge_status(raw: dict | MergeResult | None) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, MergeResult):
        return raw.status.value
    if isinstance(raw, dict):
        status = raw.get("status")
        if isinstance(status, MergeResultStatus):
            return status.value
        return str(status) if status else None
    return None
