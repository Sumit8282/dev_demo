"""GitHub REST client for PR validation and issue comments."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
GITHUB_COMMENT_MAX_CHARS = 65536


class GitHubPRError(RuntimeError):
    """Raised when the GitHub REST API cannot complete a PR operation."""


class GitHubPRClient:
    """Read a pull request and post issue comments via api.github.com."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http_client: httpx.AsyncClient | None = None,
        api_url: str = GITHUB_API_URL,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client
        self._owns_client = http_client is None
        self.api_url = api_url.rstrip("/")

    @property
    def tool_names(self) -> list[str]:
        return ["github_rest"]

    def get_pull_request_tool_name(self) -> str:
        return "github_rest"

    def _token(self) -> str:
        token = self.settings.github_personal_access_token.get_secret_value().strip()
        if not token:
            raise GitHubPRError(
                "GITHUB_PERSONAL_ACCESS_TOKEN must be configured to read GitHub pull requests"
            )
        return token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, read=60.0),
                follow_redirects=True,
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def __aenter__(self) -> GitHubPRClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: dict[str, Any] | None = None,
        expected_status: tuple[int, ...] = (200,),
    ) -> httpx.Response:
        client = await self._client()
        url = f"{self.api_url}{path}"
        response = await client.request(
            method,
            url,
            headers=self._headers(),
            params=params,
            json=json,
        )
        if response.status_code not in expected_status:
            detail = response.text[:400].strip()
            raise GitHubPRError(
                f"GitHub REST {method} {path} failed "
                f"({response.status_code}): {detail or 'no response body'}"
            )
        return response

    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/pulls/{int(pull_number)}"
        response = await self._request("GET", path, expected_status=(200, 404))
        if response.status_code == 404:
            return {"error": "Not found"}
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise GitHubPRError(f"Unexpected pull request payload for {owner}/{repo}#{pull_number}")

    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/issues/{int(issue_number)}"
        response = await self._request("GET", path, expected_status=(200, 404))
        if response.status_code == 404:
            return {"error": "Not found"}
        payload = response.json()
        if isinstance(payload, dict):
            return payload
        raise GitHubPRError(f"Unexpected issue payload for {owner}/{repo}#{issue_number}")

    async def get_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int,
    ) -> list[Any]:
        path = f"/repos/{owner}/{repo}/issues/{int(issue_number)}/comments"
        payload = (
            await self._request("GET", path, params={"per_page": 100})
        ).json()
        return payload if isinstance(payload, list) else []

    async def get_pull_request_comments(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> list[Any]:
        return await self.get_issue_comments(owner, repo, pull_number)

    async def get_pull_request_files(
        self,
        owner: str,
        repo: str,
        pull_number: int,
    ) -> list[Any]:
        files: list[Any] = []
        page = 1
        while page <= 10:
            path = f"/repos/{owner}/{repo}/pulls/{int(pull_number)}/files"
            payload = (
                await self._request(
                    "GET",
                    path,
                    params={"per_page": 100, "page": page},
                )
            ).json()
            if not isinstance(payload, list) or not payload:
                break
            files.extend(payload)
            if len(payload) < 100:
                break
            page += 1
        return files

    async def add_pull_request_comment(
        self,
        owner: str,
        repo: str,
        pull_number: int,
        body: str,
    ) -> dict[str, Any]:
        text = body if len(body) <= GITHUB_COMMENT_MAX_CHARS else body[:GITHUB_COMMENT_MAX_CHARS]
        path = f"/repos/{owner}/{repo}/issues/{int(pull_number)}/comments"
        payload = (
            await self._request(
                "POST",
                path,
                json={"body": text},
                expected_status=(200, 201),
            )
        ).json()
        if isinstance(payload, dict):
            return payload
        return {"ok": True}
