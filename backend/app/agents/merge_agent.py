"""Auto-merge agent — LangChain agent that merges the GitHub PR after L3 approval."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from langchain.tools import tool
from langchain_core.language_models.chat_models import BaseChatModel

from app.agents.llm_runner import create_langchain_agent, invoke_langchain_agent
from app.config import Settings, get_settings
from app.mcp.client_base import MCPConnectionError, MCPToolNotFoundError
from app.mcp.github_mcp import GitHubMCPClient
from app.models.l3_approval import L3ApprovalStatus
from app.models.release import WorkflowStatus, jira_required
from app.models.validation import (
    JiraValidationResult,
    MergeChecks,
    MergeResult,
    MergeResultStatus,
    ValidationStatus,
)
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.prompts import format_prompt, load_prompt
from app.services.workflow_events import emit_workflow_event
from app.utils.github_fields import (
    extract_pr_mergeable,
    extract_pr_merged,
    extract_pr_state,
    pr_exists,
)
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)

DEFAULT_MERGE_METHOD = "squash"


@dataclass
class _MergeAgentRun:
    state: ReleaseState
    result: MergeResult | None = None


class MergeAgent:
    """LangChain agent that validates pre-merge gates and merges the PR using GitHub MCP."""

    def __init__(
        self,
        settings: Settings | None = None,
        github_client: GitHubMCPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._github_client = github_client

    def build_langchain_agent(self, run: _MergeAgentRun | None = None, llm: BaseChatModel | None = None):
        """Build the merge LangChain agent with a GitHub merge tool."""
        run = run or _MergeAgentRun(state={})  # type: ignore[typeddict-item]

        @tool
        async def execute_github_pr_merge() -> dict:
            """Validate L3/Jira/PR gates and squash-merge the GitHub pull request."""
            result = await self._execute_merge_impl(run.state)
            run.result = result
            return result.model_dump(mode="json")

        return create_langchain_agent(
            settings=self.settings,
            tools=[execute_github_pr_merge],
            system_prompt=load_prompt("merge_agent_system"),
            name="merge_agent",
            llm=llm,
        )

    async def execute_merge(self, state: ReleaseState) -> MergeResult:
        """Run the merge LangChain agent, falling back to the merge tool implementation."""
        run = _MergeAgentRun(state=state)
        agent = self.build_langchain_agent(run)
        if agent is not None:
            await invoke_langchain_agent(
                agent,
                user_message=format_prompt(
                    "merge_agent_user",
                    release_id=state["release_id"],
                    github_pr_number=state["github_pr_number"],
                    github_owner=state["github_owner"],
                    github_repo=state["github_repo"],
                    jira_issue_key=state["jira_issue_key"],
                ),
            )
            if run.result is not None:
                return run.result
        return await self._execute_merge_impl(state)

    async def _execute_merge_impl(self, state: ReleaseState) -> MergeResult:
        """Run pre-merge validation and merge the PR when all gates pass."""
        release_id = state["release_id"]
        owner = state["github_owner"]
        repo = state["github_repo"]
        pull_number = state["github_pr_number"]
        github_pr_url = state["github_pr_url"]
        started_at = datetime.now(timezone.utc)
        merge_method = DEFAULT_MERGE_METHOD

        checks = MergeChecks()
        errors: list[str] = []
        metadata: dict[str, Any] = {
            "github_pr_url": github_pr_url,
            "owner": owner,
            "repo": repo,
            "pull_number": int(pull_number),
            "merge_method": merge_method,
            "started_at": started_at.isoformat(),
        }

        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.MERGE,
            phase=WorkflowEventPhase.STARTED,
            message=f"Auto-merge started for PR #{pull_number}",
            metadata={"github_pr_url": github_pr_url},
        )

        l3_ok, l3_errors = self._validate_l3_approval(state)
        checks.l3_approved = l3_ok
        if l3_ok:
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.CHECK,
                message="L3 approval status is APPROVED — PASS",
                metadata={"check": "l3_approved", "passed": True},
            )
        else:
            for error in l3_errors:
                emit_workflow_event(
                    release_id,
                    agent=WorkflowEventAgent.MERGE,
                    phase=WorkflowEventPhase.ERROR,
                    message=error if "auto merge failed" in error.lower() else f"{error} — auto merge failed",
                    metadata={"check": "l3_approved", "passed": False},
                )
            errors.extend(l3_errors)

        jira_ok, jira_errors = self._validate_jira_pass(state)
        checks.jira_validation_pass = jira_ok
        if jira_ok:
            github_issues_mode = not jira_required(state.get("qa_mode"))
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.CHECK,
                message=(
                    "GitHub issues evidence is PASS — PASS"
                    if github_issues_mode
                    else "Jira validation is PASS — PASS"
                ),
                metadata={
                    "check": (
                        "github_issues_evidence"
                        if github_issues_mode
                        else "jira_validation_pass"
                    ),
                    "passed": True,
                },
            )
        else:
            for error in jira_errors:
                emit_workflow_event(
                    release_id,
                    agent=WorkflowEventAgent.MERGE,
                    phase=WorkflowEventPhase.ERROR,
                    message=error if "auto merge failed" in error.lower() else f"{error} — auto merge failed",
                    metadata={"check": "jira_validation_pass", "passed": False},
                )
            errors.extend(jira_errors)

        if errors:
            return self._validation_failed(release_id, checks, errors, metadata, started_at=started_at)

        try:
            async with self._get_github_client() as client:
                pr_data = await client.get_pull_request(owner, repo, int(pull_number))
                metadata["mcp_read_tool"] = client.get_pull_request_tool_name()

                pr_ok, pr_errors = self._validate_pr_state(
                    pr_data,
                    checks,
                    release_id=release_id,
                    pull_number=int(pull_number),
                )
                if not pr_ok:
                    errors.extend(pr_errors)
                    return self._validation_failed(
                        release_id, checks, errors, metadata, started_at=started_at
                    )

                emit_workflow_event(
                    release_id,
                    agent=WorkflowEventAgent.MERGE,
                    phase=WorkflowEventPhase.CHECK,
                    message=f"Pre-merge validation passed — squash merging PR #{pull_number}",
                    metadata={"pull_number": pull_number, "merge_method": merge_method},
                )

                merge_payload = await client.merge_pull_request(
                    owner,
                    repo,
                    int(pull_number),
                    merge_method=merge_method,
                )
                metadata["mcp_merge_tool"] = client.get_merge_pull_request_tool_name()
                metadata["merge_response"] = merge_payload

                merge_sha = _extract_merge_sha(merge_payload)
                if merge_sha:
                    metadata["merge_sha"] = merge_sha

                merged_flag = _extract_merged_flag(merge_payload)
                if merged_flag is False:
                    message = _extract_merge_message(merge_payload) or "GitHub merge request failed."
                    return self._merge_failed(
                        release_id,
                        checks,
                        [f"Auto merge failed: {message}"],
                        metadata,
                        merge_sha=merge_sha,
                        started_at=started_at,
                        merge_method=merge_method,
                    )

                merged_at = datetime.now(timezone.utc)
                metadata["merged_at"] = merged_at.isoformat()
                result = MergeResult(
                    status=MergeResultStatus.MERGED,
                    merged=True,
                    checks=checks,
                    merge_sha=merge_sha,
                    merge_method=merge_method,
                    started_at=started_at,
                    merged_at=merged_at,
                    metadata=metadata,
                )
                emit_workflow_event(
                    release_id,
                    agent=WorkflowEventAgent.MERGE,
                    phase=WorkflowEventPhase.COMPLETED,
                    message=f"PR #{pull_number} squash-merged successfully",
                    metadata={
                        "merge_sha": merge_sha,
                        "github_pr_url": github_pr_url,
                        "merge_method": merge_method,
                        "merged_at": merged_at.isoformat(),
                    },
                )
                logger.info("[MERGE_AGENT] PR %s/%s#%s merged for release %s", owner, repo, pull_number, release_id)
                return result

        except (MCPConnectionError, MCPToolNotFoundError) as exc:
            logger.error("[MERGE_AGENT] GitHub MCP error: %s", exc)
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.ERROR,
                message=f"Auto merge failed: {exc}",
            )
            return MergeResult(
                status=MergeResultStatus.ERROR,
                merged=False,
                checks=checks,
                errors=[f"Auto merge failed: {exc}"],
                merge_method=merge_method,
                started_at=started_at,
                metadata=metadata,
            )
        except Exception as exc:
            logger.exception("[MERGE_AGENT] Unexpected merge failure for release %s", release_id)
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.ERROR,
                message=f"Auto merge failed: {exc}",
            )
            return MergeResult(
                status=MergeResultStatus.ERROR,
                merged=False,
                checks=checks,
                errors=[f"Auto merge failed: {exc}"],
                merge_method=merge_method,
                started_at=started_at,
                metadata=metadata,
            )

    def _validate_l3_approval(self, state: ReleaseState) -> tuple[bool, list[str]]:
        errors: list[str] = []
        workflow_status = state.get("workflow_status")
        allowed_statuses = {
            WorkflowStatus.L3_APPROVED.value,
            WorkflowStatus.MERGE_PENDING.value,
        }
        if workflow_status not in allowed_statuses:
            errors.append(
                f"Release workflow is not L3 approved "
                f"(current: {workflow_status or 'unknown'})."
            )

        raw = state.get("l3_approval_request")
        if not raw:
            errors.append("L3 approval request is missing.")
            return False, errors

        status = raw.get("status") if isinstance(raw, dict) else None
        approved_values = {L3ApprovalStatus.APPROVED.value, L3ApprovalStatus.APPROVED}
        if status not in approved_values:
            errors.append(f"L3 approval status is not APPROVED (current: {status or 'unknown'}).")

        if errors:
            return False, errors
        return True, []

    def _validate_jira_pass(self, state: ReleaseState) -> tuple[bool, list[str]]:
        if not jira_required(state.get("qa_mode")):
            return True, []
        raw = state.get("jira_validation")
        if raw is None:
            return False, ["Jira validation result is missing."]

        if isinstance(raw, JiraValidationResult):
            result = raw
        else:
            result = JiraValidationResult.model_validate(raw)

        if result.status == ValidationStatus.PASS:
            return True, []

        return False, [f"Jira validation is not PASS (current: {result.status.value})."]

    def _validate_pr_state(
        self,
        pr_data: dict[str, Any],
        checks: MergeChecks,
        *,
        release_id: str | None = None,
        pull_number: int | None = None,
    ) -> tuple[bool, list[str]]:
        errors: list[str] = []

        if not pr_exists(pr_data):
            errors.append("Pull request does not exist — auto merge failed.")
            self._emit_pr_check_failure(release_id, errors[-1], checks)
            return False, errors

        pr_state = (extract_pr_state(pr_data) or "").lower()
        merged = extract_pr_merged(pr_data)
        mergeable = extract_pr_mergeable(pr_data)

        checks.pr_is_open = pr_state == "open"
        checks.pr_not_closed = pr_state != "closed"
        checks.pr_not_merged = merged is not True
        checks.pr_is_mergeable = mergeable is True

        if merged is True:
            errors.append("PR is already merged — auto merge failed.")
        elif pr_state == "closed":
            errors.append("PR is closed — auto merge failed.")
        elif not checks.pr_is_open:
            errors.append(
                f"PR is not open (state: {pr_state or 'unknown'}) — auto merge failed."
            )
        if mergeable is False:
            errors.append(
                "PR is not mergeable (conflicts or checks may be failing) — auto merge failed."
            )
        elif mergeable is None and pr_state == "open":
            # GitHub sometimes omits mergeable on first fetch; treat open + unmerged as acceptable.
            checks.pr_is_mergeable = True

        if errors:
            for error in errors:
                self._emit_pr_check_failure(release_id, error, checks, pull_number=pull_number)
            return False, errors

        if release_id:
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.MERGE,
                phase=WorkflowEventPhase.CHECK,
                message=(
                    f"PR #{pull_number} is open and mergeable — PASS"
                    if pull_number
                    else "PR is open and mergeable — PASS"
                ),
                metadata={"check": "pr_mergeable", "passed": True},
            )

        return True, []

    def _emit_pr_check_failure(
        self,
        release_id: str | None,
        message: str,
        checks: MergeChecks,
        *,
        pull_number: int | None = None,
    ) -> None:
        if not release_id:
            return
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.MERGE,
            phase=WorkflowEventPhase.ERROR,
            message=message,
            metadata={
                "check": "pr_state",
                "passed": False,
                "pull_number": pull_number,
                "checks": checks.model_dump(),
            },
        )

    def _validation_failed(
        self,
        release_id: str,
        checks: MergeChecks,
        errors: list[str],
        metadata: dict[str, Any],
        *,
        started_at: datetime | None = None,
    ) -> MergeResult:
        summary = _summarize_auto_merge_failure(errors)
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.MERGE,
            phase=WorkflowEventPhase.ERROR,
            message=summary,
            metadata={"checks": checks.model_dump(), "errors": errors},
        )
        logger.warning("[MERGE_AGENT] Pre-merge validation failed for %s: %s", release_id, errors)
        return MergeResult(
            status=MergeResultStatus.VALIDATION_FAILED,
            merged=False,
            checks=checks,
            errors=errors,
            merge_method=DEFAULT_MERGE_METHOD,
            started_at=started_at,
            metadata={**metadata, "failure_summary": summary},
        )

    def _merge_failed(
        self,
        release_id: str,
        checks: MergeChecks,
        errors: list[str],
        metadata: dict[str, Any],
        *,
        merge_sha: str | None = None,
        started_at: datetime | None = None,
        merge_method: str = DEFAULT_MERGE_METHOD,
    ) -> MergeResult:
        summary = _summarize_auto_merge_failure(errors)
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.MERGE,
            phase=WorkflowEventPhase.ERROR,
            message=summary,
            metadata={"errors": errors},
        )
        return MergeResult(
            status=MergeResultStatus.MERGE_FAILED,
            merged=False,
            checks=checks,
            errors=errors,
            merge_sha=merge_sha,
            merge_method=merge_method,
            started_at=started_at,
            metadata={**metadata, "failure_summary": summary},
        )

    def _get_github_client(self) -> GitHubMCPClient | _ManagedExistingGitHubClient:
        if self._github_client is not None:
            return _ManagedExistingGitHubClient(self._github_client)
        return GitHubMCPClient()


class _ManagedExistingGitHubClient:
    def __init__(self, client: GitHubMCPClient) -> None:
        self.client = client

    async def __aenter__(self) -> GitHubMCPClient:
        if not self.client.tool_names:
            await self.client.connect()
        return self.client

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None


def _summarize_auto_merge_failure(errors: list[str]) -> str:
    if not errors:
        return "Auto merge failed."
    if len(errors) == 1:
        return errors[0]
    return f"Auto merge failed: {'; '.join(errors)}"


def _extract_merge_sha(payload: dict[str, Any]) -> str | None:
    for key in ("sha", "merge_sha", "mergeSha"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    raw = payload.get("raw")
    if isinstance(raw, str) and "SHA:" in raw:
        for part in raw.split("\n"):
            if part.strip().startswith("SHA:"):
                return part.split(":", 1)[1].strip()

    return None


def _extract_merged_flag(payload: dict[str, Any]) -> bool | None:
    merged = payload.get("merged")
    if isinstance(merged, bool):
        return merged
    if isinstance(merged, str):
        lowered = merged.strip().lower()
        if lowered in {"true", "false"}:
            return lowered == "true"

    raw = payload.get("raw")
    if isinstance(raw, str):
        lowered = raw.lower()
        if "merged: true" in lowered or "pr merged successfully" in lowered:
            return True
        if "merged: false" in lowered or "error:" in lowered:
            return False

    return True if payload and not payload.get("error") else None


def _extract_merge_message(payload: dict[str, Any]) -> str | None:
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    raw = payload.get("raw")
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    return None
