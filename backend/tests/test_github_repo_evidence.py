"""GitHub repo evidence client tests."""

import base64

import httpx
import pytest
from pydantic import SecretStr

from app.config import Settings
from app.services.github_repo_evidence import GitHubRepoEvidenceClient


def _settings() -> Settings:
    return Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("gha_test_token"))


def _handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if path.endswith("/git/trees/abc1234"):
        return httpx.Response(
            200,
            json={
                "tree": [
                    {"path": "app/offerings.py", "type": "blob"},
                    {"path": "tests/test_offerings.py", "type": "blob"},
                    {"path": "tests/test_unrelated.py", "type": "blob"},
                ]
            },
        )
    if "/contents/tests/test_offerings.py" in path:
        encoded = base64.b64encode(b"def test_remove_offerings():\n    assert True\n").decode()
        return httpx.Response(
            200,
            json={"encoding": "base64", "content": encoded},
        )
    if path.endswith("/commits/abc1234/check-runs"):
        return httpx.Response(
            200,
            json={"check_runs": [{"conclusion": "success", "name": "tests"}]},
        )
    if path.endswith("/commits/abc1234/status"):
        return httpx.Response(200, json={"state": "success"})
    return httpx.Response(404, json={"message": "not found"})


@pytest.mark.asyncio
async def test_collect_lane1_evidence_reads_related_tests_and_ci():
    transport = httpx.MockTransport(_handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = GitHubRepoEvidenceClient(
            settings=_settings(),
            http_client=http_client,
            api_url="https://api.github.com",
        )
        evidence = await client.collect_lane1_evidence(
            {
                "metadata": {
                    "owner": "acme",
                    "repo": "app",
                    "head_sha": "abc1234",
                    "changed_files": [
                        {"filename": "app/offerings.py", "status": "modified"}
                    ],
                }
            }
        )

    assert evidence["ci_status"] == "success"
    assert evidence["repo_test_files"]
    assert evidence["repo_test_files"][0]["filename"] == "tests/test_offerings.py"
    assert "test_remove_offerings" in evidence["repo_test_files"][0]["patch"]
    assert "app/offerings.py" in evidence["source_files"]
