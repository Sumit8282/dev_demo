"""Deterministic Jira workflow updates (transitions and comments) via MCP."""

from __future__ import annotations

import logging

from app.config import Settings, get_settings
from app.mcp.jira_mcp import JiraMCPClient, find_transition_id_for_status
from app.services.workflow_events import emit_workflow_event
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase

logger = logging.getLogger(__name__)


class JiraWorkflowService:
    """Apply Jira ticket lifecycle updates at key release milestones."""

    def __init__(
        self,
        settings: Settings | None = None,
        jira_client: JiraMCPClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._jira_client = jira_client

    async def transition_to_status(self, issue_key: str, target_status: str) -> bool:
        target = target_status.strip()
        if not target:
            logger.warning("[JIRA_WORKFLOW] Empty target status for %s", issue_key)
            return False

        async def _run(client: JiraMCPClient) -> bool:
            transitions = await client.get_transitions(issue_key)
            transition_id = find_transition_id_for_status(transitions, target)
            if not transition_id:
                available = [
                    (t.get("name"), (t.get("to") or {}).get("name") if isinstance(t.get("to"), dict) else None)
                    for t in transitions
                ]
                logger.warning(
                    "[JIRA_WORKFLOW] No transition to '%s' for %s (available: %s)",
                    target,
                    issue_key,
                    available,
                )
                return False
            await client.transition_issue(issue_key, transition_id)
            logger.info(
                "[JIRA_WORKFLOW] Transitioned %s to %s (transition %s)",
                issue_key,
                target,
                transition_id,
            )
            return True

        return await self._with_client(_run)

    async def add_comment(self, issue_key: str, body: str) -> bool:
        comment = body.strip()
        if not comment:
            return False

        async def _run(client: JiraMCPClient) -> bool:
            await client.add_comment(issue_key, comment)
            logger.info("[JIRA_WORKFLOW] Comment added on %s", issue_key)
            return True

        return await self._with_client(_run)

    async def on_build_completed(
        self,
        *,
        issue_key: str,
        release_id: str,
        build_id: str,
        environment: str,
    ) -> bool:
        comment = (
            f"Release build generated.\n"
            f"Build ID: {build_id}\n"
            f"Target environment: {environment}\n"
            f"Release ID: {release_id}"
        )
        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.JIRA,
            phase=WorkflowEventPhase.STARTED,
            message=f"Adding build comment on Jira ticket {issue_key}",
            metadata={"build_id": build_id},
        )
        try:
            posted = await self.add_comment(issue_key, comment)
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.COMPLETED if posted else WorkflowEventPhase.ERROR,
                message=(
                    f"Build ID {build_id} commented on Jira ticket {issue_key}"
                    if posted
                    else f"Failed to add build comment on Jira ticket {issue_key}"
                ),
                metadata={"build_id": build_id},
            )
            return posted
        except Exception:
            logger.exception(
                "[JIRA_WORKFLOW] Build comment failed for %s", issue_key
            )
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.JIRA,
                phase=WorkflowEventPhase.ERROR,
                message=f"Failed to add build comment on Jira ticket {issue_key}",
                metadata={"build_id": build_id},
            )
            return False

    async def on_deployment_completed(
        self,
        *,
        issue_key: str,
        release_id: str,
        environment: str,
        build_id: str | None = None,
    ) -> bool:
        target_status = self.settings.jira_deployment_completed_status
        comment_lines = [
            "Deployment completed successfully.",
            f"Environment: {environment}",
            f"Release ID: {release_id}",
        ]
        if build_id:
            comment_lines.insert(1, f"Build ID: {build_id}")
        comment = "\n".join(comment_lines)

        emit_workflow_event(
            release_id,
            agent=WorkflowEventAgent.DEPLOY,
            phase=WorkflowEventPhase.STARTED,
            message=f"Updating Jira ticket {issue_key} to {target_status} after deployment",
        )
        transitioned = False
        commented = False
        try:
            transitioned = await self.transition_to_status(issue_key, target_status)
            commented = await self.add_comment(issue_key, comment)
            success = transitioned and commented
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.DEPLOY,
                phase=WorkflowEventPhase.COMPLETED if success else WorkflowEventPhase.ERROR,
                message=(
                    f"Jira ticket {issue_key} updated to {target_status} after deployment"
                    if success
                    else f"Partial Jira update for {issue_key} (transition={transitioned}, comment={commented})"
                ),
                metadata={
                    "environment": environment,
                    "build_id": build_id,
                    "target_status": target_status,
                },
            )
            return success
        except Exception:
            logger.exception(
                "[JIRA_WORKFLOW] Deployment completion failed for %s", issue_key
            )
            emit_workflow_event(
                release_id,
                agent=WorkflowEventAgent.DEPLOY,
                phase=WorkflowEventPhase.ERROR,
                message=f"Failed to update Jira ticket {issue_key} to {target_status} after deployment",
            )
            return False

    async def _with_client(self, operation) -> bool:
        if self._jira_client is not None:
            if not self._jira_client.tool_names:
                await self._jira_client.connect()
            return await operation(self._jira_client)

        async with JiraMCPClient(self.settings) as client:
            return await operation(client)
