"""LangChain tools for the LLM release orchestrator."""

from __future__ import annotations

import logging
from typing import Any

from langchain.tools import tool

from app.agents.orchestrator import Orchestrator
from app.agents.workflow_context import WorkflowRunContext
from app.models.release import OverallValidationStatus, jira_required
from app.models.validation import (
    GitHubValidationResult,
    JiraValidationResult,
    QAChecks,
    QAValidationResult,
    ValidationStatus,
)
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase

logger = logging.getLogger(__name__)


def build_orchestrator_tools(
    orchestrator: Orchestrator,
    ctx: WorkflowRunContext,
) -> list:
    """Tools the orchestrator LLM uses to coordinate validation, L3, and PR comments."""

    @tool
    async def validate_github_pull_request() -> dict:
        """Validate the GitHub pull request for this release via GitHub MCP.

        Call this first. Checks PR exists, source branch matches release branch,
        target branch is present, and retrieves PR metadata (author, branches, comments).
        """
        ctx.tool_calls.append("validate_github_pull_request")
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.STARTED,
            message="GitHub PR validation started",
        )
        result = await orchestrator.run_github_validation(ctx.state, ctx=ctx)
        ctx.github_validation = result
        ctx.record_validation("github_validation", result)
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.COMPLETED,
            message=f"GitHub PR validation completed — {result.status.value}",
            metadata={"status": result.status.value},
        )
        return _compact_github_payload(result, qa_mode=ctx.state.get("qa_mode"))

    @tool
    async def validate_jira_ticket() -> dict:
        """Validate the Jira ticket by invoking the Jira LangChain agent."""
        ctx.tool_calls.append("validate_jira_ticket")
        if not jira_required(ctx.state.get("qa_mode")):
            ctx.emit(
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.STARTED,
                message="GitHub issues scope validation started",
            )
            ctx.emit(
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.COMPLETED,
                message="GitHub issues scope validation completed — PASS",
            )
            return {
                "status": "SKIPPED",
                "errors": [],
                "next_action": "validate_qa_signoff",
                "message": (
                    "Jira validation skipped for GitHub-issues QA. "
                    "Call validate_qa_signoff next."
                ),
            }
        ctx.emit(
            agent=WorkflowEventAgent.JIRA,
            phase=WorkflowEventPhase.STARTED,
            message=f"Jira validation started for {ctx.state['jira_issue_key']}",
        )
        pr_description = None
        if ctx.github_validation:
            raw = ctx.github_validation.metadata.get("pr_description")
            if isinstance(raw, str):
                pr_description = raw
        result = await orchestrator.run_jira_validation(
            ctx.state,
            github_validation=ctx.github_validation,
            pr_description=pr_description,
            ctx=ctx,
        )
        ctx.jira_validation = result
        ctx.record_validation("jira_validation", result)
        ctx.emit(
            agent=WorkflowEventAgent.JIRA,
            phase=WorkflowEventPhase.COMPLETED,
            message=f"Jira validation completed — {result.status.value}",
            metadata={"status": result.status.value, "errors": result.errors},
        )
        return _compact_jira_payload(result)

    @tool
    async def validate_qa_signoff() -> dict:
        """Validate QA sign-off by invoking the QA LangChain agent."""
        ctx.tool_calls.append("validate_qa_signoff")
        ctx.emit(
            agent=WorkflowEventAgent.QA,
            phase=WorkflowEventPhase.STARTED,
            message="QA sign-off validation started",
        )
        pr_title = None
        if ctx.github_validation:
            raw = ctx.github_validation.metadata.get("pr_title")
            if isinstance(raw, str) and raw.strip():
                pr_title = raw.strip()
        result = await orchestrator.run_qa_validation(
            ctx.state,
            pr_title=pr_title,
            jira_validation=ctx.jira_validation,
            github_validation=ctx.github_validation,
            ctx=ctx,
        )
        ctx.qa_validation = result
        ctx.record_validation("qa_validation", result)
        ctx.emit(
            agent=WorkflowEventAgent.QA,
            phase=WorkflowEventPhase.COMPLETED,
            message=f"QA sign-off validation completed — {result.status.value}",
            metadata={"status": result.status.value},
        )
        return _compact_qa_payload(result)

    @tool
    async def prepare_l3_approval() -> dict:
        """Invoke the L3 LangChain agent after GitHub, Jira, and QA all pass.

        Scores risk, queues L3 approval (MEDIUM/HIGH), or auto-merges via the
        merge LangChain agent when risk is LOW.
        """
        ctx.tool_calls.append("prepare_l3_approval")
        if not ctx.github_validation:
            return {"error": "GitHub validation has not been run."}
        result = await orchestrator.run_l3_approval_preparation(
            ctx.state,
            github_result=ctx.github_validation,
            jira_result=ctx.jira_validation,
            ctx=ctx,
        )
        ctx.l3_flow = result
        return result

    @tool
    async def post_release_failure_comment(comment_body: str) -> str:
        """Post a validation failure comment on the GitHub PR. Call only after a validation FAIL/ERROR."""
        ctx.tool_calls.append("post_release_failure_comment")
        if not _has_validation_failure(ctx):
            logger.warning(
                "[ORCHESTRATOR] Skipping premature failure comment "
                "(GitHub=%s Jira=%s QA=%s)",
                _status_value(ctx.github_validation),
                _status_value(ctx.jira_validation),
                _status_value(ctx.qa_validation),
            )
            return (
                "Skipped: no validation failure to report. "
                "If GitHub passed, call validate_jira_ticket next. "
                "Do not post a failure comment."
            )
        if ctx.github_comment_attempted:
            return (
                "Comment posted successfully."
                if ctx.github_comment_posted
                else "Failed to post comment."
            )
        if _cannot_comment_on_invalid_pr(ctx):
            ctx.github_comment_attempted = True
            logger.info("[ORCHESTRATOR] Skipping GitHub failure comment — PR URL is invalid")
            return "Skipped: cannot post a comment because the GitHub PR URL is invalid."
        ctx.github_comment_attempted = True
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.INFO,
            message="Posting validation failure comment on GitHub PR",
        )
        posted = await orchestrator.post_github_failure_comment(ctx.state, comment_body, ctx=ctx)
        ctx.github_comment_posted = posted
        ctx.emit(
            agent=WorkflowEventAgent.ORCHESTRATOR,
            phase=WorkflowEventPhase.COMPLETED if posted else WorkflowEventPhase.ERROR,
            message="Validation failure comment posted on GitHub PR"
            if posted
            else "Failed to post validation failure comment on GitHub PR",
        )
        return "Comment posted successfully." if posted else "Failed to post comment."

    return [
        validate_github_pull_request,
        validate_jira_ticket,
        validate_qa_signoff,
        prepare_l3_approval,
        post_release_failure_comment,
    ]


async def run_orchestrator_tool_sequence(
    orchestrator: Orchestrator,
    ctx: WorkflowRunContext,
) -> None:
    """Run remaining orchestrator tools in the required order.

    Idempotent: skips steps already completed (including partial LLM runs).
    Used when the LLM is unavailable or when it skipped required steps.
    """
    tools = {tool.name: tool for tool in build_orchestrator_tools(orchestrator, ctx)}

    if ctx.github_validation is None:
        await tools["validate_github_pull_request"].ainvoke({})
    github = ctx.github_validation
    if github is None or github.status == ValidationStatus.ERROR:
        return
    if github.status == ValidationStatus.FAIL:
        await _post_failure_via_tool(orchestrator, ctx, tools, github.errors)
        return

    skip_jira = not jira_required(ctx.state.get("qa_mode"))
    jira = ctx.jira_validation
    if not skip_jira:
        if ctx.jira_validation is None:
            if ctx.github_comment_posted:
                logger.warning(
                    "[ORCHESTRATOR] Clearing premature GitHub failure comment flag after GitHub PASS"
                )
                ctx.github_comment_posted = False
            logger.info("[ORCHESTRATOR] Continuing workflow with Jira validation")
            await tools["validate_jira_ticket"].ainvoke({})
        jira = ctx.jira_validation
        if jira is None:
            return
        if jira.status in (ValidationStatus.FAIL, ValidationStatus.ERROR):
            reasons = jira.errors or [
                "Jira validation could not be completed."
                if jira.status == ValidationStatus.ERROR
                else "Jira validation failed."
            ]
            await _post_failure_via_tool(orchestrator, ctx, tools, reasons)
            return
    elif ctx.github_comment_posted:
        logger.warning(
            "[ORCHESTRATOR] Clearing premature GitHub failure comment flag after GitHub PASS"
        )
        ctx.github_comment_posted = False

    if ctx.qa_validation is None:
        logger.info("[ORCHESTRATOR] Continuing workflow with QA validation")
        await tools["validate_qa_signoff"].ainvoke({})
    qa = ctx.qa_validation
    if github is None or qa is None or (not skip_jira and jira is None):
        return

    overall_status, failure_reasons = orchestrator.evaluate_validation(
        github, None if skip_jira else jira, qa
    )
    if overall_status == OverallValidationStatus.PASS:
        if ctx.l3_flow is None:
            await tools["prepare_l3_approval"].ainvoke({})
        return
    await _post_failure_via_tool(orchestrator, ctx, tools, failure_reasons)


async def _post_failure_via_tool(
    orchestrator: Orchestrator,
    ctx: WorkflowRunContext,
    tools: dict,
    failure_reasons: list[str],
) -> None:
    if ctx.github_comment_posted or ctx.github_comment_attempted:
        return
    comment = orchestrator.build_failure_comment(
        ctx.state,
        ctx.github_validation,
        ctx.jira_validation or _empty_jira(),
        ctx.qa_validation or _empty_qa(),
        failure_reasons,
    )
    await tools["post_release_failure_comment"].ainvoke({"comment_body": comment})


def _status_value(result: GitHubValidationResult | JiraValidationResult | QAValidationResult | None) -> str:
    if result is None:
        return "not_run"
    return result.status.value


def _has_validation_failure(ctx: WorkflowRunContext) -> bool:
    for result in (ctx.github_validation, ctx.jira_validation, ctx.qa_validation):
        if result is not None and result.status in (ValidationStatus.FAIL, ValidationStatus.ERROR):
            return True
    return False


def _cannot_comment_on_invalid_pr(ctx: WorkflowRunContext) -> bool:
    github = ctx.github_validation
    if github is None:
        return False
    return any(
        "Provide the valid url this url is invalid" in error for error in github.errors
    )


def _compact_github_payload(
    result: GitHubValidationResult,
    *,
    qa_mode: str | None = None,
) -> dict[str, Any]:
    metadata = result.metadata or {}
    payload: dict[str, Any] = {
        "status": result.status.value,
        "errors": result.errors,
        "checks": result.checks.model_dump(),
        "source_branch": metadata.get("source_branch"),
        "target_branch": metadata.get("target_branch"),
        "pr_title": metadata.get("pr_title"),
        "files_changed_count": metadata.get("files_changed_count"),
    }
    if result.status == ValidationStatus.PASS:
        if jira_required(qa_mode):
            payload["next_action"] = "validate_jira_ticket"
            payload["message"] = (
                "GitHub validation PASSED. Do not post a failure comment. "
                "Call validate_jira_ticket next."
            )
        else:
            payload["next_action"] = "validate_qa_signoff"
            payload["message"] = (
                "GitHub validation PASSED. Do not post a failure comment. "
                "Jira is skipped for GitHub-issues QA. Call validate_qa_signoff next."
            )
    elif result.status == ValidationStatus.FAIL:
        payload["next_action"] = "post_release_failure_comment"
        payload["message"] = "GitHub validation FAILED. Call post_release_failure_comment and stop."
    else:
        payload["next_action"] = "stop"
        payload["message"] = "GitHub validation ERROR. Stop the workflow."
    return payload


def _compact_jira_payload(result: JiraValidationResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status.value,
        "errors": result.errors,
        "checks": result.checks.model_dump(),
    }
    if result.status == ValidationStatus.PASS:
        payload["next_action"] = "validate_qa_signoff"
        payload["message"] = "Jira validation PASSED. Call validate_qa_signoff next."
    else:
        payload["next_action"] = "post_release_failure_comment"
        payload["message"] = (
            f"Jira validation {result.status.value}. Call post_release_failure_comment and stop."
        )
    return payload


def _compact_qa_payload(result: QAValidationResult) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": result.status.value,
        "errors": result.errors,
        "checks": result.checks.model_dump(),
    }
    if result.status == ValidationStatus.PASS:
        payload["next_action"] = "prepare_l3_approval"
        payload["message"] = "QA validation PASSED. Call prepare_l3_approval next."
    else:
        payload["next_action"] = "post_release_failure_comment"
        payload["message"] = (
            f"QA validation {result.status.value}. Call post_release_failure_comment and stop."
        )
    return payload


def _empty_jira() -> JiraValidationResult:
    return JiraValidationResult(
        status=ValidationStatus.PASS,
        checks={},
        errors=[],
    )


def _empty_qa() -> QAValidationResult:
    return QAValidationResult(
        status=ValidationStatus.PASS,
        checks=QAChecks(signoff_required=False, signoff_completed=True),
        errors=[],
    )
