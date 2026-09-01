"""Post-merge build success and failure routing."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.api.release_routes import _execute_post_merge_workflow
from app.models.build_result import BuildResult, BuildStatus
from app.models.release import WorkflowStatus
from app.services.release_store import release_store


def _seed(release_id: str) -> str:
    release_store.create(
        {
            "release_id": release_id,
            "release_branch": "release/v2.4.0",
            "release_version": "v2.4.0",
            "github_pr_url": "https://github.com/company/repository/pull/123",
            "github_owner": "company",
            "github_repo": "repository",
            "github_pr_number": 123,
            "jira_url": "https://company.atlassian.net/browse/ABC-123",
            "jira_issue_key": "ABC-123",
            "qa_signoff_required": False,
            "qa_signoff_not_required_reason": "Not required",
            "environment": "UAT2",
            "release_date": "2026-08-15",
        }
    )
    release_store.update(
        release_id,
        {
            "workflow_status": WorkflowStatus.MERGED.value,
            "merge_result": {"merge_sha": "abc1234", "merged": True},
        },
    )
    return release_id


@pytest.fixture(autouse=True)
def _isolate_store():
    release_store.clear_all()
    yield
    release_store.clear_all()


async def test_post_merge_failed_build_does_not_create_rm_request():
    release_id = _seed("REL-BUILDFAIL")
    failed = BuildResult(
        build_id="GHA-9",
        status=BuildStatus.FAILED,
        generated_at=datetime.now(timezone.utc),
        release_version="v2.4.0",
        target_environment="UAT2",
        failure_reason="GitHub Actions run 9 completed (failure)",
        job_url="https://github.com/company/repository/actions/runs/9",
    )

    with (
        patch("app.api.release_routes.Orchestrator") as orchestrator_cls,
        patch("app.api.release_routes._jira_on_build_completed", new_callable=AsyncMock) as jira,
    ):
        orchestrator = orchestrator_cls.return_value
        orchestrator.run_build_generation = AsyncMock(
            return_value=failed.model_dump(mode="json")
        )
        orchestrator.run_rm_approval_preparation = AsyncMock()
        await _execute_post_merge_workflow(release_id)

    stored = release_store.get(release_id)
    assert stored["workflow_status"] == WorkflowStatus.BUILD_FAILED.value
    assert stored["build_result"]["build_id"] == "GHA-9"
    assert not stored.get("rm_approval_request")
    orchestrator.run_rm_approval_preparation.assert_not_called()
    jira.assert_not_awaited()


async def test_post_merge_successful_build_requests_rm():
    release_id = _seed("REL-BUILDOK")
    completed = BuildResult(
        build_id="BUILD-20260828-001",
        status=BuildStatus.COMPLETED,
        generated_at=datetime.now(timezone.utc),
        release_version="v2.4.0",
        target_environment="UAT2",
    )

    with (
        patch("app.api.release_routes.Orchestrator") as orchestrator_cls,
        patch("app.api.release_routes._jira_on_build_completed", new_callable=AsyncMock),
    ):
        orchestrator = orchestrator_cls.return_value
        orchestrator.run_build_generation = AsyncMock(
            return_value=completed.model_dump(mode="json")
        )
        orchestrator.run_rm_approval_preparation = AsyncMock(
            return_value=({"approval_url": "http://localhost/approvals/rm/REL-BUILDOK"}, None)
        )
        await _execute_post_merge_workflow(release_id)

    stored = release_store.get(release_id)
    assert stored["workflow_status"] == WorkflowStatus.RM_APPROVAL_PENDING.value
    assert stored["build_result"]["build_id"] == "BUILD-20260828-001"
    orchestrator.run_rm_approval_preparation.assert_awaited_once()
