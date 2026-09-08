"""Deterministic QA coverage post-processor tests."""

from app.models.qa_llm_validation import (
    QAAcceptanceCriterion,
    QACoverageMatrixRow,
    QALLMValidationOutput,
    QATestCase,
)
from app.models.qa_signoff import SignOffRequest
from app.models.validation import ValidationStatus
from app.services.qa_coverage_evaluator import (
    apply_coverage_constraints,
    extract_test_cases_from_text,
    merge_test_cases,
    normalize_coverage,
    normalize_test_result,
)


def _criteria(*texts: str) -> list[QAAcceptanceCriterion]:
    return [
        QAAcceptanceCriterion(ac_id=f"AC-{index:02d}", text=text)
        for index, text in enumerate(texts, start=1)
    ]


def test_normalize_coverage_aliases():
    assert normalize_coverage("fully_covered") == "Fully Covered"
    assert normalize_coverage("partial") == "Partially Covered"
    assert normalize_coverage("unknown") == "Unable to Determine"


def test_normalize_test_result_aliases():
    assert normalize_test_result("successful") == "Pass"
    assert normalize_test_result("not run") == "Not Executed"
    assert normalize_test_result("") == "N/A"


def test_extract_test_cases_from_table_lines():
    text = (
        "TC-001 | Remove Offerings from dropdown | Option is gone | Passed\n"
        "Summary: verified in UAT\n"
        "TC-2 Confirm layout — Failed"
    )
    cases = extract_test_cases_from_text(text)
    assert [item.test_case_id for item in cases] == ["TC-001", "TC-002"]
    assert cases[0].status == "Pass"
    assert "Remove Offerings" in cases[0].scenario
    assert cases[1].status == "Failed"


def test_merge_test_cases_prefers_non_empty_llm_fields():
    merged = merge_test_cases(
        [QATestCase(test_case_id="TC-1", scenario="from code", status="Passed")],
        [QATestCase(test_case_id="TC-001", expected_result="hidden", status="")],
    )
    assert len(merged) == 1
    assert merged[0].test_case_id == "TC-001"
    assert merged[0].scenario == "from code"
    assert merged[0].expected_result == "hidden"
    assert merged[0].status == "Pass"


def test_apply_coverage_constraints_fills_omitted_ac_and_fails():
    result = apply_coverage_constraints(
        QALLMValidationOutput(
            status=ValidationStatus.PASS,
            coverage_matrix=[
                QACoverageMatrixRow(
                    ac_id="AC-01",
                    acceptance_criterion="Remove Offerings",
                    test_cases="TC-001",
                    coverage="Fully Covered",
                    test_result="Pass",
                )
            ],
            acceptance_criteria_coverage_percent=100,
            passed_acceptance_criteria_percent=100,
        ),
        acceptance_criteria=_criteria("Remove Offerings", "Keep layout"),
        test_cases=[QATestCase(test_case_id="TC-001", scenario="Remove", status="Pass")],
    )
    assert result.status == ValidationStatus.FAIL
    assert len(result.coverage_matrix) == 2
    assert result.coverage_matrix[1].coverage == "Not Covered"
    assert result.acceptance_criteria_coverage_percent == 50.0
    assert result.no_acceptance_criteria_found is False


def test_apply_coverage_constraints_drops_invented_ac_and_can_pass():
    result = apply_coverage_constraints(
        QALLMValidationOutput(
            status=ValidationStatus.FAIL,
            coverage_matrix=[
                QACoverageMatrixRow(
                    ac_id="AC-01",
                    acceptance_criterion="Remove Offerings",
                    test_cases="TC-001",
                    coverage="Fully Covered",
                    test_result="Pass",
                ),
                QACoverageMatrixRow(
                    ac_id="AC-07",
                    acceptance_criterion="Cross-browser screenshots",
                    test_cases="None",
                    coverage="Not Covered",
                    test_result="N/A",
                ),
            ],
            errors=["AC-07 missing screenshots"],
        ),
        acceptance_criteria=_criteria("Remove Offerings"),
        test_cases=[QATestCase(test_case_id="TC-001", scenario="Remove", status="Passed")],
    )
    assert result.status == ValidationStatus.PASS
    assert [row.ac_id for row in result.coverage_matrix] == ["AC-01"]
    assert result.errors == []
    assert result.acceptance_criteria_coverage_percent == 100.0


def test_apply_coverage_constraints_downgrades_failed_test():
    result = apply_coverage_constraints(
        QALLMValidationOutput(
            status=ValidationStatus.PASS,
            coverage_matrix=[
                QACoverageMatrixRow(
                    ac_id="AC-01",
                    acceptance_criterion="Remove Offerings",
                    test_cases="TC-001",
                    coverage="Fully Covered",
                    test_result="Pass",
                )
            ],
        ),
        acceptance_criteria=_criteria("Remove Offerings"),
        test_cases=[QATestCase(test_case_id="TC-001", scenario="Remove", status="Failed")],
    )
    assert result.status == ValidationStatus.FAIL
    assert result.coverage_matrix[0].coverage == "Covered but Failed"
    assert result.coverage_matrix[0].test_result == "Failed"


def test_apply_coverage_constraints_signoff_blockers_force_fail():
    result = apply_coverage_constraints(
        QALLMValidationOutput(
            status=ValidationStatus.PASS,
            coverage_matrix=[
                QACoverageMatrixRow(
                    ac_id="AC-01",
                    acceptance_criterion="Remove Offerings",
                    test_cases="TC-001",
                    coverage="Fully Covered",
                    test_result="Pass",
                )
            ],
        ),
        acceptance_criteria=_criteria("Remove Offerings"),
        test_cases=[QATestCase(test_case_id="TC-001", scenario="Remove", status="Pass")],
        signoff=SignOffRequest(
            pr_title="SCRUM-6",
            test_plan_status="Failed",
            open_blocker_or_critical_bugs=True,
        ),
    )
    assert result.status == ValidationStatus.FAIL
    assert any("test plan status" in error.lower() for error in result.errors)
    assert any("blocker" in error.lower() for error in result.errors)


def test_apply_coverage_constraints_rejects_fully_covered_without_mapped_test():
    result = apply_coverage_constraints(
        QALLMValidationOutput(
            status=ValidationStatus.PASS,
            coverage_matrix=[
                QACoverageMatrixRow(
                    ac_id="AC-01",
                    acceptance_criterion="Remove Offerings",
                    test_cases="",
                    coverage="Fully Covered",
                    test_result="Pass",
                )
            ],
        ),
        acceptance_criteria=_criteria("Remove Offerings"),
        test_cases=[QATestCase(test_case_id="TC-001", scenario="Unrelated", status="Pass")],
    )
    assert result.status == ValidationStatus.FAIL
    assert result.coverage_matrix[0].coverage == "Not Covered"


def test_apply_coverage_constraints_empty_acs():
    result = apply_coverage_constraints(
        QALLMValidationOutput(status=ValidationStatus.PASS),
        acceptance_criteria=[],
        test_cases=[],
    )
    assert result.status == ValidationStatus.FAIL
    assert result.no_acceptance_criteria_found is True
    assert result.acceptance_criteria_coverage_percent is None
