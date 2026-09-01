"""Tests for deployment completion API and Jira hooks."""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.release import WorkflowStatus
from app.services.release_store import release_store

client = TestClient(app)


def _base_state(**overrides):
    state = {
        "release_id": "REL-DEPLOY01",
        "release_branch": "release/v2.4.0",
        "release_version": "v2.4.0",
        "github_pr_url": "https://github.com/company/repository/pull/123",
        "github_owner": "company",
        "github_repo": "repository",
        "github_pr_number": 123,
        "jira_url": "https://company.atlassian.net/browse/SCRUM-6",
        "jira_issue_key": "SCRUM-6",
        "qa_signoff_required": False,
        "qa_signoff_not_required_reason": "Not required",
        "environment": "UAT2",
        "release_date": date(2026, 8, 15),
        "workflow_status": WorkflowStatus.RM_APPROVED.value,
        "build_result": {"build_id": "BUILD-20260817-001", "status": "COMPLETED"},
        "failure_reasons": [],
        "github_comment_posted": False,
        "workflow_events": [],
    }
    state.update(overrides)
    return state


@pytest.fixture(autouse=True)
def clear_store():
    release_store.clear_all()
    yield
    release_store.clear_all()


def _seed_release(**overrides):
    state = _base_state(**overrides)
    release_id = state["release_id"]
    release_store.create(state)
    release_store.update(
        release_id,
        {
            "workflow_status": state.get("workflow_status", WorkflowStatus.RM_APPROVED.value),
            "build_result": state.get("build_result"),
        },
    )
    return release_id


def test_deployment_complete_requires_rm_approved():
    release_id = _seed_release(workflow_status=WorkflowStatus.RM_APPROVAL_PENDING.value)

    response = client.post(f"/api/releases/{release_id}/deployment/complete")

    assert response.status_code == 409


def test_deployment_complete_updates_status_and_queues_jira():
    release_id = _seed_release()

    with patch(
        "app.api.release_routes._jira_on_deployment_completed",
        new=AsyncMock(),
    ) as jira_mock:
        response = client.post(f"/api/releases/{release_id}/deployment/complete")

    assert response.status_code == 200
    body = response.json()
    assert body["workflow_status"] == WorkflowStatus.DEPLOYMENT_COMPLETED.value
    jira_mock.assert_called_once_with(release_id)
