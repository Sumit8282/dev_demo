"""Release orchestrator agent — LangChain agent that coordinates GitHub, Jira, QA, and L3."""

from __future__ import annotations

import logging

from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_langchain_agent
from app.agents.orchestrator import Orchestrator
from app.agents.tools.orchestrator_tools import (
    build_orchestrator_tools,
    run_orchestrator_tool_sequence,
)
from app.agents.workflow_context import WorkflowRunContext
from app.config import Settings, get_settings
from app.models.release import OverallValidationStatus, WorkflowStatus
from app.models.validation import (
    GitHubValidationResult,
    JiraValidationResult,
    QAChecks,
    QAValidationResult,
    ValidationStatus,
)
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.prompts import format_prompt, load_prompt
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)


class ReleaseOrchestratorAgent:
    """LangChain orchestrator that delegates to GitHub tools and Jira/QA/L3/merge agents."""

    def __init__(
        self,
        orchestrator: Orchestrator | None = None,
        settings: Settings | None = None,
    ) -> None:
        self._orchestrator = orchestrator or Orchestrator()
        self._settings = settings or get_settings()

    def build_langchain_agent(self, ctx: WorkflowRunContext, llm: BaseChatModel | None = None):
        """Build the release orchestrator LangChain agent with coordination tools."""
        return create_langchain_agent(
            settings=self._settings,
            tools=build_orchestrator_tools(self._orchestrator, ctx),
            system_prompt=load_prompt("orchestrator_system"),
            name="release_orchestrator",
            llm=llm,
        )

    async def ainvoke(self, state: ReleaseState) -> ReleaseState:
        """Invoke the orchestrator LangChain agent, then map tool results to workflow state."""
        logger.info("[WORKFLOW] Initializing release %s", state["release_id"])

        ctx = WorkflowRunContext(
            state={
                **state,
                "workflow_status": WorkflowStatus.VALIDATING.value,
                "failure_reasons": [],
                "github_comment_posted": False,
            }
        )
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.STARTED,
            message="Release workflow validation started",
        )

        agent = self.build_langchain_agent(ctx)
        if agent is not None:
            await invoke_langchain_agent(
                agent,
                user_message=format_prompt(
                    "orchestrator_user",
                    release_id=state["release_id"],
                    release_branch=state["release_branch"],
                    release_version=state["release_version"],
                    environment=state["environment"],
                    release_date=state["release_date"],
                    github_pr_url=state["github_pr_url"],
                    github_owner=state["github_owner"],
                    github_repo=state["github_repo"],
                    github_pr_number=state["github_pr_number"],
                    jira_url=state["jira_url"],
                    jira_issue_key=state["jira_issue_key"],
                    qa_signoff_required=state["qa_signoff_required"],
                    qa_signoff_not_required_reason=state.get("qa_signoff_not_required_reason")
                    or "(none)",
                ),
            )

        # Always finish remaining required steps. The LLM may skip Jira/QA or
        # post a failure comment after GitHub PASS; do not trust tool_calls alone.
        await run_orchestrator_tool_sequence(self._orchestrator, ctx)

        return await self._finalize(ctx)

    async def _finalize(self, ctx: WorkflowRunContext) -> ReleaseState:
        github_result = ctx.github_validation
        current: ReleaseState = {
            **ctx.state,
            "github_validation": github_result.model_dump() if github_result else None,
            "github_comment_posted": ctx.github_comment_posted,
        }
        if ctx.jira_validation is not None:
            current["jira_validation"] = ctx.jira_validation.model_dump()
        if ctx.qa_validation is not None:
            current["qa_validation"] = ctx.qa_validation.model_dump()

        if github_result is None:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="GitHub validation did not run",
            )
            return {
                **current,
                "overall_validation_status": OverallValidationStatus.ERROR.value,
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
                "failure_reasons": ["GitHub validation did not run."],
            }

        if github_result.status == ValidationStatus.ERROR:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="GitHub validation error",
                metadata={"failure_reasons": github_result.errors},
            )
            return {
                **current,
                "overall_validation_status": OverallValidationStatus.ERROR.value,
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
                "failure_reasons": github_result.errors,
            }

        if github_result.status == ValidationStatus.FAIL:
            posted = await self._ensure_failure_comment(
                current,
                github_result,
                ctx.jira_validation or _empty_jira_result(),
                ctx.qa_validation or _empty_qa_result(),
                github_result.errors,
                ctx=ctx,
            )
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.COMPLETED,
                message="Workflow halted — GitHub validation failed",
                metadata={"overall_status": OverallValidationStatus.FAIL.value},
            )
            return {
                **current,
                "overall_validation_status": OverallValidationStatus.FAIL.value,
                "workflow_status": WorkflowStatus.HALTED.value,
                "failure_reasons": github_result.errors,
                "github_comment_posted": posted,
            }

        jira_result = ctx.jira_validation
        if jira_result is None:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="Jira Ticket is not validated",
            )
            return {
                **current,
                "overall_validation_status": OverallValidationStatus.ERROR.value,
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
                "failure_reasons": ["Jira Ticket is not validated."],
            }

        if jira_result.status in (ValidationStatus.FAIL, ValidationStatus.ERROR):
            failure_reasons = jira_result.errors or [
                "Jira validation could not be completed."
                if jira_result.status == ValidationStatus.ERROR
                else "Jira validation failed."
            ]
            posted = await self._ensure_failure_comment(
                current,
                github_result,
                jira_result,
                ctx.qa_validation or _empty_qa_result(),
                failure_reasons,
                ctx=ctx,
            )
            overall_status = (
                OverallValidationStatus.ERROR
                if jira_result.status == ValidationStatus.ERROR
                else OverallValidationStatus.FAIL
            )
            workflow_status = (
                WorkflowStatus.VALIDATION_ERROR
                if jira_result.status == ValidationStatus.ERROR
                else WorkflowStatus.HALTED
            )
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.COMPLETED
                if workflow_status == WorkflowStatus.HALTED
                else WorkflowEventPhase.ERROR,
                message="Workflow halted — Jira validation failed"
                if workflow_status == WorkflowStatus.HALTED
                else "Workflow validation error — Jira",
                metadata={
                    "overall_status": overall_status.value,
                    "failure_reasons": failure_reasons,
                },
            )
            return {
                **current,
                "overall_validation_status": overall_status.value,
                "workflow_status": workflow_status.value,
                "failure_reasons": failure_reasons,
                "github_comment_posted": posted,
            }

        qa_result = ctx.qa_validation
        if qa_result is None:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="QA agent was not invoked",
            )
            return {
                **current,
                "overall_validation_status": OverallValidationStatus.ERROR.value,
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
                "failure_reasons": ["QA agent was not invoked."],
            }

        overall_status, failure_reasons = self._orchestrator.evaluate_validation(
            github_result,
            jira_result,
            qa_result,
        )
        current = {
            **current,
            "overall_validation_status": overall_status.value,
            "failure_reasons": failure_reasons,
        }

        if overall_status == OverallValidationStatus.PASS:
            l3_flow = ctx.l3_flow
            if l3_flow is None:
                l3_flow = await self._orchestrator.run_l3_approval_preparation(
                    current,
                    github_result=github_result,
                    jira_result=jira_result,
                    ctx=ctx,
                )
                ctx.l3_flow = l3_flow
            workflow_status = l3_flow["workflow_status"]
            risk_score = l3_flow["risk_score"]
            l3_request = l3_flow["l3_approval_request"]
            merge_result = l3_flow.get("merge_result")

            if workflow_status == WorkflowStatus.MERGED.value:
                logger.info(
                    "[WORKFLOW] Low risk release %s merged automatically",
                    ctx.state["release_id"],
                )
                return {
                    **current,
                    "workflow_status": workflow_status,
                    "l3_approval_request": l3_request,
                    "risk_score": risk_score,
                    "merge_result": merge_result,
                }

            if workflow_status == WorkflowStatus.MERGE_FAILED.value:
                ctx.emit(
                    agent=WorkflowEventAgent.ORCHESTRATOR,
                    phase=WorkflowEventPhase.ERROR,
                    message="All validations passed but low risk auto-merge failed",
                    metadata={
                        "overall_status": overall_status.value,
                        "failure_reasons": l3_flow.get("failure_reasons") or [],
                    },
                )
                logger.warning(
                    "[WORKFLOW] Low risk auto-merge failed for release %s",
                    ctx.state["release_id"],
                )
                return {
                    **current,
                    "workflow_status": workflow_status,
                    "l3_approval_request": l3_request,
                    "risk_score": risk_score,
                    "merge_result": merge_result,
                    "failure_reasons": l3_flow.get("failure_reasons") or [],
                }

            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.COMPLETED,
                message="All validations passed — L3 approval pending",
                metadata={"overall_status": overall_status.value},
            )
            logger.info(
                "[WORKFLOW] L3 approval pending for release %s",
                ctx.state["release_id"],
            )
            return {
                **current,
                "workflow_status": workflow_status,
                "l3_approval_request": l3_request,
                "risk_score": risk_score,
            }

        if overall_status == OverallValidationStatus.ERROR:
            logger.error(
                "[WORKFLOW] Validation error for release %s: %s",
                ctx.state["release_id"],
                failure_reasons,
            )
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="Workflow validation error",
                metadata={"failure_reasons": failure_reasons},
            )
            return {
                **current,
                "workflow_status": WorkflowStatus.VALIDATION_ERROR.value,
            }

        posted = await self._ensure_failure_comment(
            current,
            github_result,
            jira_result,
            qa_result,
            failure_reasons,
            ctx=ctx,
        )
        logger.info("[WORKFLOW] Release %s HALTED", ctx.state["release_id"])
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.COMPLETED,
            message="Workflow halted — validation failed",
            metadata={
                "overall_status": overall_status.value,
                "failure_reasons": failure_reasons,
            },
        )
        return {
            **current,
            "github_comment_posted": posted,
            "workflow_status": WorkflowStatus.HALTED.value,
        }

    async def _ensure_failure_comment(
        self,
        state: ReleaseState,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult,
        qa_result: QAValidationResult,
        failure_reasons: list[str],
        *,
        ctx: WorkflowRunContext,
    ) -> bool:
        if ctx.github_comment_posted or ctx.github_comment_attempted:
            return ctx.github_comment_posted
        ctx.github_comment_attempted = True
        comment = self._orchestrator.build_failure_comment(
            state,
            github_result,
            jira_result,
            qa_result,
            failure_reasons,
        )
        posted = await self._orchestrator.post_github_failure_comment(state, comment, ctx=ctx)
        ctx.github_comment_posted = posted
        return posted


def build_release_orchestrator(
    orchestrator: Orchestrator | None = None,
) -> ReleaseOrchestratorAgent:
    """Factory for the release orchestrator LangChain agent."""
    return ReleaseOrchestratorAgent(orchestrator)


def _empty_jira_result() -> JiraValidationResult:
    return JiraValidationResult(
        status=ValidationStatus.PASS,
        checks={},
        errors=[],
    )


def _empty_qa_result() -> QAValidationResult:
    return QAValidationResult(
        status=ValidationStatus.PASS,
        checks=QAChecks(signoff_required=False, signoff_completed=True),
        errors=[],
    )
