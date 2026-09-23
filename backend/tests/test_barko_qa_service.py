"""Barko QA: call client with input, wrap passed/reasoning for the next step."""

from unittest.mock import AsyncMock
from pydantic import SecretStr

from app.agents.barko_qa_agent import BarkoQAAgent
from app.agents.qa_agent import QAAgent
from app.agents.qa_factory import create_qa_agent
from app.config import Settings
from app.models.validation import GitHubChecks, GitHubValidationResult, ValidationStatus
from app.services.barko_qa_client import BarkoQACredentials, BarkoQARequest, BarkoQAResult


def test_create_qa_agent_default_is_in_app_agent():
    agent = create_qa_agent(Settings(QA_WORKFLOW="default"))
    assert isinstance(agent, QAAgent)


def test_create_qa_agent_barko_switch():
    agent = create_qa_agent(Settings(QA_WORKFLOW="barko_agent"))
    assert isinstance(agent, BarkoQAAgent)


def test_credentials_repr_hides_tokens():
    creds = BarkoQACredentials(
        jira_email="qa@example.com",
        jira_api_token=SecretStr("jira-secret-token"),
        github_token=SecretStr("github-secret-token"),
    )
    rendered = repr(creds)
    assert "jira-secret-token" not in rendered
    assert "github-secret-token" not in rendered
    dumped = BarkoQARequest(
        release_id="REL-1",
        environment="UAT",
        release_version="v1.0.0",
    ).model_dump()
    assert "jira_api_token" not in dumped
    assert "github_token" not in dumped


async def test_barko_agent_pass_and_fail_via_client():
    client = AsyncMock()
    client.run.return_value = BarkoQAResult(passed=True, reasoning="Suite green.")
    agent = BarkoQAAgent(Settings(QA_WORKFLOW="barko_agent"), client=client)
    github = GitHubValidationResult(
        status=ValidationStatus.PASS,
        checks=GitHubChecks(),
        metadata={
            "github_pr_url": "https://github.com/company/repository/pull/123",
            "owner": "company",
            "repo": "repository",
            "pull_number": 123,
            "head_sha": "abc123",
            "pr_title": "SCRUM-6",
        },
    )
    result = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=True,
        environment="UAT",
        release_version="v1.0.0",
        jira_issue_key="SCRUM-6",
        github_validation=github,
    )
    assert result.status == ValidationStatus.PASS
    assert result.checks.signoff_completed is True
    assert result.errors == []
    assert result.metadata["barko_reasoning"] == "Suite green."
    request, credentials = client.run.await_args.args
    assert request.jira_issue_key == "SCRUM-6"
    assert request.github_owner == "company"
    assert request.github_pull_number == 123
    assert isinstance(credentials.github_token, SecretStr)
    assert isinstance(credentials.jira_api_token, SecretStr)

    client.run.return_value = BarkoQAResult(passed=False, reasoning="Flaky checkout.")
    failed = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=True,
        environment="UAT",
        release_version="v1.0.0",
        jira_issue_key="SCRUM-6",
        github_validation=github,
    )
    assert failed.status == ValidationStatus.FAIL
    assert failed.errors == ["Flaky checkout."]


async def test_barko_agent_skips_client_when_not_required():
    client = AsyncMock()
    agent = BarkoQAAgent(Settings(QA_WORKFLOW="barko_agent"), client=client)
    result = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=False,
        environment="UAT",
        release_version="v1.0.0",
        qa_signoff_not_required_reason="Docs only",
    )
    assert result.status == ValidationStatus.PASS
    assert result.checks.signoff_required is False
    client.run.assert_not_awaited()


async def test_unconfigured_client_is_error_not_pass():
    agent = BarkoQAAgent(Settings(QA_WORKFLOW="barko_agent"))
    result = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=True,
        environment="UAT",
        release_version="v1.0.0",
        jira_issue_key="SCRUM-6",
    )
    assert result.status == ValidationStatus.ERROR
    assert result.checks.signoff_completed is False
    assert "not configured" in result.errors[0].lower()


async def test_barko_does_not_log_tokens(caplog):
    client = AsyncMock()
    client.run.return_value = BarkoQAResult(passed=True, reasoning="ok")
    settings = Settings(
        QA_WORKFLOW="barko_agent",
        JIRA_API_TOKEN=SecretStr("super-secret-jira"),
        GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr("super-secret-github"),
    )
    agent = BarkoQAAgent(settings, client=client)
    with caplog.at_level("INFO"):
        await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            jira_issue_key="SCRUM-6",
        )
    combined = "\n".join(record.getMessage() for record in caplog.records)
    assert "super-secret-jira" not in combined
    assert "super-secret-github" not in combined
