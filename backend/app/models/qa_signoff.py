"""QA sign-off document models (ported from backend 7)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class SignOffRequest(BaseModel):
    pr_title: str = Field(..., description="GitHub pull request title")
    test_plan_status: str = Field(
        ...,
        description="QA test plan status. Expected: Passed or Failed",
    )
    open_blocker_or_critical_bugs: bool = Field(
        ...,
        description="True if any blocker or critical bug is open against this PR",
    )
    pr_tags: list[str] = Field(default_factory=list)
    summary: str | None = Field(default=None, description="Optional test summary or notes.")


class SignOffResponse(BaseModel):
    approved: bool
    message: str
    reason: str
    pr_tags: list[str]
