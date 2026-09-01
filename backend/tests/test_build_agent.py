"""Tests for Build Agent."""

from datetime import datetime, timezone
from unittest.mock import AsyncMock

from app.agents.build_agent import BuildAgent
from app.config import Settings
from app.models.build_result import BuildResult, BuildStatus


async def test_build_agent_generates_stub_build_id():
    agent = BuildAgent(Settings(CI_PROVIDER="stub"))
    state = {
        "release_id": "REL-TEST1234",
        "release_version": "v2.4.0",
        "environment": "UAT",
    }

    result = await agent.generate_build(state)

    assert result.build_id.startswith("BUILD-")
    assert result.status.value == "COMPLETED"
    assert result.release_version == "v2.4.0"
    assert result.target_environment == "UAT"
    assert result.generated_at is not None


async def test_build_agent_uses_github_actions_client():
    actions_client = AsyncMock()
    actions_client.run_release_build.return_value = BuildResult(
        build_id="GHA-99",
        status=BuildStatus.COMPLETED,
        generated_at=datetime.now(timezone.utc),
        release_version="v2.4.0",
        target_environment="UAT",
        job_url="https://github.com/acme/app/actions/runs/99",
        commit_sha="abc1234",
        external_run_id="99",
    )
    agent = BuildAgent(
        Settings(CI_PROVIDER="github_actions"),
        actions_client=actions_client,
    )
    state = {
        "release_id": "REL-TEST1234",
        "release_version": "v2.4.0",
        "environment": "UAT",
        "github_owner": "acme",
        "github_repo": "app",
        "merge_result": {"merge_sha": "abc1234"},
    }

    result = await agent.generate_build(state)

    assert result.build_id == "GHA-99"
    assert result.status == BuildStatus.COMPLETED
    actions_client.run_release_build.assert_awaited_once()
    actions_client.aclose.assert_not_called()


async def test_build_agent_falls_back_to_stub_when_workflow_missing():
    actions_client = AsyncMock()
    actions_client.run_release_build.return_value = BuildResult(
        build_id="GHA-failed",
        status=BuildStatus.FAILED,
        generated_at=datetime.now(timezone.utc),
        release_version="v2.4.0",
        target_environment="UAT",
        commit_sha="abc1234",
        failure_reason=(
            "No GitHub Actions workflow 'release-build.yml' in acme/app, "
            "and no run exists for commit abc1234."
        ),
    )
    agent = BuildAgent(
        Settings(CI_PROVIDER="github_actions", CI_FALLBACK_TO_STUB=True),
        actions_client=actions_client,
    )
    state = {
        "release_id": "REL-TEST1234",
        "release_version": "v2.4.0",
        "environment": "UAT",
    }

    result = await agent.generate_build(state)

    assert result.build_id.startswith("BUILD-")
    assert result.status == BuildStatus.COMPLETED
    assert result.workflow_name == "stub-fallback"
    assert result.commit_sha == "abc1234"
