"""Structured LLM output for QA acceptance-criteria validation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.validation import ValidationStatus


class QAAcceptanceCriterion(BaseModel):
    ac_id: str
    text: str


class QAAcceptanceCriteriaExtract(BaseModel):
    acceptance_criteria: list[QAAcceptanceCriterion] = Field(default_factory=list)
    no_acceptance_criteria_found: bool = False


class QATestCase(BaseModel):
    test_case_id: str
    scenario: str = ""
    expected_result: str = ""
    status: str = ""


class QATestCaseExtract(BaseModel):
    test_cases: list[QATestCase] = Field(default_factory=list)


class QACoverageMatrixRow(BaseModel):
    ac_id: str
    acceptance_criterion: str
    test_cases: str = ""
    coverage: str
    test_result: str = ""
    evidence_reason: str = ""


class QADraftTest(BaseModel):
    ac_id: str
    suggested_path: str = "tests/test_generated.py"
    language: str = "python"
    test_code: str
    rationale: str = ""


class QADraftTestBundle(BaseModel):
    drafts: list[QADraftTest] = Field(default_factory=list)
    developer_instructions: str = (
        "Review these draft tests, commit the ones you accept to the PR, "
        "then create the release again so Lane 1 re-runs against the new SHA."
    )


class QAGeneratedTest(BaseModel):
    ac_id: str
    generated_test: str = ""
    test_file: str = "tests/test_generated.py"
    summary: str = ""
    reason: str = ""
    status: str = "FAIL"
    test_code: str = ""


class QAGeneratedTestBundle(BaseModel):
    tests: list[QAGeneratedTest] = Field(default_factory=list)


class QAGapReviewBundle(BaseModel):
    coverage_matrix: list[QACoverageMatrixRow] = Field(default_factory=list)
    review_notes: str = ""


class QALLMValidationOutput(BaseModel):
    status: ValidationStatus
    validation_summary: str = ""
    coverage_matrix: list[QACoverageMatrixRow] = Field(default_factory=list)
    acceptance_criteria_coverage_percent: float | None = None
    passed_acceptance_criteria_percent: float | None = None
    no_acceptance_criteria_found: bool = False
    errors: list[str] = Field(default_factory=list)
