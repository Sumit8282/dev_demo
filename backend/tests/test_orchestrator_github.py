"""Orchestrator GitHub PR validation tests."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agents.orchestrator import Orchestrator
from app.models.validation import ValidationStatus


def _build_github_client(
    *,
    pr_payload: dict | None = None,
    comments_payload: dict | None = None,
):
    client = MagicMock()
    client.tool_names = ["pull_request_read"]
    client.get_pull_request_tool_name.return_value = "pull_request_read"
    client.get_pull_request = AsyncMock(
        return_value=pr_payload
        or {
            "number": 123,
            "title": "Release v2.4.0",
            "state": "open",
            "body": "Release fix for offerings dropdown",
            "user": {"login": "gauri-dev"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
        }
    )
    client.get_pull_request_comments = AsyncMock(
        return_value=comments_payload or {"comments": []}
    )
    client.get_pull_request_files = AsyncMock(
        return_value=[
            {
                "filename": ".gitignore",
                "status": "added",
                "additions": 21,
                "deletions": 0,
            },
            {
                "filename": "frontend/package-lock.json",
                "status": "modified",
                "additions": 18,
                "deletions": 1,
            },
        ]
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    return client


@pytest.mark.asyncio
async def test_orchestrator_github_pass(sample_state):
    orchestrator = Orchestrator(github_client=_build_github_client())
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.PASS
    assert result.checks.pr_is_open is True
    assert result.metadata["source_branch"] == "release/v2.4.0"
    assert result.metadata.get("pr_description") == "Release fix for offerings dropdown"
    assert result.metadata["target_branch"] == "main"
    assert result.metadata["pull_number"] == 123
    assert result.metadata["author"] == "gauri-dev"
    assert result.metadata["raised_by"] == "gauri-dev"
    assert result.metadata["files_changed_count"] == 2
    assert result.metadata["lines_added"] == 39
    assert result.metadata["lines_deleted"] == 1
    assert ".gitignore" in result.metadata["changed_file_names"]


@pytest.mark.asyncio
async def test_orchestrator_github_source_branch_mismatch(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "user": {"login": "dev1"},
            "head": {"ref": "feature/wrong"},
            "base": {"ref": "main"},
        }
    )
    orchestrator = Orchestrator(github_client=client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.FAIL
    assert result.checks.source_branch_match is False


@pytest.mark.asyncio
async def test_orchestrator_github_pr_merged_fails(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "state": "closed",
            "merged": True,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
        }
    )
    orchestrator = Orchestrator(github_client=client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.FAIL
    assert result.checks.pr_is_open is False
    assert any("merged" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_orchestrator_github_pr_closed_fails(sample_state):
    client = _build_github_client(
        pr_payload={
            "number": 123,
            "state": "closed",
            "merged": False,
            "user": {"login": "dev1"},
            "head": {"ref": "release/v2.4.0"},
            "base": {"ref": "main"},
        }
    )
    orchestrator = Orchestrator(github_client=client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.FAIL
    assert result.checks.pr_is_open is False
    assert any("closed" in error.lower() for error in result.errors)


@pytest.mark.asyncio
async def test_orchestrator_github_pr_missing(sample_state):
    client = _build_github_client(pr_payload={"error": "Not found"})
    orchestrator = Orchestrator(github_client=client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.FAIL
    assert result.checks.pr_exists is False


@pytest.mark.asyncio
async def test_orchestrator_invalid_pr_url_shows_friendly_message(sample_state):
    from app.mcp.client_base import MCPConnectionError
    from app.mcp.github_mcp import INVALID_PR_URL_MESSAGE

    client = _build_github_client()
    client.get_pull_request = AsyncMock(
        side_effect=MCPConnectionError(
            "[github_mcp] Tool pull_request_read failed: missing required parameter: method"
        )
    )
    orchestrator = Orchestrator(github_client=client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.FAIL
    assert result.errors == [INVALID_PR_URL_MESSAGE]
    assert "missing required parameter: method" not in result.errors[0]
    assert "Provide the valid url this url is invalid" in result.errors[0]


@pytest.mark.asyncio
async def test_orchestrator_github_validates_via_rest(sample_state):
    import httpx
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.github_pr_client import GitHubPRClient

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/pulls/123") and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "number": 123,
                    "title": "Release v2.4.0",
                    "state": "open",
                    "body": "Release fix via REST",
                    "user": {"login": "gauri-dev"},
                    "head": {"ref": "release/v2.4.0", "sha": "abc1234567"},
                    "base": {"ref": "main"},
                    "additions": 4,
                    "deletions": 1,
                    "changed_files": 1,
                },
            )
        if path.endswith("/issues/123/comments"):
            return httpx.Response(200, json=[])
        if path.endswith("/pulls/123/files"):
            return httpx.Response(
                200,
                json=[
                    {
                        "filename": "app/offerings.py",
                        "status": "modified",
                        "additions": 4,
                        "deletions": 1,
                    }
                ],
            )
        return httpx.Response(404, text="missing")

    rest_client = GitHubPRClient(
        Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("test-token")),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    orchestrator = Orchestrator(github_client=rest_client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.PASS
    assert result.metadata["github_source"] == "github_rest"
    assert result.metadata["source_branch"] == "release/v2.4.0"
    assert result.metadata["files_changed_count"] == 1
    assert result.metadata["pr_description"] == "Release fix via REST"


@pytest.mark.asyncio
async def test_orchestrator_github_rest_unauthorized_is_error(sample_state):
    import httpx
    from pydantic import SecretStr

    from app.config import Settings
    from app.services.github_pr_client import GitHubPRClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="Bad credentials")

    rest_client = GitHubPRClient(
        Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("bad-token")),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    orchestrator = Orchestrator(github_client=rest_client)
    result = await orchestrator.run_github_validation(sample_state)

    assert result.status == ValidationStatus.ERROR
    assert result.errors
    assert "GitHub PR validation failed" in result.errors[0]
    assert "401" in result.errors[0]


def test_is_github_unauthorized_detects_401_and_exception_group():
    from app.mcp.github_mcp import is_github_unauthorized

    assert is_github_unauthorized(RuntimeError("HTTP/1.1 401 Unauthorized"))
    group = ExceptionGroup("unhandled errors in a TaskGroup", [RuntimeError("401 Unauthorized")])
    assert is_github_unauthorized(group)
    assert not is_github_unauthorized(RuntimeError("PR not found"))


@pytest.mark.asyncio
async def test_github_client_falls_back_to_rest_on_mcp_401():
    from unittest.mock import patch

    from app.agents.orchestrator import _GitHubClientOrRestFallback
    from app.mcp.client_base import MCPConnectionError

    rest = _build_github_client()
    mcp = MagicMock()
    mcp.connect = AsyncMock(
        side_effect=MCPConnectionError(
            "[GITHUB_MCP] GitHub MCP rejected the token (401 Unauthorized)."
        )
    )
    mcp.disconnect = AsyncMock()

    with patch("app.agents.orchestrator.GitHubMCPClient", return_value=mcp), patch(
        "app.agents.orchestrator.GitHubPRClient", return_value=rest
    ):
        async with _GitHubClientOrRestFallback() as client:
            assert client is rest
    mcp.disconnect.assert_awaited()
