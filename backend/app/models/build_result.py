"""Build generation result model."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class BuildStatus(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class BuildResult(BaseModel):
    build_id: str
    status: BuildStatus = BuildStatus.COMPLETED
    generated_at: datetime
    release_version: str
    target_environment: str
    job_url: str | None = None
    logs_url: str | None = None
    commit_sha: str | None = None
    external_run_id: str | None = None
    failure_reason: str | None = None
    workflow_name: str | None = None
