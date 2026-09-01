"""Tests for RM Approval Agent and notification email."""

from datetime import date, datetime, timezone

import pytest

from app.agents.rm_agent import RMAgent
from app.config import Settings
from app.models.build_result import BuildResult, BuildStatus
from app.models.l3_approval import L3ApprovalStatus
from app.services.rm_mail_service import format_deployment_window


def _sample_state() -> dict:
    return {
        "release_id": "REL-RMTEST01",
        "release_branch": "feature/SCRUM-6-offerings",
        "release_version": "v2.4.0",
        "github_pr_url": "https://github.com/org/repo/pull/1",
        "github_pr_number": 1,
        "jira_url": "https://jira.example.com/browse/SCRUM-6",
        "jira_issue_key": "SCRUM-6",
        "environment": "UAT",
        "release_date": date(2026, 8, 13),
        "created_by": "Gauri Satalkar",
        "github_validation": {"status": "PASS"},
        "jira_validation": {"status": "PASS"},
        "qa_validation": {"status": "PASS"},
        "l3_approval_request": {
            "status": L3ApprovalStatus.APPROVED.value,
            "approved_by": "L3 Manager Name",
        },
        "merge_result": {"status": "MERGED"},
    }


def test_format_deployment_window():
    window = format_deployment_window(date(2026, 8, 13))
    assert window == "2026-08-13 22:00 - 2026-08-14 02:00 UTC"


@pytest.mark.asyncio
async def test_rm_agent_creates_approval_request_and_notification():
    settings = Settings(
        PORTAL_BASE_URL="http://localhost:5173",
        RM_MANAGER_EMAIL="rm.manager@citi.com",
        MAIL_ENABLED=False,
        USE_LLM_AGENTS=False,
    )
    agent = RMAgent(settings=settings)
    state = _sample_state()
    build_result = BuildResult(
        build_id="BUILD-20260813-001",
        status=BuildStatus.COMPLETED,
        generated_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        release_version=state["release_version"],
        target_environment=state["environment"],
    )

    approval_request, notification_draft = await agent.create_approval_request(
        state,
        build_result=build_result,
    )

    assert approval_request.release_id == "REL-RMTEST01"
    assert approval_request.jira_issue_key == "SCRUM-6"
    assert approval_request.github_pr_number == 1
    assert approval_request.build_id == "BUILD-20260813-001"
    assert approval_request.target_environment == "UAT"
    assert approval_request.approval_statuses.github_validation == "PASS"
    assert approval_request.approval_statuses.l3_approval == "APPROVED"
    assert approval_request.approval_statuses.merge == "MERGED"
    assert approval_request.approval_statuses.build == "COMPLETED"
    assert approval_request.deployment_window == "2026-08-13 22:00 - 2026-08-14 02:00 UTC"
    assert approval_request.approval_url == "http://localhost:5173/approvals/rm/REL-RMTEST01"
    assert approval_request.approval_queue_url == "http://localhost:5173/approvals?tab=rm"

    assert notification_draft.to == ["rm.manager@citi.com"]
    assert notification_draft.subject == "RM Approval Required: REL-RMTEST01"
    assert "Hi RM Team" in notification_draft.body_html
    assert "L3 Approved By" in notification_draft.body_html
    assert "L3 Manager Name" in notification_draft.body_html
    assert "Gauri Satalkar" in notification_draft.body_html
    assert notification_draft.metadata["jira_issue_key"] == "SCRUM-6"
    assert notification_draft.metadata["build_id"] == "BUILD-20260813-001"
    assert "BUILD-20260813-001" in notification_draft.body_text
    assert "BUILD-20260813-001" in notification_draft.body_html
    assert notification_draft.metadata["l3_approved_by"] == "L3 Manager Name"
    assert "approvals/rm/REL-RMTEST01" in notification_draft.approval_url
