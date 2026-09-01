"""GitHub Actions client for release build observe/dispatch and polling."""

from __future__ import annotations

import asyncio
import logging
import inspect
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.models.build_result import BuildResult, BuildStatus
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)

GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"

_SUCCESS_CONCLUSIONS = {"success"}
_FAILED_CONCLUSIONS = {
    "failure",
    "cancelled",
    "canceled",
    "timed_out",
    "startup_failure",
    "action_required",
    "stale",
    "neutral",
    "skipped",
}


class GitHubActionsError(RuntimeError):
    """Raised when the GitHub Actions API cannot complete a build operation."""


OnRunDiscovered = Callable[[BuildResult], Awaitable[None] | None]


class GitHubActionsClient:
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
        token = self.settings.github_personal_access_token.get_secret_value().strip()
        if not token:
            raise GitHubActionsError(
                "GITHUB_PERSONAL_ACCESS_TOKEN must be configured for GitHub Actions builds"
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
            raise GitHubActionsError(
                f"GitHub Actions API {method} {path} failed "
                f"({response.status_code}): {detail or 'no response body'}"
            )
        return response

    async def list_workflow_runs(
        self,
        owner: str,
        repo: str,
        *,
        head_sha: str | None = None,
        workflow: str | None = None,
        event: str | None = None,
        per_page: int = 20,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"per_page": per_page}
        if head_sha:
            params["head_sha"] = head_sha
        if event:
            params["event"] = event
        if workflow:
            path = f"/repos/{owner}/{repo}/actions/workflows/{workflow}/runs"
            response = await self._request("GET", path, params=params, expected_status=(200, 404))
            if response.status_code == 404:
                logger.warning(
                    "[GITHUB_ACTIONS] Workflow %s was not found in %s/%s; listing all runs",
                    workflow,
                    owner,
                    repo,
                )
                return await self.list_workflow_runs(
                    owner,
                    repo,
                    head_sha=head_sha,
                    event=event,
                    per_page=per_page,
                )
            payload = response.json()
        else:
            path = f"/repos/{owner}/{repo}/actions/runs"
            try:
                payload = (await self._request("GET", path, params=params)).json()
            except GitHubActionsError as exc:
                if "(404)" in str(exc):
                    raise GitHubActionsError(
                        f"Cannot read GitHub Actions in {owner}/{repo}. "
                        "Grant the PAT Actions: Read (GitHub often returns 404 when the "
                        "token cannot access Actions), or enable Actions on that repository."
                    ) from exc
                raise
        runs = payload.get("workflow_runs") if isinstance(payload, dict) else None
        return runs if isinstance(runs, list) else []

    async def get_workflow_run(
        self,
        owner: str,
        repo: str,
        run_id: int | str,
    ) -> dict[str, Any]:
        path = f"/repos/{owner}/{repo}/actions/runs/{run_id}"
        payload = (await self._request("GET", path)).json()
        if not isinstance(payload, dict):
            raise GitHubActionsError(f"Unexpected workflow run payload for {run_id}")
        return payload

    async def dispatch_workflow(
        self,
        owner: str,
        repo: str,
        workflow: str,
        ref: str,
        inputs: dict[str, str] | None = None,
    ) -> None:
        path = f"/repos/{owner}/{repo}/actions/workflows/{workflow}/dispatches"
        body: dict[str, Any] = {"ref": ref}
        if inputs:
            body["inputs"] = inputs
        await self._request("POST", path, json=body, expected_status=(204,))

    async def workflow_exists(
        self,
        owner: str,
        repo: str,
        workflow: str,
        *,
        ref: str | None = None,
    ) -> bool:
        if ref:
            path = f"/repos/{owner}/{repo}/contents/.github/workflows/{workflow}"
            response = await self._request(
                "GET",
                path,
                params={"ref": ref},
                expected_status=(200, 404),
            )
            if response.status_code == 200:
                return True
        path = f"/repos/{owner}/{repo}/actions/workflows/{workflow}"
        response = await self._request("GET", path, expected_status=(200, 404))
        return response.status_code == 200

    async def find_run_for_sha(
        self,
        owner: str,
        repo: str,
        head_sha: str,
        *,
        workflow: str | None = None,
    ) -> dict[str, Any] | None:
        runs = await self.list_workflow_runs(
            owner,
            repo,
            head_sha=head_sha,
            workflow=workflow,
        )
        return runs[0] if runs else None

    async def wait_for_run(
        self,
        owner: str,
        repo: str,
        run_id: int | str,
        *,
        poll_interval_seconds: int | None = None,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        interval = poll_interval_seconds or self.settings.github_actions_poll_interval_seconds
        timeout = timeout_seconds or self.settings.github_actions_poll_timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            run = await self.get_workflow_run(owner, repo, run_id)
            if str(run.get("status") or "").lower() == "completed":
                return run
            if asyncio.get_running_loop().time() >= deadline:
                raise GitHubActionsError(
                    f"Timed out waiting for GitHub Actions run {run_id} after {timeout}s"
                )
            await asyncio.sleep(interval)

    async def run_release_build(
        self,
        state: ReleaseState,
        *,
        on_run_discovered: OnRunDiscovered | None = None,
    ) -> BuildResult:
        owner = str(state.get("github_owner") or "").strip()
        repo = str(state.get("github_repo") or "").strip()
        if not owner or not repo:
            return self._failed_result(
                state,
                "GitHub owner/repository is missing from the release state.",
            )

        merge_sha = _merge_sha(state)
        workflow = self.settings.github_actions_workflow.strip() or None
        try:
            if self.settings.ci_trigger_mode == "dispatch":
                run = await self._dispatch_and_discover(
                    state,
                    owner=owner,
                    repo=repo,
                    merge_sha=merge_sha,
                    workflow=workflow,
                )
            else:
                try:
                    run = await self._observe_run(
                        owner=owner,
                        repo=repo,
                        merge_sha=merge_sha,
                        workflow=workflow,
                        ref=str(state.get("release_branch") or "").strip() or None,
                    )
                except GitHubActionsError as observe_exc:
                    logger.warning(
                        "[GITHUB_ACTIONS] Observe found no run; dispatching %s on %s/%s. %s",
                        workflow,
                        owner,
                        repo,
                        observe_exc,
                    )
                    run = await self._dispatch_and_discover(
                        state,
                        owner=owner,
                        repo=repo,
                        merge_sha=merge_sha,
                        workflow=workflow,
                    )
        except GitHubActionsError as exc:
            logger.error("[GITHUB_ACTIONS] Failed to start or find build: %s", exc)
            return self._failed_result(state, str(exc), commit_sha=merge_sha)

        pending = self._result_from_run(state, run, status=BuildStatus.PENDING)
        if on_run_discovered is not None:
            maybe_awaitable = on_run_discovered(pending)
            if inspect.isawaitable(maybe_awaitable):
                await maybe_awaitable

        run_id = run.get("id")
        if run_id is None:
            return self._failed_result(
                state,
                "GitHub Actions run did not include an id.",
                commit_sha=merge_sha,
            )

        try:
            completed = await self.wait_for_run(owner, repo, run_id)
        except GitHubActionsError as exc:
            logger.error("[GITHUB_ACTIONS] Build poll failed: %s", exc)
            return self._failed_result(
                state,
                str(exc),
                commit_sha=merge_sha,
                run=run,
            )
        return self._result_from_run(state, completed)

    async def _observe_run(
        self,
        *,
        owner: str,
        repo: str,
        merge_sha: str | None,
        workflow: str | None,
        ref: str | None = None,
    ) -> dict[str, Any]:
        if not merge_sha:
            raise GitHubActionsError(
                "merge_sha is required to observe a GitHub Actions run after merge"
            )
        timeout = self.settings.github_actions_discover_timeout_seconds
        interval = self.settings.github_actions_poll_interval_seconds
        deadline = asyncio.get_running_loop().time() + timeout
        missing_named_workflow = False
        if workflow and not await self.workflow_exists(owner, repo, workflow, ref=ref):
            missing_named_workflow = True
            logger.warning(
                "[GITHUB_ACTIONS] %s is not on %s/%s@%s; looking for any run on %s",
                workflow,
                owner,
                repo,
                ref or "default",
                merge_sha[:7],
            )

        while True:
            run = await self.find_run_for_sha(
                owner,
                repo,
                merge_sha,
                workflow=None if missing_named_workflow else workflow,
            )
            if run:
                logger.info(
                    "[GITHUB_ACTIONS] Found workflow run %s for %s/%s@%s",
                    run.get("id"),
                    owner,
                    repo,
                    merge_sha[:7],
                )
                return run
            if missing_named_workflow:
                raise GitHubActionsError(
                    f"No GitHub Actions workflow '{workflow}' on {owner}/{repo}"
                    f"{('@' + ref) if ref else ''}, "
                    f"and no run exists for commit {merge_sha[:7]}. "
                    f"Copy .github/workflows/{workflow} onto branch '{ref or 'Release-v1'}' "
                    "in the PR repo, then merge again."
                )
            if asyncio.get_running_loop().time() >= deadline:
                workflow_hint = f" ({workflow})" if workflow else ""
                raise GitHubActionsError(
                    f"No GitHub Actions run found for {owner}/{repo}@{merge_sha[:7]} "
                    f"within {timeout}s{workflow_hint}. "
                    f"Add .github/workflows/{workflow or 'release-build.yml'} to {owner}/{repo} "
                    "(the PR repo), or merge to a branch that already triggers CI."
                )
            await asyncio.sleep(interval)

    async def _dispatch_and_discover(
        self,
        state: ReleaseState,
        *,
        owner: str,
        repo: str,
        merge_sha: str | None,
        workflow: str | None,
    ) -> dict[str, Any]:
        if not workflow:
            raise GitHubActionsError(
                "GITHUB_ACTIONS_WORKFLOW must be set when CI_TRIGGER_MODE=dispatch"
            )
        ref = str(state.get("release_branch") or "").strip()
        if not ref:
            raise GitHubActionsError(
                "release_branch is required to dispatch a workflow (use Release-v1, not main)"
            )

        inputs = {
            key: value
            for key, value in {
                "release_id": str(state.get("release_id") or ""),
                "release_version": str(state.get("release_version") or ""),
                "environment": str(state.get("environment") or ""),
            }.items()
            if value
        }
        dispatched_at = datetime.now(timezone.utc)
        await self.dispatch_workflow(owner, repo, workflow, ref, inputs or None)
        logger.info(
            "[GITHUB_ACTIONS] Dispatched %s on %s/%s@%s",
            workflow,
            owner,
            repo,
            ref,
        )

        timeout = self.settings.github_actions_discover_timeout_seconds
        interval = self.settings.github_actions_poll_interval_seconds
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            runs = await self.list_workflow_runs(
                owner,
                repo,
                workflow=workflow,
                event="workflow_dispatch",
            )
            match = _newest_run_since(runs, dispatched_at, merge_sha)
            if match is None:
                match = _newest_run_since(runs, dispatched_at, None)
            if match:
                return match
            if asyncio.get_running_loop().time() >= deadline:
                raise GitHubActionsError(
                    f"Dispatched {workflow} but no matching run appeared within {timeout}s"
                )
            await asyncio.sleep(interval)

    def _result_from_run(
        self,
        state: ReleaseState,
        run: dict[str, Any],
        *,
        status: BuildStatus | None = None,
    ) -> BuildResult:
        conclusion = str(run.get("conclusion") or "").lower()
        run_status = str(run.get("status") or "").lower()
        if status is None:
            if run_status != "completed":
                mapped = BuildStatus.PENDING
            elif conclusion in _SUCCESS_CONCLUSIONS:
                mapped = BuildStatus.COMPLETED
            else:
                mapped = BuildStatus.FAILED
        else:
            mapped = status

        run_id = str(run.get("id") or run.get("run_number") or "unknown")
        html_url = run.get("html_url")
        logs_url = run.get("logs_url")
        head_sha = run.get("head_sha") or _merge_sha(state)
        failure_reason = None
        if mapped == BuildStatus.FAILED:
            failure_reason = (
                f"GitHub Actions run {run_id} {run_status}"
                + (f" ({conclusion})" if conclusion else "")
            )
        return BuildResult(
            build_id=f"GHA-{run_id}",
            status=mapped,
            generated_at=datetime.now(timezone.utc),
            release_version=str(state.get("release_version") or ""),
            target_environment=str(state.get("environment") or ""),
            job_url=str(html_url) if html_url else None,
            logs_url=str(logs_url) if logs_url else None,
            commit_sha=str(head_sha) if head_sha else None,
            external_run_id=run_id,
            failure_reason=failure_reason,
            workflow_name=str(run.get("name") or self.settings.github_actions_workflow or ""),
        )

    def _failed_result(
        self,
        state: ReleaseState,
        reason: str,
        *,
        commit_sha: str | None = None,
        run: dict[str, Any] | None = None,
    ) -> BuildResult:
        run_id = str((run or {}).get("id") or "failed")
        html_url = (run or {}).get("html_url")
        return BuildResult(
            build_id=f"GHA-{run_id}",
            status=BuildStatus.FAILED,
            generated_at=datetime.now(timezone.utc),
            release_version=str(state.get("release_version") or ""),
            target_environment=str(state.get("environment") or ""),
            job_url=str(html_url) if html_url else None,
            commit_sha=commit_sha or _merge_sha(state),
            external_run_id=str((run or {}).get("id") or "") or None,
            failure_reason=reason,
            workflow_name=self.settings.github_actions_workflow or None,
        )


def _merge_sha(state: ReleaseState) -> str | None:
    merge = state.get("merge_result")
    if isinstance(merge, dict):
        sha = merge.get("merge_sha")
        if not sha:
            metadata = merge.get("metadata")
            if isinstance(metadata, dict):
                sha = metadata.get("merge_sha")
        return str(sha) if sha else None
    sha = getattr(merge, "merge_sha", None)
    return str(sha) if sha else None


def _newest_run_since(
    runs: list[dict[str, Any]],
    dispatched_at: datetime,
    merge_sha: str | None,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for run in runs:
        if merge_sha and run.get("head_sha") and run.get("head_sha") != merge_sha:
            continue
        created = _parse_github_datetime(run.get("created_at"))
        if created is not None and created < dispatched_at:
            continue
        matches.append(run)
    return matches[0] if matches else None


def _parse_github_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
