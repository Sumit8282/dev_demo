"""L3 Approval Agent — LangChain agent for approval queue entries and mail drafts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_langchain_agent
from app.config import Settings, get_settings
from app.models.l3_approval import L3ApprovalMailDraft, L3ApprovalRequest, L3ApprovalStatus
from app.models.risk_score import ReleaseRiskScore
from app.models.validation import GitHubValidationResult, JiraValidationResult
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.prompts import format_prompt, load_prompt
from app.services.jira_workflow_service import JiraWorkflowService
from app.services.l3_change_summary_service import L3ChangeSummaryService
from app.services.l3_mail_service import (
    build_l3_approval_mail_draft,
    build_l3_merged_notification_mail_draft,
)
from app.services.workflow_events import emit_workflow_event
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)


@dataclass
class _L3AgentRun:
    state: ReleaseState | None = None
    github_validation: GitHubValidationResult | dict | None = None
    jira_validation: JiraValidationResult | dict | None = None
    risk_score: ReleaseRiskScore | None = None
    issue_key: str | None = None
    release_id: str | None = None
    low_risk: bool = False
    result: Any = None


class L3Agent:
    def __init__(
        self,
        settings: Settings | None = None,
        summary_service: L3ChangeSummaryService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._summary_service = summary_service or L3ChangeSummaryService(self.settings)

    def build_langchain_agent(self, run: _L3AgentRun | None = None, llm: BaseChatModel | None = None):
        """Build the L3 LangChain agent with approval, notification, and Jira tools."""
        run = run or _L3AgentRun()

        @tool
        async def create_l3_approval_request() -> dict:
            """Create an L3 approval queue entry and mail draft for MEDIUM/HIGH risk releases."""
            if run.state is None:
                return {"error": "Release state is missing."}
            approval_request, mail_draft = await self._create_approval_request_impl(
                run.state,
                github_validation=run.github_validation,
                jira_validation=run.jira_validation,
                risk_score=run.risk_score,
            )
            run.result = (approval_request, mail_draft)
            return {
                "status": approval_request.status.value,
                "approval_url": approval_request.approval_url,
            }

        @tool
        async def create_low_risk_merged_notification() -> dict:
            """Create an auto-approved L3 record and merged-notification mail for LOW risk."""
            if run.state is None:
                return {"error": "Release state is missing."}
            approval_request, mail_draft = await self._create_low_risk_merged_notification_impl(
                run.state,
                github_validation=run.github_validation,
                jira_validation=run.jira_validation,
                risk_score=run.risk_score,
            )
            run.result = (approval_request, mail_draft)
            return {
                "status": approval_request.status.value,
                "approved_by": approval_request.approved_by,
            }

        @tool
        async def update_jira_ticket_status() -> dict:
            """Transition the Jira ticket to the L3-approved status via Jira MCP."""
            updated = await self._update_jira_ticket_status_impl(
                issue_key=run.issue_key or "",
                release_id=run.release_id or "",
                low_risk=run.low_risk,
            )
            run.result = updated
            return {"updated": updated}

        return create_langchain_agent(
            settings=self.settings,
            tools=[
                create_l3_approval_request,
                create_low_risk_merged_notification,
                update_jira_ticket_status,
            ],
            system_prompt=load_prompt("l3_agent_system"),
            name="l3_agent",
            llm=llm,
        )

    async def _invoke_or_impl(self, run: _L3AgentRun, *, user_message: str, impl):
        agent = self.build_langchain_agent(run)
        if agent is not None:
            await invoke_langchain_agent(agent, user_message=user_message)
            if run.result is not None:
                return run.result
        return await impl()

    async def create_approval_request(
        self,
        state: ReleaseState,
        *,
        github_validation: GitHubValidationResult | dict | None = None,
        jira_validation: JiraValidationResult | dict | None = None,
        risk_score: ReleaseRiskScore | None = None,
    ) -> tuple[L3ApprovalRequest, L3ApprovalMailDraft]:
        run = _L3AgentRun(
            state=state,
            github_validation=github_validation,
            jira_validation=jira_validation,
            risk_score=risk_score,
        )
        return await self._invoke_or_impl(
            run,
            user_message=format_prompt(
                "l3_agent_user",
                action="create_l3_approval_request",
                release_id=state["release_id"],
                jira_issue_key=state["jira_issue_key"],
                risk_level=(risk_score.level if risk_score else "unknown"),
            ),
            impl=lambda: self._create_approval_request_impl(
                state,
                github_validation=github_validation,
                jira_validation=jira_validation,
                risk_score=risk_score,
            ),
        )

    async def create_low_risk_merged_notification(
        self,
        state: ReleaseState,
        *,
        github_validation: GitHubValidationResult | dict | None = None,
        jira_validation: JiraValidationResult | dict | None = None,
        risk_score: ReleaseRiskScore | None = None,
    ) -> tuple[L3ApprovalRequest, L3ApprovalMailDraft]:
        run = _L3AgentRun(
            state=state,
            github_validation=github_validation,
            jira_validation=jira_validation,
            risk_score=risk_score,
        )
        return await self._invoke_or_impl(
            run,
            user_message=format_prompt(
                "l3_agent_user",
                action="create_low_risk_merged_notification",
                release_id=state["release_id"],
                jira_issue_key=state["jira_issue_key"],
                risk_level=(risk_score.level if risk_score else "LOW"),
            ),
            impl=lambda: self._create_low_risk_merged_notification_impl(
                state,
                github_validation=github_validation,
                jira_validation=jira_validation,
                risk_score=risk_score,
            ),
        )

    async def update_jira_ticket_status(
        self,
        *,
        issue_key: str,
        release_id: str,
        low_risk: bool = False,
    ) -> bool:
        run = _L3AgentRun(issue_key=issue_key, release_id=release_id, low_risk=low_risk)
        return await self._invoke_or_impl(
            run,
            user_message=format_prompt(
                "l3_agent_user",
                action="update_jira_ticket_status",
                release_id=release_id,
                jira_issue_key=issue_key,
                risk_level="LOW" if low_risk else "unknown",
            ),
            impl=lambda: self._update_jira_ticket_status_impl(
                issue_key=issue_key,
                release_id=release_id,
                low_risk=low_risk,
            ),
        )

    async def _create_approval_request_impl(
        self,
        state: ReleaseState,
        *,
        github_validation: GitHubValidationResult | dict | None = None,
        jira_validation: JiraValidationResult | dict | None = None,
        risk_score: ReleaseRiskScore | None = None,
    ) -> tuple[L3ApprovalRequest, L3ApprovalMailDraft]:
        logger.info("[L3_AGENT] Creating L3 approval request for release %s", state["release_id"])

        github_metadata: dict = {}
        if github_validation is not None:
            if hasattr(github_validation, "metadata"):
                github_metadata = github_validation.metadata or {}
            elif isinstance(github_validation, dict):
                github_metadata = github_validation.get("metadata") or {}

        raised_by = state.get("created_by") or _metadata_str(github_metadata, "raised_by")
        pr_title = _metadata_str(github_metadata, "pr_title")
        release_summary = await self._summary_service.generate_summary(
            release_id=state["release_id"],
            jira_issue_key=state["jira_issue_key"],
            github_validation=github_validation,
            jira_validation=jira_validation,
        )
        approval_url = self._build_approval_url(state["release_id"])

        attachment = state.get("qa_signoff_attachment")
        has_qa_attachment = bool(attachment)
        qa_filename = attachment.get("filename") if attachment else None

        now = datetime.now(timezone.utc)
        approval_request = L3ApprovalRequest(
            release_id=state["release_id"],
            status=L3ApprovalStatus.PENDING,
            approval_url=approval_url,
            created_at=now,
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            environment=state["environment"],
            release_date=state["release_date"],
            raised_by=raised_by,
            pr_title=pr_title,
            qa_signoff_required=state["qa_signoff_required"],
            has_qa_attachment=has_qa_attachment,
            qa_signoff_attachment_filename=qa_filename,
            risk_score=risk_score,
        )

        mail_draft = build_l3_approval_mail_draft(
            release_id=state["release_id"],
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            environment=state["environment"],
            release_date=state["release_date"],
            raised_by=raised_by,
            pr_title=pr_title,
            approval_url=approval_url,
            recipient_emails=self.settings.l3_manager_emails,
            change_description=release_summary,
            risk_score=risk_score,
        )

        logger.info(
            "[L3_AGENT] L3 approval request created for %s (mail draft to %s)",
            state["release_id"],
            ", ".join(mail_draft.to) or "(no recipients configured)",
        )
        if len(mail_draft.to) > 1:
            logger.info(
                "[L3_AGENT] L3 approval mail recipients (%d): %s",
                len(mail_draft.to),
                ", ".join(mail_draft.to),
            )
        return approval_request, mail_draft

    async def _create_low_risk_merged_notification_impl(
        self,
        state: ReleaseState,
        *,
        github_validation: GitHubValidationResult | dict | None = None,
        jira_validation: JiraValidationResult | dict | None = None,
        risk_score: ReleaseRiskScore | None = None,
    ) -> tuple[L3ApprovalRequest, L3ApprovalMailDraft]:
        """Create an auto-approved L3 record and merged-notification mail for LOW risk releases."""
        logger.info(
            "[L3_AGENT] Creating low-risk auto-merged L3 notification for release %s",
            state["release_id"],
        )

        github_metadata: dict = {}
        if github_validation is not None:
            if hasattr(github_validation, "metadata"):
                github_metadata = github_validation.metadata or {}
            elif isinstance(github_validation, dict):
                github_metadata = github_validation.get("metadata") or {}

        raised_by = state.get("created_by") or _metadata_str(github_metadata, "raised_by")
        pr_title = _metadata_str(github_metadata, "pr_title")
        release_summary = await self._summary_service.generate_summary(
            release_id=state["release_id"],
            jira_issue_key=state["jira_issue_key"],
            github_validation=github_validation,
            jira_validation=jira_validation,
        )
        approval_url = self._build_approval_url(state["release_id"])

        attachment = state.get("qa_signoff_attachment")
        has_qa_attachment = bool(attachment)
        qa_filename = attachment.get("filename") if attachment else None

        now = datetime.now(timezone.utc)
        approval_request = L3ApprovalRequest(
            release_id=state["release_id"],
            status=L3ApprovalStatus.APPROVED,
            approval_url=approval_url,
            created_at=now,
            approved_by="Release Automation (Low Risk)",
            approved_at=now,
            approval_comment="Auto-approved based on LOW risk score.",
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            environment=state["environment"],
            release_date=state["release_date"],
            raised_by=raised_by,
            pr_title=pr_title,
            qa_signoff_required=state["qa_signoff_required"],
            has_qa_attachment=has_qa_attachment,
            qa_signoff_attachment_filename=qa_filename,
            risk_score=risk_score,
        )

        mail_draft = build_l3_merged_notification_mail_draft(
            release_id=state["release_id"],
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            environment=state["environment"],
            release_date=state["release_date"],
            raised_by=raised_by,
            pr_title=pr_title,
            recipient_emails=self.settings.l3_manager_emails,
            change_description=release_summary,
            risk_score=risk_score,
        )

        logger.info(
            "[L3_AGENT] Low-risk merged notification created for %s (mail draft to %s)",
            state["release_id"],
            ", ".join(mail_draft.to) or "(no recipients configured)",
        )
        return approval_request, mail_draft

    async def _update_jira_ticket_status_impl(
        self,
        *,
        issue_key: str,
        release_id: str,
        low_risk: bool = False,
    ) -> bool:
        """Transition the Jira ticket to the L3-approved status via Jira MCP tools."""
        target_status = self.settings.jira_l3_approved_status
        metadata = {
            "low_risk_auto_approval": low_risk,
            "target_status": target_status,
        }
        logger.info(
            "[L3_AGENT] Updating Jira ticket %s to %s for release %s (low_risk=%s)",
            issue_key,
            target_status,
            release_id,
            low_risk,
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.L3,
            phase=WorkflowEventPhase.STARTED,
            message=f"Transitioning Jira ticket {issue_key} to {target_status}",
            metadata=metadata,
        )
        jira_service = JiraWorkflowService(settings=self.settings)
        try:
            updated = await jira_service.transition_to_status(issue_key, target_status)
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.L3,
                phase=WorkflowEventPhase.COMPLETED if updated else WorkflowEventPhase.ERROR,
                message=(
                    f"Jira ticket {issue_key} transitioned to {target_status}"
                    if updated
                    else f"Failed to transition Jira ticket {issue_key} to {target_status}"
                ),
                metadata=metadata,
            )
            return updated
        except Exception:
            logger.exception(
                "[L3_AGENT] Jira status update failed for %s on release %s",
                issue_key,
                release_id,
            )
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.L3,
                phase=WorkflowEventPhase.ERROR,
                message=f"Failed to transition Jira ticket {issue_key} to {target_status}",
                metadata=metadata,
            )
            return False

    def _build_approval_url(self, release_id: str) -> str:
        base = self.settings.portal_base_url.rstrip("/")
        return f"{base}/approvals/l3/{release_id}"


def _metadata_str(metadata: dict, key: str) -> str | None:
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
