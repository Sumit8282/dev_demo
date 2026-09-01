"""Helpers to simulate LLM orchestrator tool runs in tests."""

from __future__ import annotations

from app.agents.tools.orchestrator_tools import run_orchestrator_tool_sequence
from app.agents.workflow_context import WorkflowRunContext


async def simulate_orchestrator_tool_run(ctx: WorkflowRunContext, orchestrator) -> None:
    """Run validation tools in standard order (simulates LLM orchestrator in tests)."""
    await run_orchestrator_tool_sequence(orchestrator, ctx)
