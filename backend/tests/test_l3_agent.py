"""L3 agent tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from datetime import date

from app.agents.l3_agent import L3Agent
from app.models.risk_score import ReleaseRiskScore


@pytest.fixture
def l3_state():
    return {
        "release_id": "REL-L3-001",
        "release_branch": "feature/SCRUM-6-offerings",
        "release_version": "feature/SCRUM-6-offerings",
        "github_pr_url": "https://github.com/example/repo/pull/11",
        "github_pr_number": 11,
        "jira_url": "https://example.atlassian.net/browse/SCRUM-6",
        "jira_issue_key": "SCRUM-6",
        "qa_signoff_required": False,
        "environment": "UAT",
        "release_date": date(2026, 8, 18),
        "created_by": "dev1",
    }


@pytest.mark.asyncio
async def test_l3_agent_uses_llm_summary_in_mail(l3_state):
    summary_service = MagicMock()
    summary_service.generate_summary = AsyncMock(
        return_value="- Fix Offerings dropdown navigation.\n- Validated by QA."
    )
    settings = MagicMock()
    settings.portal_base_url = "http://localhost:5173"
    settings.l3_manager_emails = ["l3@example.com"]

    agent = L3Agent(settings=settings, summary_service=summary_service)
    github_validation = {
        "metadata": {
            "pr_title": "Implement SCRUM-6 offerings",
            "pr_description": "Raw PR description should not appear directly.",
            "comments": [{"author": "qa", "body": "Looks good"}],
        }
    }
    jira_validation = {"metadata": {"jira_description": "Raw jira description"}}

    approval_request, mail_draft = await agent.create_approval_request(
        l3_state,
        github_validation=github_validation,
        jira_validation=jira_validation,
    )

    summary_service.generate_summary.assert_awaited_once()
    assert "Fix Offerings dropdown navigation" in mail_draft.body_text
    assert "Raw PR description should not appear directly" not in mail_draft.body_text
    assert approval_request.release_id == "REL-L3-001"


@pytest.mark.asyncio
async def test_l3_agent_includes_risk_score_in_mail(l3_state):
    summary_service = MagicMock()
    summary_service.generate_summary = AsyncMock(return_value="Summary text.")
    settings = MagicMock()
    settings.portal_base_url = "http://localhost:5173"
    settings.l3_manager_emails = ["l3@example.com"]

    risk_score = ReleaseRiskScore(
        score=0.44,
        level="MEDIUM",
        breakdown={
            "file_count_score": 0.25,
            "lines_changed_score": 0.55,
            "failure_rate_score": 0.46,
        },
        metrics={
            "files_changed": 5,
            "lines_added": 400,
            "lines_deleted": 150,
            "lines_changed": 550,
            "file_count_limit": 20,
            "lines_changed_limit": 1000,
            "file_count_weight": 0.25,
            "lines_changed_weight": 0.35,
            "failure_rate_weight": 0.40,
        },
        high_risk_files=[
            {
                "filepath": "src/payments/processor.py",
                "failure_rate": 0.72,
                "lines_changed": 295,
            }
        ],
    )

    agent = L3Agent(settings=settings, summary_service=summary_service)
    approval_request, mail_draft = await agent.create_approval_request(
        l3_state,
        github_validation={"metadata": {"pr_title": "Test PR"}},
        risk_score=risk_score,
    )

    assert approval_request.risk_score is not None
    assert approval_request.risk_score.level == "MEDIUM"
    assert "Risk Score\t0.44" in mail_draft.body_text
    assert "Risk Level\tMEDIUM" in mail_draft.body_text
    assert "Risk Reason\t" in mail_draft.body_text
    assert "Classified as MEDIUM risk." in mail_draft.body_text
    assert (
        "This release touches 5 files and changes 550 lines of code "
        "(400 added, 150 removed)" in mail_draft.body_text
    )
    assert "review limits of 20 files and 1,000 lines" in mail_draft.body_text
    assert "this code has failed in 46% of earlier releases" in mail_draft.body_text
    assert "biggest contributor to this level" not in mail_draft.body_text
    assert "src/payments/processor.py (failed in 72% of past releases" in mail_draft.body_text
    assert "Risk Reason" in mail_draft.body_html


@pytest.mark.asyncio
async def test_l3_agent_update_jira_ticket_status(l3_state):
    settings = MagicMock()
    settings.jira_l3_approved_status = "Released"
    jira_service = MagicMock()
    jira_service.transition_to_status = AsyncMock(return_value=True)

    agent = L3Agent(settings=settings)
    with patch("app.agents.l3_agent.JiraWorkflowService", return_value=jira_service):
        with patch("app.agents.l3_agent.emit_workflow_event") as emit_event:
            result = await agent.update_jira_ticket_status(
                issue_key="SCRUM-6",
                release_id=l3_state["release_id"],
                low_risk=True,
            )

    assert result is True
    jira_service.transition_to_status.assert_awaited_once_with("SCRUM-6", "Released")
    assert emit_event.call_count == 2
    started_call = emit_event.call_args_list[0].kwargs
    completed_call = emit_event.call_args_list[1].kwargs
    assert started_call["agent"].value == "l3"
    assert started_call["phase"].value == "started"
    assert "Transitioning Jira ticket SCRUM-6 to Released" in started_call["message"]
    assert started_call["metadata"]["low_risk_auto_approval"] is True
    assert completed_call["agent"].value == "l3"
    assert completed_call["phase"].value == "completed"
    assert "transitioned to Released" in completed_call["message"]


@pytest.mark.asyncio
async def test_l3_agent_skips_jira_when_issue_key_missing(l3_state):
    settings = MagicMock()
    settings.jira_l3_approved_status = "Released"
    jira_service = MagicMock()
    jira_service.transition_to_status = AsyncMock(return_value=True)

    agent = L3Agent(settings=settings)
    with patch("app.agents.l3_agent.JiraWorkflowService", return_value=jira_service):
        with patch("app.agents.l3_agent.emit_workflow_event") as emit_event:
            result = await agent.update_jira_ticket_status(
                issue_key="",
                release_id=l3_state["release_id"],
                low_risk=True,
            )

    assert result is True
    jira_service.transition_to_status.assert_not_awaited()
    emit_event.assert_called_once()
    skip_call = emit_event.call_args.kwargs
    assert skip_call["agent"].value == "l3"
    assert skip_call["phase"].value == "info"
    assert "Jira status update skipped" in skip_call["message"]


@pytest.mark.asyncio
async def test_l3_agent_low_risk_merged_notification_mail(l3_state):
    summary_service = MagicMock()
    summary_service.generate_summary = AsyncMock(return_value="Summary text.")
    settings = MagicMock()
    settings.portal_base_url = "http://localhost:5173"
    settings.l3_manager_emails = ["l3@example.com"]

    risk_score = ReleaseRiskScore(
        score=0.12,
        level="LOW",
        breakdown={
            "file_count_score": 0.05,
            "lines_changed_score": 0.10,
            "failure_rate_score": 0.0,
        },
        metrics={
            "files_changed": 1,
            "lines_added": 70,
            "lines_deleted": 30,
            "lines_changed": 100,
            "file_count_limit": 20,
            "lines_changed_limit": 1000,
            "file_count_weight": 0.25,
            "lines_changed_weight": 0.35,
            "failure_rate_weight": 0.40,
        },
        high_risk_files=[],
    )

    agent = L3Agent(settings=settings, summary_service=summary_service)
    approval_request, mail_draft = await agent.create_low_risk_merged_notification(
        l3_state,
        github_validation={"metadata": {"pr_title": "Test PR"}},
        risk_score=risk_score,
    )

    assert approval_request.status.value == "APPROVED"
    assert approval_request.approved_by == "Release Automation (Low Risk)"
    assert "PR Merged — Release: REL-L3-001" in mail_draft.subject
    assert "Approval URL" not in mail_draft.body_text
    assert "Open L3 Approval Page" not in mail_draft.body_html
    assert "The pull request has been merged" in mail_draft.body_text
    assert "Risk Score\t0.12" in mail_draft.body_text
    assert "Risk Level\tLOW" in mail_draft.body_text
    assert "Classified as LOW risk." in mail_draft.body_text
    assert (
        "This release touches 1 file and changes 100 lines of code "
        "(70 added, 30 removed)" in mail_draft.body_text
    )
    assert "None of the changed files have failed in earlier releases." in mail_draft.body_text
    assert "biggest contributor to this level" not in mail_draft.body_text
