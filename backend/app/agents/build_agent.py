"""Build Agent — generates or observes a release build after merge completes."""

from __future__ import annotations

import logging
import random
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.config import Settings, get_settings
from app.models.build_result import BuildResult, BuildStatus
from app.services.github_actions_client import GitHubActionsClient
from app.workflow.state import ReleaseState

logger = logging.getLogger(__name__)

OnRunDiscovered = Callable[[BuildResult], Awaitable[None] | None]


class BuildAgent:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        actions_client: GitHubActionsClient | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.actions_client = actions_client

    async def generate_build(
        self,
        state: ReleaseState,
        *,
        on_run_discovered: OnRunDiscovered | None = None,
    ) -> BuildResult:
        release_id = state["release_id"]
        if self.settings.ci_provider == "github_actions":
            logger.info(
                "[BUILD_AGENT] Starting GitHub Actions build for %s (mode=%s)",
                release_id,
                self.settings.ci_trigger_mode,
            )
            client = self.actions_client or GitHubActionsClient(self.settings)
            try:
                result = await client.run_release_build(
                    state,
                    on_run_discovered=on_run_discovered,
                )
            finally:
                if self.actions_client is None:
                    await client.aclose()
            logger.info(
                "[BUILD_AGENT] GitHub Actions build for %s — %s (%s)",
                release_id,
                result.build_id,
                result.status.value,
            )
            if (
                result.status == BuildStatus.FAILED
                and self.settings.ci_fallback_to_stub
                and _is_missing_ci_run(result.failure_reason)
            ):
                logger.warning(
                    "[BUILD_AGENT] No GitHub Actions run for %s; falling back to stub. %s",
                    release_id,
                    result.failure_reason,
                )
                stub = self._generate_stub_build(state)
                stub.workflow_name = "stub-fallback"
                stub.commit_sha = result.commit_sha
                stub.failure_reason = result.failure_reason
                return stub
            return result

        return self._generate_stub_build(state)

    def _generate_stub_build(self, state: ReleaseState) -> BuildResult:
        release_id = state["release_id"]
        logger.info("[BUILD_AGENT] Generating stub build for release %s", release_id)

        now = datetime.now(timezone.utc)
        date_str = now.strftime("%Y%m%d")
        random_suffix = str(random.randint(1, 999)).zfill(3)
        build_id = f"BUILD-{date_str}-{random_suffix}"

        build_result = BuildResult(
            build_id=build_id,
            status=BuildStatus.COMPLETED,
            generated_at=now,
            release_version=state["release_version"],
            target_environment=state["environment"],
        )

        logger.info(
            "[BUILD_AGENT] Stub build generated for %s — %s",
            release_id,
            build_id,
        )
        return build_result


def _is_missing_ci_run(reason: str | None) -> bool:
    text = (reason or "").lower()
    return any(
        marker in text
        for marker in (
            "no github actions run",
            "no github actions workflow",
            "cannot read github actions",
            "was not found",
            "not found in",
        )
    )
