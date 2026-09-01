"""Workflow activity event models for agentic UI."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class WorkflowEventPhase(str, Enum):
    STARTED = "started"
    CHECK = "check"
    COMPLETED = "completed"
    ERROR = "error"
    INFO = "info"


class WorkflowEventAgent(str, Enum):
    SYSTEM = "system"
    ORCHESTRATOR = "orchestrator"
    GITHUB = "github"  # legacy — prefer ORCHESTRATOR for GitHub PR validation events
    JIRA = "jira"
    QA = "qa"
    L3 = "l3"
    MERGE = "merge"
    BUILD = "build"
    RM = "rm"
    DEPLOY = "deploy"


class WorkflowEvent(BaseModel):
    timestamp: datetime
    agent: str
    phase: str
    message: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    simulated: bool = False
