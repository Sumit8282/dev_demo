"""Tests for the GitHub Actions release-build client."""

from datetime import datetime, timedelta, timezone

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.models.build_result import BuildStatus
from app.services.github_actions_client import GitHubActionsClient, GitHubActionsError


def _settings(**overrides) -> Settings:
    values = {
        "CI_PROVIDER": "github_actions",
        "CI_TRIGGER_MODE": "observe",
        "GITHUB_ACTIONS_WORKFLOW": "release-build.yml",
        "GITHUB_ACTIONS_POLL_INTERVAL_SECONDS": 0,
        "GITHUB_ACTIONS_POLL_TIMEOUT_SECONDS": 2,
        "GITHUB_ACTIONS_DISCOVER_TIMEOUT_SECONDS": 1,
        "GITHUB_PERSONAL_ACCESS_TOKEN": SecretStr("gha_test_token"),
    }
    values.update(overrides)
    return Settings(**values)


def _state(**overrides):
    state = {
        "release_id": "REL-TEST1234",
        "release_branch": "release/v2.4.0",
        "release_version": "v2.4.0",
        "environment": "UAT",
        "github_owner": "acme",
        "github_repo": "app",
        "merge_result": {"merge_sha": "abc1234deadbeef"},
    }
    state.update(overrides)
    return state


def _run(status="completed", conclusion="success", run_id=44, **extra):
    payload = {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "html_url": f"https://github.com/acme/app/actions/runs/{run_id}",
        "logs_url": f"https://api.github.com/repos/acme/app/actions/runs/{run_id}/logs",
        "head_sha": "abc1234deadbeef",
        "name": "Release build",
        "created_at": "2026-08-28T06:00:00Z",
    }
    payload.update(extra)
    return payload


async def test_observe_successful_run():
    calls = {"runs": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/workflows/release-build.yml") and not request.url.path.endswith("/runs"):
            return httpx.Response(200, json={"name": "Release build"})
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            calls["runs"] += 1
            return httpx.Response(200, json={"workflow_runs": [_run(status="in_progress")]})
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run())
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    discovered = []

    async def on_discovered(result):
        discovered.append(result.build_id)

    result = await client.run_release_build(_state(), on_run_discovered=on_discovered)

    assert result.status == BuildStatus.COMPLETED
    assert result.build_id == "GHA-44"
    assert result.job_url.endswith("/actions/runs/44")
    assert result.commit_sha == "abc1234deadbeef"
    assert discovered == ["GHA-44"]
    await client.aclose()


async def test_observe_failed_run():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/workflows/release-build.yml") and not request.url.path.endswith("/runs"):
            return httpx.Response(200, json={"name": "Release build"})
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            return httpx.Response(200, json={"workflow_runs": [_run()]})
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run(conclusion="failure"))
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.FAILED
    assert result.failure_reason
    await client.aclose()


async def test_dispatch_then_poll():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/dispatches"):
            return httpx.Response(204)
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        _run(
                            status="in_progress",
                            created_at=datetime.now(timezone.utc).isoformat(),
                        )
                    ]
                },
            )
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run())
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(CI_TRIGGER_MODE="dispatch"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.COMPLETED
    await client.aclose()


async def test_dispatch_matches_run_created_before_local_clock():
    created = (datetime.now(timezone.utc) - timedelta(seconds=90)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/dispatches"):
            return httpx.Response(204)
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        _run(
                            status="in_progress",
                            created_at=created,
                            event="workflow_dispatch",
                            head_branch="release/v2.4.0",
                        )
                    ]
                },
            )
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run())
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(CI_TRIGGER_MODE="dispatch"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.COMPLETED
    assert result.build_id == "GHA-44"
    await client.aclose()


async def test_dispatch_falls_back_to_push_run():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path.endswith("/dispatches"):
            return httpx.Response(204)
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            return httpx.Response(
                200,
                json={
                    "workflow_runs": [
                        _run(
                            status="in_progress",
                            created_at=datetime.now(timezone.utc).isoformat(),
                            event="push",
                            head_branch="release/v2.4.0",
                        )
                    ]
                },
            )
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run())
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(CI_TRIGGER_MODE="dispatch"),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.COMPLETED
    assert result.build_id == "GHA-44"
    await client.aclose()


async def test_missing_token_fails_cleanly():
    client = GitHubActionsClient(
        _settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("")),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(lambda request: httpx.Response(500))
        ),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.FAILED
    assert "GITHUB_PERSONAL_ACCESS_TOKEN" in (result.failure_reason or "")
    await client.aclose()


async def test_observe_falls_back_when_named_workflow_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/workflows/release-build.yml") and not request.url.path.endswith("/runs"):
            return httpx.Response(404, json={"message": "Not Found", "status": "404"})
        if request.url.path.endswith("/actions/workflows/release-build.yml/runs"):
            return httpx.Response(404, json={"message": "Not Found", "status": "404"})
        if request.url.path.endswith("/actions/runs") and request.method == "GET":
            return httpx.Response(200, json={"workflow_runs": [_run(status="in_progress")]})
        if request.url.path.endswith("/actions/runs/44"):
            return httpx.Response(200, json=_run())
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.COMPLETED
    assert result.build_id == "GHA-44"
    await client.aclose()


async def test_observe_fails_fast_when_workflow_and_runs_missing():
    def handler(request: httpx.Request) -> httpx.Response:
        if "/actions/" in request.url.path:
            if request.url.path.endswith("/actions/runs"):
                return httpx.Response(200, json={"workflow_runs": []})
            return httpx.Response(404, json={"message": "Not Found", "status": "404"})
        return httpx.Response(404, text="missing")

    client = GitHubActionsClient(
        _settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    result = await client.run_release_build(_state())
    assert result.status == BuildStatus.FAILED
    assert "release-build.yml" in (result.failure_reason or "")
    assert "AI_Studio_Main" not in (result.failure_reason or "")
    assert "acme/app" in (result.failure_reason or "")
    await client.aclose()


async def test_api_error_message():
    client = GitHubActionsClient(
        _settings(),
        http_client=httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(401, text="bad credentials")
            )
        ),
    )
    try:
        await client.list_workflow_runs("acme", "app")
        raise AssertionError("expected GitHubActionsError")
    except GitHubActionsError as exc:
        assert "401" in str(exc)
    await client.aclose()
