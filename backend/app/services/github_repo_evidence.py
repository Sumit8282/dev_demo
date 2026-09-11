"""Fetch repo tests and commit check status for QA Lane 1 (no document)."""

from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.services.qa_pr_test_gate import (
    changed_production_files,
    extract_github_metadata,
    select_related_test_paths,
    select_source_paths,
)

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"
_MAX_FILE_CHARS = 8000
_FAILED_CONCLUSIONS = {
    "failure",
    "cancelled",
    "canceled",
    "timed_out",
    "startup_failure",
    "action_required",
}


class GitHubRepoEvidenceClient:
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

    def _token(self) -> str:
        return self.settings.github_personal_access_token.get_secret_value().strip()

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        token = self._token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is None:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(20.0, read=40.0),
                follow_redirects=True,
            )
        return self._http_client

    async def aclose(self) -> None:
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()
            self._http_client = None

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        expected_status: tuple[int, ...] = (200,),
    ) -> httpx.Response | None:
        if not self._token():
            return None
        client = await self._client()
        response = await client.request(
            method,
            f"{self.api_url}{path}",
            headers=self._headers(),
            params=params,
        )
        if response.status_code not in expected_status:
            logger.warning(
                "[GITHUB_EVIDENCE] %s %s failed (%s)",
                method,
                path,
                response.status_code,
            )
            return None
        return response

    async def list_tree_paths(self, owner: str, repo: str, sha: str) -> list[str]:
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/trees/{sha}",
            params={"recursive": "1"},
        )
        if response is None:
            return []
        payload = response.json()
        tree = payload.get("tree") if isinstance(payload, dict) else None
        if not isinstance(tree, list):
            return []
        paths: list[str] = []
        for item in tree:
            if not isinstance(item, dict):
                continue
            if item.get("type") != "blob":
                continue
            path = str(item.get("path") or "").strip()
            if path:
                paths.append(path)
        return paths

    async def get_file_text(self, owner: str, repo: str, path: str, ref: str) -> str:
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/contents/{path.lstrip('/')}",
            params={"ref": ref},
            expected_status=(200, 404),
        )
        if response is None or response.status_code == 404:
            return ""
        payload = response.json()
        if not isinstance(payload, dict):
            return ""
        encoding = str(payload.get("encoding") or "")
        content = payload.get("content")
        if encoding == "base64" and isinstance(content, str):
            try:
                decoded = base64.b64decode(content).decode("utf-8", errors="replace")
            except Exception:
                return ""
            return decoded[:_MAX_FILE_CHARS]
        if isinstance(content, str) and content.strip():
            return content[:_MAX_FILE_CHARS]
        return ""

    async def get_commit_check_status(self, owner: str, repo: str, sha: str) -> str:
        check_response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{sha}/check-runs",
        )
        conclusions: list[str] = []
        if check_response is not None:
            payload = check_response.json()
            runs = payload.get("check_runs") if isinstance(payload, dict) else None
            if isinstance(runs, list):
                for item in runs:
                    if isinstance(item, dict) and item.get("conclusion"):
                        conclusions.append(str(item["conclusion"]).lower())

        status_response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/commits/{sha}/status",
        )
        if status_response is not None:
            payload = status_response.json()
            if isinstance(payload, dict):
                state = str(payload.get("state") or "").lower()
                if state:
                    conclusions.append(state)

        if any(item in _FAILED_CONCLUSIONS or item == "error" for item in conclusions):
            return "failure"
        if any(item in {"success", "passed"} for item in conclusions):
            return "success"
        if any(item in {"pending", "queued", "in_progress"} for item in conclusions):
            return "pending"
        return ""

    async def collect_related_repo_tests(
        self,
        *,
        owner: str,
        repo: str,
        sha: str,
        changed_files: list[str],
    ) -> list[dict[str, Any]]:
        if not owner or not repo or not sha:
            return []
        try:
            paths = await self.list_tree_paths(owner, repo, sha)
        except Exception as exc:
            logger.warning("[GITHUB_EVIDENCE] Tree listing failed: %s", exc)
            return []
        selected = select_related_test_paths(paths, changed_files=changed_files)
        files: list[dict[str, Any]] = []
        for path in selected:
            try:
                content = await self.get_file_text(owner, repo, path, sha)
            except Exception as exc:
                logger.warning("[GITHUB_EVIDENCE] Could not read %s: %s", path, exc)
                content = ""
            files.append(
                {
                    "filename": path,
                    "status": "existing",
                    "patch": content,
                    "source": "repo",
                }
            )
        return files

    async def collect_lane1_evidence(
        self,
        github_validation: Any | None,
    ) -> dict[str, Any]:
        metadata = extract_github_metadata(github_validation)
        owner = str(metadata.get("owner") or "").strip()
        repo = str(metadata.get("repo") or "").strip()
        sha = str(metadata.get("head_sha") or "").strip()
        evidence: dict[str, Any] = {
            "repo_test_files": [],
            "source_files": [],
            "source_excerpt": "",
            "ci_status": "",
        }
        if not owner or not repo or not sha or not self._token():
            return evidence
        changed = changed_production_files(github_validation)
        if not changed:
            changed = [
                str(item.get("filename") or "")
                for item in (metadata.get("changed_files") or [])
                if isinstance(item, dict) and item.get("filename")
            ]
        try:
            evidence["repo_test_files"] = await self.collect_related_repo_tests(
                owner=owner,
                repo=repo,
                sha=sha,
                changed_files=changed,
            )
        except Exception as exc:
            logger.warning("[GITHUB_EVIDENCE] Related repo tests failed: %s", exc)
        try:
            paths = await self.list_tree_paths(owner, repo, sha)
            evidence["source_files"] = select_source_paths(paths, changed_files=changed)
            chunks: list[str] = []
            for path in evidence["source_files"][:15]:
                content = await self.get_file_text(owner, repo, path, sha)
                if not content.strip():
                    continue
                chunks.append(f"### {path}\n{content[:1500]}")
            evidence["source_excerpt"] = "\n\n".join(chunks)
        except Exception as exc:
            logger.warning("[GITHUB_EVIDENCE] Source file listing failed: %s", exc)
        try:
            evidence["ci_status"] = await self.get_commit_check_status(owner, repo, sha)
        except Exception as exc:
            logger.warning("[GITHUB_EVIDENCE] Check status failed: %s", exc)
        return evidence
