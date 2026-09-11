"""QA agent unit tests."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.qa_agent import QAAgent
from app.models.qa_llm_validation import (
    QAAcceptanceCriteriaExtract,
    QAAcceptanceCriterion,
    QACoverageMatrixRow,
    QADraftTest,
    QADraftTestBundle,
    QAGeneratedTest,
    QAGeneratedTestBundle,
    QALLMValidationOutput,
    QATestCase,
    QATestCaseExtract,
)
from app.models.validation import ValidationStatus
from app.services.qa_signoff_service import QASignoffService


async def _passthrough_generated_run(tests, **kwargs):
    owner = str(kwargs.get("owner") or "")
    repo = str(kwargs.get("repo") or "")
    sha = str(kwargs.get("sha") or "")
    prefix = f"Ran against GitHub {owner}/{repo}@{sha}. " if owner and repo and sha else ""
    for item in tests:
        item.status = "PASS"
        item.reason = prefix + (item.reason or "Pytest completed successfully.")
    return tests


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
        if response_model is QADraftTestBundle:
            return QADraftTestBundle(
                drafts=[
                    QADraftTest(
                        ac_id="AC-02",
                        suggested_path="tests/test_layout.py",
                        language="python",
                        test_code="def test_layout():\n    assert True",
                    )
                ]
            )
        if response_model is QAGeneratedTestBundle:
            return QAGeneratedTestBundle(
                tests=[
                    QAGeneratedTest(
                        ac_id="AC-01",
                        generated_test="test_offerings_dropdown_navigates",
                        test_file="tests/test_offerings.py",
                        summary="Checks offerings dropdown navigation.",
                        test_code="def test_offerings_dropdown_navigates():\n    assert True\n",
                    )
                ]
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
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
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
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
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
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
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
        agent, "build_generated_test_agent", return_value=MagicMock()
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
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
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
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
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


def _pr_github_validation():
    return {
        "metadata": {
            "owner": "acme",
            "repo": "portal",
            "pr_title": "Remove Offerings",
            "head_sha": "abc123456789",
            "changed_files": [
                {
                    "filename": "tests/test_offerings.py",
                    "status": "added",
                    "patch": "+def test_remove_offerings():\n+    assert True\n",
                }
            ],
        }
    }


@pytest.mark.asyncio
async def test_qa_agent_pr_tests_lane1_pass():
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(settings=settings)
    agent._generated_test_runner.run = _passthrough_generated_run

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(_pass_output()),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            qa_mode="pr_tests",
            environment="UAT",
            release_version="v1.0.0",
            pr_title="Remove Offerings",
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": ["Offerings dropdown navigates correctly"],
                }
            },
            github_validation=_pr_github_validation(),
        )

    assert result.status == ValidationStatus.PASS
    assert result.metadata["qa_mode"] == "pr_tests"
    assert result.metadata["qa_lane"] == 1
    assert result.metadata["head_sha"] == "abc123456789"
    assert "tests/test_offerings.py" in result.metadata["pr_test_files"]
    assert result.metadata["repo_test_file_count"] == 0
    assert result.metadata["generated_tests"]
    assert result.metadata["generated_tests"][0]["status"] == "PASS"
    assert result.metadata["generated_tests_repo"] == "acme/portal"
    assert result.metadata["generated_tests_sha"] == "abc123456789"
    assert "acme/portal@abc123456789" in result.metadata["generated_tests"][0]["reason"]
    assert "lane2_draft_tests" not in result.metadata


@pytest.mark.asyncio
async def test_qa_agent_pr_tests_lane2_drafts_when_coverage_fails():
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(settings=settings)
    agent._generated_test_runner.run = _passthrough_generated_run
    false_pass = QALLMValidationOutput(
        status=ValidationStatus.PASS,
        coverage_matrix=[
            QACoverageMatrixRow(
                ac_id="AC-01",
                acceptance_criterion="Offerings dropdown navigates correctly",
                test_cases="TC-001",
                coverage="Fully Covered",
                test_result="Pass",
            )
        ],
    )

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_lane2_draft_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(false_pass),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            qa_mode="pr_tests",
            environment="UAT",
            release_version="v1.0.0",
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": [
                        "Offerings dropdown navigates correctly",
                        "Keep other dropdown options unchanged.",
                    ]
                }
            },
            github_validation=_pr_github_validation(),
        )

    assert result.status == ValidationStatus.FAIL
    assert result.metadata["qa_lane"] == 2
    assert result.metadata["lane2_optional"] is True
    assert result.metadata["lane2_draft_tests"]
    assert "Lane 2" in result.metadata["lane2_comment"]


class _FakeRepoEvidence:
    def __init__(self, payload: dict):
        self.payload = payload

    async def collect_lane1_evidence(self, _github_validation):
        return self.payload


@pytest.mark.asyncio
async def test_qa_agent_pr_tests_uses_writeup_and_repo_tests():
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(
        settings=settings,
        repo_evidence_client=_FakeRepoEvidence(
            {
                "repo_test_files": [
                    {
                        "filename": "tests/test_offerings.py",
                        "status": "existing",
                        "patch": "def test_remove_offerings():\n    assert True",
                        "source": "repo",
                    }
                ],
                "ci_status": "success",
            }
        ),
    )
    agent._generated_test_runner.run = _passthrough_generated_run

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(_pass_output()),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            qa_mode="pr_tests",
            environment="UAT",
            release_version="v1.0.0",
            pr_title="Remove Offerings",
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": ["Offerings dropdown navigates correctly"],
                }
            },
            github_validation={
                "metadata": {
                    "owner": "acme",
                    "repo": "app",
                    "head_sha": "abc123456789",
                    "pr_description": "## Testing\n- Verified offerings dropdown navigates correctly",
                    "changed_files": [
                        {"filename": "app/offerings.py", "status": "modified", "patch": "+x"}
                    ],
                }
            },
        )

    assert result.status == ValidationStatus.PASS
    assert result.metadata["testing_writeup_used"] is True
    assert "tests/test_offerings.py" in result.metadata["repo_test_files"]
    assert result.metadata["ci_status"] == "success"


@pytest.mark.asyncio
async def test_qa_agent_pr_tests_fails_when_ci_failed():
    settings = MagicMock()
    settings.llm_enabled = True
    agent = QAAgent(
        settings=settings,
        repo_evidence_client=_FakeRepoEvidence(
            {"repo_test_files": [], "ci_status": "failure"}
        ),
    )
    agent._generated_test_runner.run = _passthrough_generated_run

    with patch.object(agent, "build_langchain_agent", return_value=MagicMock()), patch.object(
        agent, "build_tc_extract_agent", return_value=MagicMock()
    ), patch.object(
        agent, "build_generated_test_agent", return_value=MagicMock()
    ), patch(
        "app.agents.qa_agent.invoke_structured_agent",
        new=_hybrid_invoke(_pass_output()),
    ):
        result = await agent.validate_async(
            release_id="REL-1",
            qa_signoff_required=True,
            qa_mode="pr_tests",
            environment="UAT",
            release_version="v1.0.0",
            jira_issue_key="SCRUM-6",
            jira_validation={
                "metadata": {
                    "acceptance_criteria": ["Offerings dropdown navigates correctly"],
                }
            },
            github_validation=_pr_github_validation(),
        )

    assert result.status == ValidationStatus.FAIL
    assert any("did not pass" in error.lower() for error in result.errors)
