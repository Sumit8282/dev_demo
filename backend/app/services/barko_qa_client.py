"""External Barko QA client: request in, passed/reasoning out."""

from __future__ import annotations

import logging

from pydantic import BaseModel, ConfigDict, Field, SecretStr

logger = logging.getLogger(__name__)


class BarkoQAClientError(RuntimeError):
    """Raised when the Barko client cannot complete a run."""


class BarkoQAResult(BaseModel):
    passed: bool
    reasoning: str = ""


class BarkoQARequest(BaseModel):
    """Safe-to-log payload. Credentials are passed separately."""

    release_id: str
    environment: str
    release_version: str
    jira_issue_key: str | None = None
    github_pr_url: str | None = None
    github_owner: str | None = None
    github_repo: str | None = None
    github_pull_number: int | None = None
    github_head_sha: str | None = None
    pr_title: str | None = None


class BarkoQACredentials(BaseModel):
    model_config = ConfigDict(extra="forbid")

    jira_email: str = ""
    jira_api_token: SecretStr = Field(default=SecretStr(""), repr=False)
    github_token: SecretStr = Field(default=SecretStr(""), repr=False)


class BarkoQAClient:
    """Placeholder until the Barko package/API is wired."""

    async def run(
        self,
        request: BarkoQARequest,
        credentials: BarkoQACredentials,
    ) -> BarkoQAResult:
        del credentials
        logger.info(
            "[BARKO_QA] Client is not configured; skipping external run for %s",
            request.release_id,
        )
        raise BarkoQAClientError("Barko QA client is not configured")
