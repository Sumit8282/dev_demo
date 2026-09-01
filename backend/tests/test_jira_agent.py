"""Jira agent unit tests with mocked LLM responses."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.jira_agent import (
    JiraAgent,
    JiraTicketNotFoundError,
    _apply_authoritative_ac_constraints,
    _filter_release_automation_pr_comments,
    _log_jira_validation_matrix,
)
from app.config import Settings
from app.models.jira_llm_validation import JiraLLMValidationOutput, JiraRequirementMatrixRow
from app.models.validation import JiraChecks, JiraValidationResult, ValidationStatus


@pytest.fixture
def llm_settings():
    return Settings(
        USE_LLM_AGENTS=True,
        LLM_PROVIDER="openai",
        LLM_MODEL="gpt-4.1",
        LLM_API_KEY="test-key",
        LLM_BASE_URL="https://example.com/v1",
    )


@pytest.fixture
def mock_jira_prefetch():
    with patch.object(
        JiraAgent,
        "_prefetch_jira_ticket_context",
        new=AsyncMock(return_value=("(test snapshot)", [])),
    ) as prefetch_mock:
        yield prefetch_mock


@pytest.mark.asyncio
async def test_jira_pass(llm_settings, mock_jira_prefetch):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.PASS,
        validation_summary="## JIRA–PR Validation Summary\n\n**Overall Status:** PASS",
        jira_pr_relationship="MATCHED",
        checks=JiraChecks(
            ticket_exists=True,
            status_valid=True,
            fix_version_match=True,
            description_match=True,
        ),
        errors=[],
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ):
        result = await agent.validate(issue_key="ABC-123", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.PASS
    assert result.metadata.get("acceptance_criteria") == []


@pytest.mark.asyncio
async def test_jira_stores_prefetched_acceptance_criteria(llm_settings):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.PASS,
        checks=JiraChecks(
            ticket_exists=True,
            status_valid=True,
            fix_version_match=True,
            description_match=True,
        ),
        errors=[],
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(
        JiraAgent,
        "_prefetch_jira_ticket_context",
        new=AsyncMock(
            return_value=(
                "(test snapshot)",
                ["Remove the Offerings option from the dropdown menu."],
            )
        ),
    ), patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ):
        result = await agent.validate(issue_key="SCRUM-13", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.PASS
    assert result.metadata["acceptance_criteria"] == [
        "Remove the Offerings option from the dropdown menu."
    ]


@pytest.mark.asyncio
async def test_jira_ticket_missing_from_prefetch(llm_settings):
    agent = JiraAgent(settings=llm_settings)
    with patch.object(
        JiraAgent,
        "_prefetch_jira_ticket_context",
        new=AsyncMock(side_effect=JiraTicketNotFoundError("ABC-999")),
    ):
        result = await agent.validate(issue_key="ABC-999", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.FAIL
    assert result.checks.ticket_exists is False
    assert result.errors == ["Jira ticket ABC-999 does not exist."]


@pytest.mark.asyncio
async def test_jira_ticket_missing(llm_settings, mock_jira_prefetch):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(ticket_exists=False),
        errors=["Jira ticket ABC-999 does not exist."],
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ):
        result = await agent.validate(issue_key="ABC-999", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.FAIL
    assert result.checks.ticket_exists is False
    assert result.errors == ["Jira ticket ABC-999 does not exist."]


@pytest.mark.asyncio
async def test_jira_status_invalid(llm_settings, mock_jira_prefetch):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(ticket_exists=True, status_valid=False, fix_version_match=True),
        errors=["Invalid status"],
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ):
        result = await agent.validate(issue_key="ABC-123", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.FAIL
    assert result.checks.status_valid is False


@pytest.mark.asyncio
async def test_jira_fix_version_mismatch(llm_settings, mock_jira_prefetch):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(ticket_exists=True, status_valid=True, fix_version_match=False),
        errors=["Fix version mismatch"],
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ):
        result = await agent.validate(issue_key="ABC-123", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.FAIL
    assert result.checks.fix_version_match is False


@pytest.mark.asyncio
async def test_jira_description_mismatch(llm_settings, mock_jira_prefetch):
    expected = JiraLLMValidationOutput(
        status=ValidationStatus.FAIL,
        validation_summary="## JIRA–PR Validation Summary\n\n**Overall Status:** FAIL",
        jira_pr_relationship="PARTIALLY MATCHED",
        validation_matrix=[
            JiraRequirementMatrixRow(
                requirement_id="AC-01",
                jira_requirement="Fix login bug",
                pr_evidence="PR mentions UI changes only",
                status="Not Addressed",
                remarks="Scope mismatch",
            )
        ],
        checks=JiraChecks(
            ticket_exists=True,
            status_valid=True,
            fix_version_match=True,
            description_match=False,
        ),
        errors=["PR description does not match Jira issue description"],
        github_pr_description="Fix login page bug",
    )
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=expected)
    ) as invoke_mock:
        result = await agent.validate(
            issue_key="ABC-123",
            expected_release_version="v2.4.0",
            pr_description="Fix login page bug",
            pr_title="ABC-123: Fix login",
            code_change_summary="Files changed: 2",
        )

    assert result.status == ValidationStatus.FAIL
    assert result.checks.description_match is False
    assert result.metadata["jira_pr_relationship"] == "PARTIALLY MATCHED"
    assert len(result.metadata["validation_matrix"]) == 1
    user_message = invoke_mock.call_args.kwargs.get("user_message") or invoke_mock.call_args.args[1]
    assert "Fix login page bug" in user_message
    assert "ABC-123: Fix login" in user_message


def test_jira_validation_matrix_logged_to_terminal(caplog):
    result = JiraValidationResult(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(
            ticket_exists=True,
            status_valid=True,
            fix_version_match=False,
            description_match=False,
        ),
        errors=[
            "JIRA ticket SCRUM-13 does not specify the required fixVersion (Release-v1), blocking release.",
            "PR does not provide evidence/screenshots of UI on multiple browsers/resolutions.",
        ],
        metadata={
            "jira_pr_relationship": "MATCHED",
            "validation_matrix": [
                {
                    "requirement_id": "AC-07",
                    "jira_requirement": (
                        "Verify the UI is consistent across supported browsers/resolutions"
                    ),
                    "pr_evidence": (
                        "PR mentions UI consistency but no proof of cross-browser testing"
                    ),
                    "status": "Partially Addressed",
                    "remarks": "No browser/resolution evidence provided.",
                }
            ],
        },
    )

    with caplog.at_level("INFO", logger="app.agents.jira_agent"):
        _log_jira_validation_matrix(result)

    log_text = caplog.text
    assert "JIRA" in log_text and "validation matrix:" in log_text
    assert "AC-07" in log_text
    assert "Verify the UI is consistent across supported brow" in log_text
    assert "PR mentions UI consistency but no proof of cross-" in log_text
    assert "Partially Addressed" in log_text
    assert "relationship: MATCHED" in log_text
    assert "Validation errors:" in log_text


@pytest.mark.asyncio
async def test_jira_llm_not_configured():
    settings = Settings(USE_LLM_AGENTS=True, LLM_PROVIDER="", LLM_MODEL="", LLM_API_KEY="")
    agent = JiraAgent(settings=settings)
    result = await agent.validate(issue_key="ABC-123", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.ERROR


@pytest.mark.asyncio
async def test_jira_llm_returns_none(llm_settings, mock_jira_prefetch):
    agent = JiraAgent(settings=llm_settings)
    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.jira_agent.invoke_structured_agent", new=AsyncMock(return_value=None)
    ):
        result = await agent.validate(issue_key="ABC-123", expected_release_version="v2.4.0")

    assert result.status == ValidationStatus.ERROR


def test_filter_release_automation_pr_comments():
    comments = [
        {"author": "bot", "body": "Release Validation Failed\n\nFailed Checks:\nAC-07"},
        {"author": "qa", "body": "Looks good after retest"},
    ]
    filtered = _filter_release_automation_pr_comments(comments)
    assert filtered == [{"author": "qa", "body": "Looks good after retest"}]


def test_apply_authoritative_ac_constraints_drops_extra_ac_rows():
    llm_result = JiraLLMValidationOutput(
        status=ValidationStatus.FAIL,
        checks=JiraChecks(
            ticket_exists=True,
            status_valid=True,
            fix_version_match=True,
            description_match=False,
        ),
        validation_matrix=[
            JiraRequirementMatrixRow(
                requirement_id="AC-01",
                jira_requirement="Remove Offerings",
                pr_evidence="Done",
                status="Fully Addressed",
            ),
            JiraRequirementMatrixRow(
                requirement_id="AC-07",
                jira_requirement="Cross-browser screenshots",
                pr_evidence="Missing",
                status="Not Addressed",
            ),
        ],
        errors=["AC-07 missing screenshots"],
    )

    adjusted = _apply_authoritative_ac_constraints(
        llm_result,
        ["Remove Offerings"],
    )

    assert len(adjusted.validation_matrix) == 1
    assert adjusted.validation_matrix[0].requirement_id == "AC-01"
    assert adjusted.status == ValidationStatus.PASS
    assert adjusted.checks.description_match is True
    assert adjusted.errors == []
