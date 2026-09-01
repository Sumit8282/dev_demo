"""Helpers for persisting workflow activity events."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.models.workflow_event import WorkflowEvent, WorkflowEventAgent, WorkflowEventPhase
from app.services.release_store import release_store


def make_workflow_event(
    *,
    agent: str | WorkflowEventAgent,
    phase: str | WorkflowEventPhase,
    message: str,
    metadata: dict[str, Any] | None = None,
    simulated: bool = False,
    timestamp: datetime | None = None,
) -> dict[str, Any]:
    event = WorkflowEvent(
        timestamp=timestamp or datetime.now(timezone.utc),
        agent=agent.value if isinstance(agent, WorkflowEventAgent) else agent,
        phase=phase.value if isinstance(phase, WorkflowEventPhase) else phase,
        message=message,
        metadata=metadata or {},
        simulated=simulated,
    )
    return event.model_dump(mode="json")


def persist_workflow_event(release_id: str, event: dict[str, Any]) -> None:
    release_store.append_event(release_id, event)


def emit_workflow_event(
    release_id: str,
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
    persist_workflow_event(release_id, event)
    return event
