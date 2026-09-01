"""QA agent unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent import QAAgent
from app.models.qa_llm_validation import QACoverageMatrixRow, QALLMValidationOutput
from app.models.validation import ValidationStatus
from app.services.qa_signoff_service import QASignoffService


@pytest.mark.asyncio
async def test_qa_agent_not_required():
    agent = QAAgent()
    result = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=False,
        environment="UAT",
        release_version="v1.0.0",
        qa_signoff_not_required_reason="Documentation only",
    )
    assert result.status == ValidationStatus.PASS


@pytest.mark.asyncio
async def test_qa_agent_required_missing_attachment():
    agent = QAAgent()
    result = await agent.validate_async(
        release_id="REL-1",
        qa_signoff_required=True,
        environment="UAT",
        release_version="v1.0.0",
        pr_title="SCRUM-6: Implement offerings",
        qa_signoff_attachment=None,
        jira_issue_key="SCRUM-6",
    )
    assert result.status == ValidationStatus.FAIL


@pytest.mark.asyncio
async def test_qa_agent_llm_ac_validation_pass():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = (
        "qa-signoff.docx",
        "PR Title\nImplement offerings\nTest Plan Status\nPassed",
    )

    settings = MagicMock()
    settings.llm_enabled = True

    agent = QAAgent(signoff_service=signoff_service, settings=settings)
    llm_output = QALLMValidationOutput(
        status=ValidationStatus.PASS,
        validation_summary="## QA Validation Summary\n\n**Overall Status:** PASS",
        coverage_matrix=[
            QACoverageMatrixRow(
                ac_id="AC-01",
                acceptance_criterion="Offerings dropdown navigates correctly",
                test_cases="TC-001",
                coverage="Fully Covered",
                test_result="Pass",
                evidence_reason="QA document validates navigation",
            )
        ],
        acceptance_criteria_coverage_percent=100.0,
        passed_acceptance_criteria_percent=100.0,
    )

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=AsyncMock(return_value=llm_output),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            pr_title="Implement offerings",
            qa_signoff_attachment={"filename": "qa-signoff.docx"},
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "jira_description": "Acceptance Criteria:\n- Offerings dropdown works",
                    "jira_comments": [{"author": "qa", "body": "Verified in UAT"}],
                }
            },
        )

    assert result.status == ValidationStatus.PASS
    assert result.checks.signoff_completed is True
    assert result.metadata["acceptance_criteria_coverage_percent"] == 100.0
    assert len(result.metadata["coverage_matrix"]) == 1


@pytest.mark.asyncio
async def test_qa_agent_uses_jira_matrix_acceptance_criteria():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = (
        "qa-signoff.docx",
        "TC-001 Remove Offerings — Passed",
    )
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(signoff_service=signoff_service, settings=settings)

    captured: dict[str, str] = {}
    llm_output = QALLMValidationOutput(
        status=ValidationStatus.PASS,
        validation_summary="## QA Validation Summary\n\n**Overall Status:** PASS",
        coverage_matrix=[
            QACoverageMatrixRow(
                ac_id="AC-01",
                acceptance_criterion="Remove the Offerings option from the dropdown menu.",
                test_cases="TC-001",
                coverage="Fully Covered",
                test_result="Pass",
            )
        ],
        acceptance_criteria_coverage_percent=100.0,
        passed_acceptance_criteria_percent=100.0,
    )

    async def fake_invoke(agent, *, user_message, response_model):
        captured["user_message"] = user_message
        return llm_output

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=fake_invoke,
    ), patch.object(
        agent,
        "_prefetch_jira_acceptance_criteria",
        new=AsyncMock(return_value=("", "", [])),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            pr_title="Remove Offerings",
            qa_signoff_attachment={"filename": "qa-signoff.docx"},
            jira_issue_key="SCRUM-13",
            jira_validation={
                "metadata": {
                    "jira_description": "Short summary without an AC heading",
                    "validation_matrix": [
                        {
                            "requirement_id": "AC-01",
                            "jira_requirement": "Remove the Offerings option from the dropdown menu.",
                            "status": "Fully Addressed",
                        },
                        {
                            "requirement_id": "AC-02",
                            "jira_requirement": "Keep other dropdown options unchanged.",
                            "status": "Fully Addressed",
                        },
                    ],
                }
            },
        )

    assert result.status == ValidationStatus.PASS
    assert "AC-01: Remove the Offerings option" in captured["user_message"]
    assert "Do not report them as missing" in captured["user_message"]
    assert result.metadata["no_acceptance_criteria_found"] is False


@pytest.mark.asyncio
async def test_qa_agent_does_not_fail_for_missing_ac_when_jira_already_found_them():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = ("qa-signoff.docx", "Passed")
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(signoff_service=signoff_service, settings=settings)
    llm_output = QALLMValidationOutput(
        status=ValidationStatus.FAIL,
        no_acceptance_criteria_found=True,
        errors=[
            "Missing explicit Acceptance Criteria in JIRA SCRUM-13 and comments. "
            "This blocks QA validation against requirements."
        ],
    )

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=AsyncMock(return_value=llm_output),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            qa_signoff_attachment={"filename": "qa-signoff.docx"},
            jira_issue_key="SCRUM-13",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": [
                        "Remove the Offerings option from the dropdown menu."
                    ]
                }
            },
        )

    assert result.metadata["no_acceptance_criteria_found"] is False
    assert not any("Missing explicit Acceptance Criteria" in error for error in result.errors)
