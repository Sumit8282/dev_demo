"""Tests for the GitHub REST pull-request client."""

import httpx
from pydantic import SecretStr

from app.config import Settings
from app.services.github_pr_client import GitHubPRClient, GitHubPRError


def _settings() -> Settings:
    return Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("gh_test_token"))


def _client(handler) -> GitHubPRClient:
    return GitHubPRClient(
        _settings(),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_get_pull_request_returns_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer gh_test_token"
        assert request.url.path == "/repos/acme/app/pulls/12"
        return httpx.Response(200, json={"number": 12, "state": "open"})

    payload = await _client(handler).get_pull_request("acme", "app", 12)
    assert payload["number"] == 12


async def test_get_pull_request_maps_404_to_error_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="Not Found")

    payload = await _client(handler).get_pull_request("acme", "app", 12)
    assert payload == {"error": "Not found"}


async def test_get_issue_returns_body_and_skips_404():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues/12"):
            return httpx.Response(
                200,
                json={
                    "number": 12,
                    "title": "Offering cards",
                    "body": "## Acceptance criteria\n- [ ] Cards are clickable",
                },
            )
        if request.url.path.endswith("/issues/99"):
            return httpx.Response(404, text="Not Found")
        return httpx.Response(404, text="Not Found")

    client = _client(handler)
    payload = await client.get_issue("acme", "app", 12)
    assert payload["number"] == 12
    assert "Cards are clickable" in payload["body"]
    missing = await client.get_issue("acme", "app", 99)
    assert missing == {"error": "Not found"}


async def test_get_issue_comments_returns_list():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/acme/app/issues/12/comments"
        return httpx.Response(200, json=[{"body": "Looks good"}])

    comments = await _client(handler).get_issue_comments("acme", "app", 12)
    assert comments[0]["body"] == "Looks good"


async def test_add_pull_request_comment_posts_body():
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content.decode()
        return httpx.Response(201, json={"id": 7, "body": "hello"})

    payload = await _client(handler).add_pull_request_comment(
        "acme", "app", 12, "hello"
    )
    assert payload["id"] == 7
    assert seen["path"] == "/repos/acme/app/issues/12/comments"
    assert "hello" in seen["body"]


async def test_add_pull_request_comment_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, text="Resource not accessible")

    try:
        await _client(handler).add_pull_request_comment("acme", "app", 12, "hello")
    except GitHubPRError as exc:
        assert "403" in str(exc)
    else:
        raise AssertionError("expected GitHubPRError")
