"""QA agent unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent import QAAgent
from app.models.qa_llm_validation import (
    QAAcceptanceCriteriaExtract,
    QAAcceptanceCriterion,
    QACoverageMatrixRow,
    QALLMValidationOutput,
    QATestCase,
    QATestCaseExtract,
)
from app.models.validation import ValidationStatus
from app.services.qa_signoff_service import QASignoffService


def _pass_output() -> QALLMValidationOutput:
    return QALLMValidationOutput(
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


def _hybrid_invoke(
    mapper_output: QALLMValidationOutput,
    *,
    test_cases: list[QATestCase] | None = None,
    ac_extract: QAAcceptanceCriteriaExtract | None = None,
    captured: dict[str, object] | None = None,
):
    async def fake_invoke(agent, *, user_message, response_model):
        if captured is not None:
            captured.setdefault("models", []).append(response_model)
            captured[response_model.__name__] = user_message
        if response_model is QATestCaseExtract:
            return QATestCaseExtract(
                test_cases=test_cases
                or [
                    QATestCase(
                        test_case_id="TC-001",
                        scenario="Offerings dropdown navigates correctly",
                        status="Passed",
                    )
                ]
            )
        if response_model is QAAcceptanceCriteriaExtract:
            return ac_extract or QAAcceptanceCriteriaExtract(
                no_acceptance_criteria_found=True
            )
        return mapper_output

    return fake_invoke


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
    captured: dict[str, object] = {}

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(_pass_output(), captured=captured),
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
    assert result.metadata["ac_source"] == "code"
    assert result.metadata["hybrid_pipeline"] is True
    assert QAAcceptanceCriteriaExtract not in captured["models"]
    assert QATestCaseExtract in captured["models"]
    assert QALLMValidationOutput in captured["models"]


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

    captured: dict[str, object] = {}
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
            ),
            QACoverageMatrixRow(
                ac_id="AC-02",
                acceptance_criterion="Keep other dropdown options unchanged.",
                test_cases="TC-001",
                coverage="Fully Covered",
                test_result="Pass",
            ),
        ],
        acceptance_criteria_coverage_percent=100.0,
        passed_acceptance_criteria_percent=100.0,
    )

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(llm_output, captured=captured),
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

    mapper_message = captured["QALLMValidationOutput"]
    assert result.status == ValidationStatus.PASS
    assert "AC-01: Remove the Offerings option" in mapper_message
    assert "Do not report them as missing" in mapper_message
    assert "TC-001:" in mapper_message
    assert result.metadata["no_acceptance_criteria_found"] is False
    assert result.metadata["ac_source"] == "code"


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

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(llm_output),
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


@pytest.mark.asyncio
async def test_qa_agent_uses_llm_ac_extract_when_code_finds_none():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = (
        "qa-signoff.docx",
        "TC-001 Verify comment AC — Passed",
    )
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(signoff_service=signoff_service, settings=settings)
    captured: dict[str, object] = {}
    ac_extract = QAAcceptanceCriteriaExtract(
        acceptance_criteria=[
            QAAcceptanceCriterion(
                ac_id="AC-01",
                text="Hide Offerings when the flag is off.",
            )
        ]
    )

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_ac_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(_pass_output(), ac_extract=ac_extract, captured=captured),
    ), patch.object(
        agent,
        "_prefetch_jira_acceptance_criteria",
        new=AsyncMock(return_value=("No AC heading here", "- qa: added later", [])),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            qa_signoff_attachment={"filename": "qa-signoff.docx"},
            jira_issue_key="SCRUM-20",
            jira_validation={
                "metadata": {
                    "jira_description": "Short summary without an AC heading",
                }
            },
        )

    assert result.status == ValidationStatus.PASS
    assert result.metadata["ac_source"] == "llm"
    assert QAAcceptanceCriteriaExtract in captured["models"]
    assert QATestCaseExtract in captured["models"]
    assert "Hide Offerings when the flag is off." in captured["QALLMValidationOutput"]
    assert "SCRUM-20" in captured["QAAcceptanceCriteriaExtract"]


@pytest.mark.asyncio
async def test_qa_agent_errors_when_test_case_extract_fails():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = ("qa-signoff.docx", "Passed")
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(signoff_service=signoff_service, settings=settings)

    async def failing_tc_invoke(agent, *, user_message, response_model):
        if response_model is QATestCaseExtract:
            return None
        return _pass_output()

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=failing_tc_invoke,
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            environment="UAT",
            release_version="v1.0.0",
            qa_signoff_attachment={"filename": "qa-signoff.docx"},
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": ["Offerings dropdown works"],
                }
            },
        )

    assert result.status == ValidationStatus.ERROR
    assert any("test-case extract" in error for error in result.errors)


@pytest.mark.asyncio
async def test_qa_agent_overrides_false_pass_when_ac_is_omitted():
    signoff_service = MagicMock(spec=QASignoffService)
    signoff_service.load_qa_document_text.return_value = (
        "qa-signoff.docx",
        "TC-001 Remove Offerings — Passed",
    )
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(signoff_service=signoff_service, settings=settings)
    false_pass = QALLMValidationOutput(
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

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(false_pass),
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
                        "Remove the Offerings option from the dropdown menu.",
                        "Keep other dropdown options unchanged.",
                    ]
                }
            },
        )

    assert result.status == ValidationStatus.FAIL
    assert result.metadata["acceptance_criteria_coverage_percent"] == 50.0
    assert len(result.metadata["coverage_matrix"]) == 2
    assert result.metadata["coverage_matrix"][1]["coverage"] == "Not Covered"
    assert any("not fully covered" in error.lower() for error in result.errors)
