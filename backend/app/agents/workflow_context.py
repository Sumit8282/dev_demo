"""Mutable context shared by orchestrator LLM tools during a workflow run."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.models.validation import (
    GitHubValidationResult,
    JiraValidationResult,
    QAValidationResult,
)
from app.models.workflow_event import WorkflowEventAgent, WorkflowEventPhase
from app.services.workflow_events import make_workflow_event, persist_workflow_event
from app.workflow.state import ReleaseState


@dataclass
class WorkflowRunContext:
    state: ReleaseState
    github_validation: GitHubValidationResult | None = None
    jira_validation: JiraValidationResult | None = None
    qa_validation: QAValidationResult | None = None
    l3_flow: dict[str, Any] | None = None
    github_comment_posted: bool = False
    github_comment_attempted: bool = False
    llm_summary: str = ""
    tool_calls: list[str] = field(default_factory=list)
    workflow_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def release_id(self) -> str:
        return self.state["release_id"]

    def emit(
        self,
        *,
        agent: str | WorkflowEventAgent,
        phase: str | WorkflowEventPhase,
        message: str,
        metadata: dict[str, Any] | None = None,
        simulated: bool = False,
    ) -> dict[str, Any]:
        event = make_workflow_event(
            agent=agent,
            phase=phase,
            message=message,
            metadata=metadata,
            simulated=simulated,
        )
        self.workflow_events.append(event)
        persist_workflow_event(self.release_id, event)
        return event
