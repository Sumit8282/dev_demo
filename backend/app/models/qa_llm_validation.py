"""Structured LLM output for QA acceptance-criteria validation."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.models.validation import ValidationStatus


class QACoverageMatrixRow(BaseModel):
    ac_id: str
    acceptance_criterion: str
    test_cases: str = ""
    coverage: str
    test_result: str = ""
    evidence_reason: str = ""


class QALLMValidationOutput(BaseModel):
    status: ValidationStatus
    validation_summary: str = ""
    coverage_matrix: list[QACoverageMatrixRow] = Field(default_factory=list)
    acceptance_criteria_coverage_percent: float | None = None
    passed_acceptance_criteria_percent: float | None = None
    no_acceptance_criteria_found: bool = False
    errors: list[str] = Field(default_factory=list)
