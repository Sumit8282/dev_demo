"""Release Orchestrator – GitHub MCP validation, Jira/QA coordination, PR comments."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.jira_agent import (
    JiraAgent,
    extract_github_metadata,
    format_github_code_change_summary,
)
from app.agents.build_agent import BuildAgent
from app.models.build_result import BuildStatus
from app.agents.l3_agent import L3Agent
from app.agents.merge_agent import MergeAgent
from app.agents.qa_agent import QAAgent
from app.agents.rm_agent import RMAgent
from app.agents.workflow_context import WorkflowRunContext
from app.mcp.client_base import MCPConnectionError, MCPToolNotFoundError
from app.mcp.github_mcp import GitHubMCPClient, INVALID_PR_URL_MESSAGE, is_invalid_pr_read_error
from app.models.release import OverallValidationStatus, WorkflowStatus
from app.models.validation import (
    GitHubChecks,
    GitHubValidationResult,
    JiraValidationResult,
    MergeResult,
    QAValidationResult,
    ValidationStatus,
)
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.models.risk_score import ReleaseRiskScore
from app.services.file_failure_history_store import FileFailureHistoryStore
from app.services.mail_service import send_l3_approval_mail, send_rm_approval_notification
from app.services.release_risk_scorer import (
    build_file_changes_from_github_metadata,
    score_release_from_github_metadata,
)
from app.prompts import load_prompt
from app.utils.github_fields import (
    branches_match,
    build_pull_request_change_stats,
    extract_pr_author,
    extract_pr_description,
    extract_pr_head_sha,
    extract_pr_merged,
    extract_pr_number,
    extract_pr_state,
    extract_pr_title,
    extract_pull_request_comments,
    extract_source_branch,
    extract_target_branch,
    pr_exists,
    validate_pr_open_for_release,
)
from app.utils.jira_fields import resolve_jira_ticket_not_found_message
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)


def get_orchestrator_system_prompt() -> str:
    """Return the orchestrator system prompt from ``app/prompts/``."""
    return load_prompt("orchestrator_system")


class Orchestrator:
    def __init__(
        self,
        jira_agent: JiraAgent | None = None,
        qa_agent: QAAgent | None = None,
        l3_agent: L3Agent | None = None,
        build_agent: BuildAgent | None = None,
        rm_agent: RMAgent | None = None,
        merge_agent: MergeAgent | None = None,
        github_client: GitHubMCPClient | None = None,
        failure_history_store: FileFailureHistoryStore | None = None,
    ) -> None:
        self._github_client = github_client
        self.jira_agent = jira_agent or JiraAgent()
        self.qa_agent = qa_agent or QAAgent()
        self.l3_agent = l3_agent or L3Agent()
        self.build_agent = build_agent or BuildAgent()
        self.rm_agent = rm_agent or RMAgent()
        self.merge_agent = merge_agent or MergeAgent(github_client=github_client)
        self._failure_history_store = failure_history_store or FileFailureHistoryStore()

    @property
    def github_client(self) -> GitHubMCPClient | None:
        return self._github_client

    async def run_github_validation(
        self,
        state: ReleaseState,
        *,
        ctx: WorkflowRunContext | None = None,
    ) -> GitHubValidationResult:
        """Validate GitHub PR via MCP and parse PR metadata (same client used for comments)."""
        owner = state["github_owner"]
        repo = state["github_repo"]
        pull_number = state["github_pr_number"]
        expected_release_branch = state["release_branch"]
        github_pr_url = state["github_pr_url"]

        logger.info(
            "[ORCHESTRATOR] Validating GitHub PR %s/%s#%s",
            owner,
            repo,
            pull_number,
        )

        checks = GitHubChecks()
        errors: list[str] = []
        metadata: dict[str, str | int | list[dict[str, str]]] = {
            "github_pr_url": github_pr_url,
            "owner": owner,
            "repo": repo,
            "pull_number": pull_number,
        }

        try:
            async with self._get_github_client() as client:
                pr_data = await client.get_pull_request(owner, repo, pull_number)
                metadata["mcp_tool"] = client.get_pull_request_tool_name()

                comments_data = await client.get_pull_request_comments(owner, repo, pull_number)
                comments = extract_pull_request_comments(comments_data)
                checks.comments_retrieved = True
                metadata["comment_count"] = len(comments)
                metadata["comments"] = comments[:20]

                change_stats = await self._collect_pull_request_change_stats(
                    client,
                    owner=owner,
                    repo=repo,
                    pull_number=pull_number,
                    pr_data=pr_data,
                )
                if change_stats:
                    metadata.update(change_stats)
                    self._log_pull_request_change_stats(owner, repo, pull_number, change_stats)
                    if ctx:
                        ctx.emit(
                            agent=WorkflowEventAgent.ORCHESTRATOR,
                            phase=WorkflowEventPhase.INFO,
                            message=(
                                f"PR change summary — {change_stats['files_changed_count']} files, "
                                f"+{change_stats['lines_added']} / -{change_stats['lines_deleted']} lines"
                            ),
                            metadata={
                                "files_changed_count": change_stats["files_changed_count"],
                                "lines_added": change_stats["lines_added"],
                                "lines_deleted": change_stats["lines_deleted"],
                                "changed_file_names": change_stats["changed_file_names"],
                            },
                        )
        except (MCPConnectionError, MCPToolNotFoundError) as exc:
            if is_invalid_pr_read_error(exc):
                message = INVALID_PR_URL_MESSAGE
                status = ValidationStatus.FAIL
            else:
                message = f"GitHub MCP connection error: {exc}"
                status = ValidationStatus.ERROR
            logger.error("[ORCHESTRATOR] GitHub MCP error: %s", message)
            if ctx:
                ctx.emit(
                    agent=WorkflowEventAgent.ORCHESTRATOR,
                    phase=WorkflowEventPhase.ERROR,
                    message=message,
                )
            return GitHubValidationResult(
                status=status,
                checks=checks,
                errors=[message],
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("[ORCHESTRATOR] GitHub PR validation error")
            return GitHubValidationResult(
                status=ValidationStatus.ERROR,
                checks=checks,
                errors=[f"GitHub PR validation failed: {exc}"],
                metadata=metadata,
            )

        parsed_number = extract_pr_number(pr_data) or pull_number
        source_branch = extract_source_branch(pr_data)
        target_branch = extract_target_branch(pr_data)
        pr_title = extract_pr_title(pr_data)
        pr_state = extract_pr_state(pr_data)
        pr_merged = extract_pr_merged(pr_data)
        pr_author = extract_pr_author(pr_data)
        pr_description = extract_pr_description(pr_data)

        metadata["pull_number"] = parsed_number
        metadata["source_branch"] = source_branch or ""
        metadata["target_branch"] = target_branch or ""
        if pr_title:
            metadata["pr_title"] = pr_title
        if pr_state:
            metadata["pr_state"] = pr_state
        if pr_merged is not None:
            metadata["pr_merged"] = pr_merged
        if pr_author:
            metadata["author"] = pr_author
            metadata["raised_by"] = pr_author
        if pr_description:
            metadata["pr_description"] = pr_description
        head_sha = extract_pr_head_sha(pr_data)
        if head_sha:
            metadata["head_sha"] = head_sha

        checks.pr_exists = pr_exists(pr_data)
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.CHECK,
                message=f"PR exists — {'PASS' if checks.pr_exists else 'FAIL'}",
                metadata={"check": "pr_exists", "passed": checks.pr_exists},
            )
        if not checks.pr_exists:
            errors.append(
                f"GitHub pull request {owner}/{repo}#{pull_number} was not found or could not be retrieved."
            )
            return self._github_result(checks, errors, metadata, ValidationStatus.FAIL)

        pr_open, pr_state_error = validate_pr_open_for_release(pr_data)
        checks.pr_is_open = pr_open
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.CHECK,
                message=f"PR is open — {'PASS' if checks.pr_is_open else 'FAIL'}",
                metadata={
                    "check": "pr_is_open",
                    "passed": checks.pr_is_open,
                    "pr_state": pr_state or "",
                    "pr_merged": pr_merged,
                },
            )
        if not checks.pr_is_open and pr_state_error:
            errors.append(pr_state_error)
            return self._github_result(checks, errors, metadata, ValidationStatus.FAIL)

        if not source_branch:
            checks.source_branch_match = False
            errors.append("GitHub PR source branch metadata is unavailable.")
        elif branches_match(expected_release_branch, source_branch):
            checks.source_branch_match = True
        else:
            checks.source_branch_match = False
            errors.append(
                f"GitHub PR source branch '{source_branch}' does not match release branch "
                f"'{expected_release_branch}'."
            )
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.CHECK,
                message=(
                    f"Source branch match ({source_branch or 'unknown'}) — "
                    f"{'PASS' if checks.source_branch_match else 'FAIL'}"
                ),
                metadata={"check": "source_branch_match", "passed": checks.source_branch_match},
            )

        if target_branch:
            checks.target_branch_present = True
        else:
            checks.target_branch_present = False
            errors.append("GitHub PR target branch metadata is unavailable.")
        if ctx and not checks.target_branch_present:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.CHECK,
                message="Target branch metadata unavailable — FAIL",
                metadata={"check": "target_branch_present", "passed": False},
            )
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.CHECK,
                message=f"PR comments retrieved — {'PASS' if checks.comments_retrieved else 'FAIL'}",
                metadata={"check": "comments_retrieved", "passed": checks.comments_retrieved},
            )

        status_value = (
            ValidationStatus.PASS
            if checks.pr_exists
            and checks.pr_is_open
            and checks.source_branch_match
            and checks.target_branch_present
            and checks.comments_retrieved
            else ValidationStatus.FAIL
        )
        return self._github_result(checks, errors, metadata, status_value)

    async def _collect_pull_request_change_stats(
        self,
        client: GitHubMCPClient,
        *,
        owner: str,
        repo: str,
        pull_number: int,
        pr_data: dict,
    ) -> dict[str, Any] | None:
        try:
            files_data = await client.get_pull_request_files(owner, repo, pull_number)
            return build_pull_request_change_stats(pr_data, files_data)
        except Exception as exc:
            logger.warning(
                "[ORCHESTRATOR] Unable to retrieve PR file change stats for %s/%s#%s: %s",
                owner,
                repo,
                pull_number,
                exc,
            )
            summary = build_pull_request_change_stats(pr_data, [])
            if summary["files_changed_count"] or summary["lines_added"] or summary["lines_deleted"]:
                return summary
            return None

    @staticmethod
    def _log_pull_request_change_stats(
        owner: str,
        repo: str,
        pull_number: int,
        change_stats: dict[str, Any],
    ) -> None:
        file_names = change_stats.get("changed_file_names") or []
        logger.info(
            "[ORCHESTRATOR] GitHub PR %s/%s#%s change summary: %s files changed, "
            "+%s lines added, -%s lines deleted",
            owner,
            repo,
            pull_number,
            change_stats.get("files_changed_count", 0),
            change_stats.get("lines_added", 0),
            change_stats.get("lines_deleted", 0),
        )
        if file_names:
            logger.info(
                "[ORCHESTRATOR] GitHub PR %s/%s#%s changed files: %s",
                owner,
                repo,
                pull_number,
                ", ".join(str(name) for name in file_names),
            )
        for file_entry in change_stats.get("changed_files") or []:
            if not isinstance(file_entry, dict):
                continue
            logger.info(
                "[ORCHESTRATOR] GitHub PR %s/%s#%s file %s (%s): +%s / -%s",
                owner,
                repo,
                pull_number,
                file_entry.get("filename", "unknown"),
                file_entry.get("status", "modified"),
                file_entry.get("additions", 0),
                file_entry.get("deletions", 0),
            )

    async def run_jira_validation(
        self,
        state: ReleaseState,
        *,
        github_validation: GitHubValidationResult | dict | None = None,
        pr_description: str | None = None,
        ctx: WorkflowRunContext | None = None,
    ) -> JiraValidationResult:
        github_metadata = extract_github_metadata(github_validation)
        result = await self.jira_agent.validate(
            issue_key=state["jira_issue_key"],
            expected_release_version=state["release_version"],
            pr_description=pr_description or _metadata_str(github_metadata, "pr_description"),
            pr_title=_metadata_str(github_metadata, "pr_title"),
            pr_comments=github_metadata.get("comments") if isinstance(github_metadata.get("comments"), list) else None,
            code_change_summary=format_github_code_change_summary(github_metadata),
        )
        if ctx:
            self._emit_jira_check_events(ctx, result)
        return result

    @staticmethod
    def _emit_jira_check_events(ctx: WorkflowRunContext, result: JiraValidationResult) -> None:
        checks = result.checks
        issue_key = str((result.metadata or {}).get("issue_key") or "Jira ticket")

        if not checks.ticket_exists:
            error_message = resolve_jira_ticket_not_found_message(issue_key, result.errors)
            ctx.emit(
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.CHECK,
                message="Jira ticket exists — FAIL",
                metadata={
                    "check": "ticket_exists",
                    "passed": False,
                    "error_message": error_message,
                },
            )
            return

        check_messages = [
            ("ticket_exists", checks.ticket_exists, "Jira ticket exists"),
            ("status_valid", checks.status_valid, "Jira status valid"),
        ]
        for check_name, passed, label in check_messages:
            ctx.emit(
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.CHECK,
                message=f"{label} — {'PASS' if passed else 'FAIL'}",
                metadata={"check": check_name, "passed": passed},
            )

        if checks.fix_version_match is False:
            ctx.emit(
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.CHECK,
                message="Fix version matches release — FAIL",
                metadata={"check": "fix_version_match", "passed": False},
            )

        code_validation_passed = checks.description_match
        ctx.emit(
            agent=WorkflowEventAgent.JIRA,
            phase=WorkflowEventPhase.CHECK,
            message=(
                "Code validation successful — PASS"
                if code_validation_passed
                else "Code validation failed — FAIL"
            ),
            metadata={"check": "description_match", "passed": code_validation_passed},
        )

    async def run_l3_approval_preparation(
        self,
        state: ReleaseState,
        *,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult | None = None,
        ctx: WorkflowRunContext | None = None,
    ) -> dict[str, Any]:
        """Score risk, then either auto-merge (LOW) or queue L3 approval (MEDIUM/HIGH)."""
        github_metadata = github_result.metadata or {}
        changed_files = build_file_changes_from_github_metadata(github_metadata)
        filepaths = [item.filepath for item in changed_files]
        historical_rates = self._failure_history_store.get_failure_rates(filepaths)
        risk_result = score_release_from_github_metadata(
            github_metadata,
            historical_rates,
        )
        risk_score = ReleaseRiskScore.from_scorer_result(risk_result)

        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.INFO,
                message=(
                    f"Risk score: {risk_score.score:.2f} — Risk level: {risk_score.level}"
                ),
                metadata={
                    "risk_score": risk_score.score,
                    "risk_level": risk_score.level,
                    "files_changed_count": github_metadata.get("files_changed_count", 0),
                    "lines_added": github_metadata.get("lines_added", 0),
                    "lines_deleted": github_metadata.get("lines_deleted", 0),
                    "changed_file_names": github_metadata.get("changed_file_names", []),
                },
            )

        if risk_score.level == "LOW":
            return await self._run_low_risk_auto_merge_flow(
                state,
                github_result=github_result,
                jira_result=jira_result,
                risk_score=risk_score,
                ctx=ctx,
            )

        return await self._run_l3_approval_pending_flow(
            state,
            github_result=github_result,
            jira_result=jira_result,
            risk_score=risk_score,
            ctx=ctx,
        )

    async def _run_l3_approval_pending_flow(
        self,
        state: ReleaseState,
        *,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult | None,
        risk_score: ReleaseRiskScore,
        ctx: WorkflowRunContext | None = None,
    ) -> dict[str, Any]:
        """Create L3 approval queue entry and send approval notification email."""
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.L3,
                phase=WorkflowEventPhase.STARTED,
                message="Creating L3 approval request",
            )
        approval_request, mail_draft = await self.l3_agent.create_approval_request(
            state,
            github_validation=github_result,
            jira_validation=jira_result,
            risk_score=risk_score,
        )
        mail_sent = send_l3_approval_mail(mail_draft)
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.L3,
                phase=WorkflowEventPhase.COMPLETED if mail_sent else WorkflowEventPhase.ERROR,
                message=(
                    f"L3 approval email sent — {approval_request.approval_url}"
                    if mail_sent
                    else f"L3 approval email failed to send — {approval_request.approval_url}"
                ),
                metadata={
                    "approval_url": approval_request.approval_url,
                    "mail_sent": mail_sent,
                    "risk_score": risk_score.score,
                    "risk_level": risk_score.level,
                },
            )
        return {
            "l3_approval_request": approval_request.model_dump(mode="json"),
            "risk_score": risk_score.model_dump(mode="json"),
            "workflow_status": WorkflowStatus.L3_APPROVAL_PENDING.value,
            "merge_result": None,
        }

    async def _run_low_risk_auto_merge_flow(
        self,
        state: ReleaseState,
        *,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult | None,
        risk_score: ReleaseRiskScore,
        ctx: WorkflowRunContext | None = None,
    ) -> dict[str, Any]:
        """Auto-approve, notify L3, and merge the PR when risk is LOW."""
        approval_request, mail_draft = await self.l3_agent.create_low_risk_merged_notification(
            state,
            github_validation=github_result,
            jira_validation=jira_result,
            risk_score=risk_score,
        )
        mail_sent = send_l3_approval_mail(mail_draft)
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.L3,
                phase=WorkflowEventPhase.COMPLETED,
                message="L3 approval granted by Release Automation system.",
                metadata={
                    "risk_score": risk_score.score,
                    "risk_level": risk_score.level,
                    "auto_merged": True,
                    "mail_sent": mail_sent,
                },
            )
        if ctx and not mail_sent:
            ctx.emit(
                agent=WorkflowEventAgent.ORCHESTRATOR,
                phase=WorkflowEventPhase.ERROR,
                message="L3 merged-notification email failed to send",
                metadata={
                    "mail_sent": mail_sent,
                    "risk_score": risk_score.score,
                    "risk_level": risk_score.level,
                    "auto_merged": True,
                },
            )

        await self.l3_agent.update_jira_ticket_status(
            issue_key=state["jira_issue_key"],
            release_id=state["release_id"],
            low_risk=True,
        )

        merge_state: ReleaseState = {
            **state,
            "workflow_status": WorkflowStatus.L3_APPROVED.value,
            "l3_approval_request": approval_request.model_dump(mode="json"),
            "risk_score": risk_score.model_dump(mode="json"),
        }
        merge_result = await self.run_merge(
            merge_state,
            ctx=ctx,
            low_risk_auto_merge=True,
        )
        merge_payload = merge_result.model_dump(mode="json")

        if merge_result.merged:
            workflow_status = WorkflowStatus.MERGED.value
        else:
            workflow_status = WorkflowStatus.MERGE_FAILED.value
            if ctx:
                ctx.emit(
                    agent=WorkflowEventAgent.ORCHESTRATOR,
                    phase=WorkflowEventPhase.ERROR,
                    message="Low risk release — auto-merge failed",
                    metadata={
                        "risk_level": risk_score.level,
                        "merge_errors": merge_result.errors,
                    },
                )

        return {
            "l3_approval_request": approval_request.model_dump(mode="json"),
            "risk_score": risk_score.model_dump(mode="json"),
            "workflow_status": workflow_status,
            "merge_result": merge_payload,
            "failure_reasons": merge_result.errors if not merge_result.merged else [],
        }

    async def run_build_generation(
        self,
        state: ReleaseState,
        *,
        ctx: WorkflowRunContext | None = None,
        on_run_discovered=None,
    ) -> dict:
        """Generate or observe a release build after merge completes."""
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.BUILD,
                phase=WorkflowEventPhase.STARTED,
                message="Build agent started — generating release build",
            )
        build_result = await self.build_agent.generate_build(
            state,
            on_run_discovered=on_run_discovered,
        )
        build_payload = build_result.model_dump(mode="json")
        if ctx:
            if build_result.status == BuildStatus.FAILED:
                ctx.emit(
                    agent=WorkflowEventAgent.BUILD,
                    phase=WorkflowEventPhase.ERROR,
                    message=(
                        f"Build failed — {build_result.build_id}: "
                        f"{build_result.failure_reason or 'CI/CD pipeline failed'}"
                    ),
                    metadata={
                        "build_id": build_result.build_id,
                        "job_url": build_result.job_url,
                    },
                )
            else:
                ctx.emit(
                    agent=WorkflowEventAgent.BUILD,
                    phase=WorkflowEventPhase.COMPLETED,
                    message=f"Build generated successfully — {build_result.build_id}",
                    metadata={
                        "build_id": build_result.build_id,
                        "job_url": build_result.job_url,
                    },
                )
        return build_payload

    async def run_rm_approval_preparation(
        self,
        state: ReleaseState,
        *,
        build_result: dict,
        ctx: WorkflowRunContext | None = None,
    ) -> tuple[dict, None]:
        """Create RM approval queue entry and send notification email."""
        from app.models.build_result import BuildResult

        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.RM,
                phase=WorkflowEventPhase.STARTED,
                message="RM approval requested",
            )

        build = BuildResult.model_validate(build_result)
        github_validation = state.get("github_validation")
        approval_request, notification_draft = await self.rm_agent.create_approval_request(
            state,
            build_result=build,
            github_validation=github_validation,
        )
        notification_sent = send_rm_approval_notification(notification_draft)
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.RM,
                phase=WorkflowEventPhase.COMPLETED if notification_sent else WorkflowEventPhase.ERROR,
                message=(
                    f"RM approval notification sent — {approval_request.approval_url}"
                    if notification_sent
                    else f"RM approval notification failed to send — {approval_request.approval_url}"
                ),
                metadata={
                    "approval_url": approval_request.approval_url,
                    "approval_queue_url": approval_request.approval_queue_url,
                    "notification_sent": notification_sent,
                    "build_id": build.build_id,
                },
            )
        return approval_request.model_dump(mode="json"), None

    async def run_merge(
        self,
        state: ReleaseState,
        *,
        ctx: WorkflowRunContext | None = None,
        low_risk_auto_merge: bool = False,
    ) -> MergeResult:
        """Validate pre-merge gates and merge the GitHub PR via MCP."""
        logger.info("[ORCHESTRATOR] Starting auto-merge for release %s", state["release_id"])
        if ctx:
            ctx.emit(
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.STARTED,
                message=(
                    "Auto-merge started — low risk release"
                    if low_risk_auto_merge
                    else "Auto-merge agent invoked"
                ),
                metadata={"low_risk_auto_merge": low_risk_auto_merge},
            )
        result = await self.merge_agent.execute_merge(state)
        if ctx:
            if result.merged and low_risk_auto_merge:
                merge_message = "PR automatically merged by Release Automation system"
            else:
                merge_message = f"Merge result: {result.status.value}"
            ctx.emit(
                agent=WorkflowEventAgent.MERGE,
                phase=(
                    WorkflowEventPhase.COMPLETED
                    if result.merged
                    else WorkflowEventPhase.ERROR
                ),
                message=merge_message,
                metadata={
                    "merged": result.merged,
                    "merge_sha": result.merge_sha,
                    "low_risk_auto_merge": low_risk_auto_merge,
                    "auto_merged": low_risk_auto_merge and result.merged,
                },
            )
        return result

    async def run_qa_validation(
        self,
        state: ReleaseState,
        *,
        pr_title: str | None = None,
        jira_validation: JiraValidationResult | dict | None = None,
        github_validation: GitHubValidationResult | dict | None = None,
        ctx: WorkflowRunContext | None = None,
    ) -> QAValidationResult:
        result = await self.qa_agent.validate_async(
            release_id=state["release_id"],
            qa_signoff_required=state["qa_signoff_required"],
            environment=state["environment"],
            release_version=state["release_version"],
            qa_signoff_not_required_reason=state.get("qa_signoff_not_required_reason"),
            pr_title=pr_title,
            qa_signoff_attachment=state.get("qa_signoff_attachment"),
            jira_issue_key=state.get("jira_issue_key"),
            jira_validation=jira_validation or state.get("jira_validation"),
            qa_mode=state.get("qa_mode"),
            github_validation=(
                github_validation
                or (ctx.github_validation if ctx else None)
                or state.get("github_validation")
            ),
        )
        if ctx:
            checks = result.checks
            if checks.signoff_required:
                qa_mode = (result.metadata or {}).get("qa_mode") or "upload"
                if qa_mode == "pr_tests":
                    check_message = (
                        f"Lane 1 PR test coverage (sha={(result.metadata or {}).get('head_sha') or 'unknown'}) — "
                        f"{'PASS' if checks.signoff_completed else 'FAIL'}"
                    )
                elif qa_mode == "github_issues":
                    check_message = (
                        f"Lane 1 GitHub issue coverage (sha={(result.metadata or {}).get('head_sha') or 'unknown'}) — "
                        f"{'PASS' if checks.signoff_completed else 'FAIL'}"
                    )
                else:
                    check_message = (
                        f"QA sign-off attachment validated — "
                        f"{'PASS' if checks.signoff_completed else 'FAIL'}"
                    )
                ctx.emit(
                    agent=WorkflowEventAgent.QA,
                    phase=WorkflowEventPhase.CHECK,
                    message=check_message,
                    metadata={"check": "signoff_completed", "passed": checks.signoff_completed},
                )
            else:
                ctx.emit(
                    agent=WorkflowEventAgent.QA,
                    phase=WorkflowEventPhase.CHECK,
                    message="QA sign-off not required — PASS",
                    metadata={"check": "signoff_not_required", "passed": True},
                )
            if result.errors:
                ctx.emit(
                    agent=WorkflowEventAgent.QA,
                    phase=WorkflowEventPhase.CHECK,
                    message=f"Open bugs / sign-off issues — FAIL ({'; '.join(result.errors)})",
                    metadata={"check": "no_open_bugs", "passed": False},
                )
            elif result.status == ValidationStatus.PASS:
                ctx.emit(
                    agent=WorkflowEventAgent.QA,
                    phase=WorkflowEventPhase.CHECK,
                    message="No open bugs — PASS",
                    metadata={"check": "no_open_bugs", "passed": True},
                )
        return result

    def evaluate_validation(
        self,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult | None,
        qa_result: QAValidationResult,
    ) -> tuple[OverallValidationStatus, list[str]]:
        failure_reasons: list[str] = []

        if github_result.status == ValidationStatus.ERROR:
            failure_reasons.extend(
                github_result.errors or ["GitHub PR validation could not be completed."]
            )
        elif github_result.status == ValidationStatus.FAIL:
            failure_reasons.extend(github_result.errors)

        if jira_result is not None:
            if jira_result.status == ValidationStatus.ERROR:
                failure_reasons.extend(
                    jira_result.errors or ["Jira validation could not be completed."]
                )
            elif jira_result.status == ValidationStatus.FAIL:
                failure_reasons.extend(jira_result.errors)

        if qa_result.status == ValidationStatus.ERROR:
            failure_reasons.extend(qa_result.errors or ["QA validation could not be completed."])
        elif qa_result.status == ValidationStatus.FAIL:
            failure_reasons.extend(qa_result.errors)

        if (
            github_result.status == ValidationStatus.ERROR
            or (jira_result is not None and jira_result.status == ValidationStatus.ERROR)
            or qa_result.status == ValidationStatus.ERROR
        ):
            logger.info("[ORCHESTRATOR] Overall validation: ERROR")
            return OverallValidationStatus.ERROR, failure_reasons

        jira_ok = jira_result is None or jira_result.status == ValidationStatus.PASS
        if (
            github_result.status == ValidationStatus.PASS
            and jira_ok
            and qa_result.status == ValidationStatus.PASS
        ):
            logger.info("[ORCHESTRATOR] Overall validation: PASS")
            return OverallValidationStatus.PASS, failure_reasons

        logger.info("[ORCHESTRATOR] Overall validation: FAIL")
        return OverallValidationStatus.FAIL, failure_reasons

    def determine_workflow_status(
        self,
        overall_status: OverallValidationStatus,
    ) -> WorkflowStatus:
        if overall_status == OverallValidationStatus.PASS:
            return WorkflowStatus.L3_APPROVAL_PENDING
        if overall_status == OverallValidationStatus.ERROR:
            return WorkflowStatus.VALIDATION_ERROR
        return WorkflowStatus.HALTED

    def build_failure_comment(
        self,
        state: ReleaseState,
        github_result: GitHubValidationResult,
        jira_result: JiraValidationResult | None,
        qa_result: QAValidationResult,
        failure_reasons: list[str],
    ) -> str:
        github_label = self._validation_label(github_result.status)
        jira_label = (
            "SKIPPED"
            if jira_result is None
            else self._validation_label(jira_result.status)
        )
        qa_label = self._validation_label(qa_result.status)

        failed_checks = "\n".join(f"* {reason}" for reason in failure_reasons) or "* Unknown failure"
        source_branch = github_result.metadata.get("source_branch", "unknown")
        target_branch = github_result.metadata.get("target_branch", "unknown")
        raised_by = github_result.metadata.get("raised_by", "unknown")
        pr_number = github_result.metadata.get("pull_number", state["github_pr_number"])
        body = (
            "Release Validation Failed\n\n"
            f"Release Branch: {state['release_branch']}\n"
            f"Environment: {state['environment']}\n"
            f"GitHub PR: #{pr_number}\n"
            f"GitHub PR Raised By: {raised_by}\n"
            f"GitHub PR Source Branch: {source_branch}\n"
            f"GitHub PR Target Branch: {target_branch}\n\n"
            f"GitHub PR Validation: {github_label}\n"
            f"Jira Validation: {jira_label}\n"
            f"QA Validation: {qa_label}\n\n"
            "Failed Checks:\n\n"
            f"{failed_checks}\n\n"
            "Release workflow has been HALTED.\n\n"
            "L3 approval will not be triggered."
        )
        lane2 = (qa_result.metadata or {}).get("lane2_comment")
        if isinstance(lane2, str) and lane2.strip():
            body = f"{body}\n\n{lane2.strip()}"
        return body

    async def post_github_failure_comment(
        self,
        state: ReleaseState,
        comment_body: str,
        *,
        ctx: WorkflowRunContext | None = None,
    ) -> bool:
        logger.info("[GITHUB_MCP] Posting validation failure comment")
        try:
            async with self._get_github_client() as client:
                await client.add_pull_request_comment(
                    owner=state["github_owner"],
                    repo=state["github_repo"],
                    pull_number=state["github_pr_number"],
                    body=comment_body,
                )
            logger.info("[GITHUB_MCP] Comment posted successfully")
            return True
        except MCPConnectionError as exc:
            logger.error("[GITHUB_MCP] Failed to post comment: %s", exc)
            return False
        except Exception as exc:
            logger.exception("[GITHUB_MCP] Unexpected comment failure")
            logger.error("[GITHUB_MCP] Failed to post comment: %s", exc)
            return False

    def _get_github_client(self) -> GitHubMCPClient | _ManagedExistingGitHubClient:
        if self._github_client is not None:
            return _ManagedExistingGitHubClient(self._github_client)
        return GitHubMCPClient()

    @staticmethod
    def _github_result(
        checks: GitHubChecks,
        errors: list[str],
        metadata: dict,
        status: ValidationStatus,
    ) -> GitHubValidationResult:
        result = GitHubValidationResult(
            status=status,
            checks=checks,
            errors=errors,
            metadata=metadata,
        )
        logger.info("[ORCHESTRATOR] GitHub validation result: %s", status.value)
        return result

    @staticmethod
    def _validation_label(status: ValidationStatus) -> str:
        if status == ValidationStatus.PASS:
            return "PASS"
        if status == ValidationStatus.ERROR:
            return "ERROR"
        return "FAIL"


def _metadata_str(metadata: dict | None, key: str) -> str | None:
    if not metadata:
        return None
    value = metadata.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


class _ManagedExistingGitHubClient:
    def __init__(self, client: GitHubMCPClient) -> None:
        self.client = client

    async def __aenter__(self) -> GitHubMCPClient:
        if not self.client.tool_names:
            await self.client.connect()
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None
