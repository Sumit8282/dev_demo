"""Deterministic QA coverage post-processing — code owns the release gate."""

from __future__ import annotations

import re
from typing import Iterable

from app.models.qa_llm_validation import (
    QAAcceptanceCriterion,
    QACoverageMatrixRow,
    QALLMValidationOutput,
    QATestCase,
)
from app.models.qa_signoff import SignOffRequest
from app.models.validation import ValidationStatus

FULLY_COVERED = "Fully Covered"
PARTIALLY_COVERED = "Partially Covered"
NOT_COVERED = "Not Covered"
COVERED_BUT_FAILED = "Covered but Failed"
UNABLE_TO_DETERMINE = "Unable to Determine"

COVERAGE_VALUES = (
    FULLY_COVERED,
    PARTIALLY_COVERED,
    NOT_COVERED,
    COVERED_BUT_FAILED,
    UNABLE_TO_DETERMINE,
)

_COVERAGE_ALIASES = {
    "fully covered": FULLY_COVERED,
    "fully_covered": FULLY_COVERED,
    "complete": FULLY_COVERED,
    "covered": FULLY_COVERED,
    "partially covered": PARTIALLY_COVERED,
    "partially_covered": PARTIALLY_COVERED,
    "partial": PARTIALLY_COVERED,
    "not covered": NOT_COVERED,
    "not_covered": NOT_COVERED,
    "uncovered": NOT_COVERED,
    "none": NOT_COVERED,
    "covered but failed": COVERED_BUT_FAILED,
    "covered_but_failed": COVERED_BUT_FAILED,
    "failed": COVERED_BUT_FAILED,
    "fail": COVERED_BUT_FAILED,
    "unable to determine": UNABLE_TO_DETERMINE,
    "unable_to_determine": UNABLE_TO_DETERMINE,
    "unknown": UNABLE_TO_DETERMINE,
    "insufficient": UNABLE_TO_DETERMINE,
}

_PASS_RESULTS = {"pass", "passed", "successful", "success", "ok"}
_FAIL_RESULTS = {"fail", "failed", "failure"}
_INCOMPLETE_RESULTS = {
    "not executed",
    "not run",
    "blocked",
    "pending",
    "planned",
    "",
    "n/a",
    "na",
    "unclear",
}

_TC_ID = re.compile(r"\b(TC[-_ ]?\d{1,4})\b", re.IGNORECASE)
_STATUS_WORD = re.compile(
    r"\b(passed|pass|failed|fail|not executed|not run|blocked|pending|successful|success)\b",
    re.IGNORECASE,
)
_AC_ID = re.compile(r"AC-(\d+)", re.IGNORECASE)


def normalize_coverage(value: str | None) -> str:
    text = " ".join(str(value or "").replace("_", " ").split()).strip().lower()
    if text in _COVERAGE_ALIASES:
        return _COVERAGE_ALIASES[text]
    for label in COVERAGE_VALUES:
        if text == label.lower():
            return label
    return UNABLE_TO_DETERMINE if text else NOT_COVERED


def normalize_test_result(value: str | None) -> str:
    text = " ".join(str(value or "").replace("_", " ").split()).strip().lower()
    if text in _PASS_RESULTS:
        return "Pass"
    if text in _FAIL_RESULTS:
        return "Failed"
    if text in {"not executed", "not run"}:
        return "Not Executed"
    if text == "blocked":
        return "Blocked"
    if text in {"pending", "planned"}:
        return "Pending"
    if text in {"", "n/a", "na"}:
        return "N/A"
    if text:
        return str(value).strip()
    return "N/A"


def is_successful_result(value: str | None) -> bool:
    return normalize_test_result(value) == "Pass"


def normalize_test_case_id(value: str | None) -> str:
    match = _TC_ID.search(str(value or ""))
    if not match:
        return str(value or "").strip().upper()
    raw = re.sub(r"[\s_]+", "-", match.group(1).upper())
    digits = re.sub(r"\D", "", raw)
    return f"TC-{int(digits):03d}" if digits else raw


def extract_test_case_ids(value: str | None) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for match in _TC_ID.finditer(str(value or "")):
        tc_id = normalize_test_case_id(match.group(1))
        if tc_id and tc_id not in seen:
            seen.add(tc_id)
            found.append(tc_id)
    return found


def extract_test_cases_from_text(text: str | None) -> list[QATestCase]:
    """Pull TC-n rows out of QA document text (tables become pipe-separated lines)."""
    cases: list[QATestCase] = []
    seen: set[str] = set()
    for line in str(text or "").splitlines():
        match = _TC_ID.search(line)
        if not match:
            continue
        tc_id = normalize_test_case_id(match.group(1))
        if not tc_id or tc_id in seen:
            continue
        seen.add(tc_id)
        status_match = _STATUS_WORD.search(line)
        status = normalize_test_result(status_match.group(0)) if status_match else ""
        parts = [part.strip() for part in line.split("|") if part.strip()]
        scenario = ""
        expected = ""
        if len(parts) >= 2:
            remainder = [part for part in parts if not _TC_ID.fullmatch(part)]
            if remainder:
                scenario = remainder[0]
            if len(remainder) >= 2:
                expected = remainder[1]
        else:
            scenario = _STATUS_WORD.sub("", _TC_ID.sub("", line))
            scenario = re.sub(r"[\-—|:]+", " ", scenario).strip(" .")
        cases.append(
            QATestCase(
                test_case_id=tc_id,
                scenario=scenario,
                expected_result=expected,
                status=status,
            )
        )
    return cases


def merge_test_cases(
    code_cases: Iterable[QATestCase],
    llm_cases: Iterable[QATestCase],
) -> list[QATestCase]:
    merged: dict[str, QATestCase] = {}
    for source in (code_cases, llm_cases):
        for item in source:
            key = normalize_test_case_id(item.test_case_id)
            if not key:
                continue
            existing = merged.get(key)
            if existing is None:
                merged[key] = QATestCase(
                    test_case_id=key,
                    scenario=item.scenario.strip(),
                    expected_result=item.expected_result.strip(),
                    status=normalize_test_result(item.status) if item.status else "",
                )
                continue
            merged[key] = QATestCase(
                test_case_id=key,
                scenario=item.scenario.strip() or existing.scenario,
                expected_result=item.expected_result.strip() or existing.expected_result,
                status=(
                    normalize_test_result(item.status)
                    if item.status
                    else existing.status
                ),
            )
    return list(merged.values())


def format_signoff_facts(signoff: SignOffRequest | None) -> str:
    if signoff is None:
        return (
            "No structured sign-off fields were parsed. "
            "Use the extracted test cases only."
        )
    bugs = "Yes" if signoff.open_blocker_or_critical_bugs else "No"
    summary = (signoff.summary or "").strip() or "(none)"
    return "\n".join(
        [
            f"- Test plan status: {signoff.test_plan_status}",
            f"- Open blocker or critical bugs: {bugs}",
            f"- Summary: {summary}",
        ]
    )


def apply_coverage_constraints(
    llm_result: QALLMValidationOutput,
    *,
    acceptance_criteria: list[QAAcceptanceCriterion],
    test_cases: list[QATestCase],
    signoff: SignOffRequest | None = None,
) -> QALLMValidationOutput:
    """Force one matrix row per AC, recompute %, and own PASS/FAIL."""
    if not acceptance_criteria:
        llm_result.coverage_matrix = []
        llm_result.acceptance_criteria_coverage_percent = None
        llm_result.passed_acceptance_criteria_percent = None
        llm_result.no_acceptance_criteria_found = True
        llm_result.status = ValidationStatus.FAIL
        llm_result.errors = [
            error
            for error in llm_result.errors
            if error
        ] or ["No explicit Acceptance Criteria found in JIRA."]
        llm_result.validation_summary = _sync_summary(
            llm_result.validation_summary,
            ValidationStatus.FAIL,
        )
        return llm_result

    tests_by_id = {
        normalize_test_case_id(item.test_case_id): item
        for item in test_cases
        if item.test_case_id
    }
    rows_by_id = _index_llm_rows(llm_result.coverage_matrix)
    rebuilt: list[QACoverageMatrixRow] = []

    for criterion in acceptance_criteria:
        ac_id = _normalize_ac_id(criterion.ac_id) or criterion.ac_id
        row = rows_by_id.get(ac_id) or QACoverageMatrixRow(
            ac_id=ac_id,
            acceptance_criterion=criterion.text,
            test_cases="",
            coverage=NOT_COVERED,
            test_result="N/A",
            evidence_reason="Mapper omitted this criterion.",
        )
        rebuilt.append(
            _reconcile_row(
                row,
                criterion=criterion,
                tests_by_id=tests_by_id,
            )
        )

    llm_result.coverage_matrix = rebuilt
    llm_result.no_acceptance_criteria_found = False

    total = len(rebuilt)
    fully_covered = sum(1 for row in rebuilt if row.coverage == FULLY_COVERED)
    fully_passed = sum(
        1
        for row in rebuilt
        if row.coverage == FULLY_COVERED and is_successful_result(row.test_result)
    )
    llm_result.acceptance_criteria_coverage_percent = round(
        (fully_covered / total) * 100, 1
    )
    llm_result.passed_acceptance_criteria_percent = round(
        (fully_passed / total) * 100, 1
    )

    errors = [
        error
        for error in llm_result.errors
        if not _is_missing_ac_error(error)
    ]
    blocking = [row for row in rebuilt if row.coverage != FULLY_COVERED]
    if blocking:
        ids = ", ".join(row.ac_id for row in blocking[:8])
        message = f"One or more acceptance criteria are not fully covered: {ids}."
        if not any("not fully covered" in error.lower() for error in errors):
            errors.append(message)

    if signoff is not None:
        if signoff.test_plan_status.strip().lower() != "passed":
            errors.append(
                f"QA test plan status is {signoff.test_plan_status!r}, not Passed."
            )
        if signoff.open_blocker_or_critical_bugs:
            errors.append("QA document reports open blocker or critical bugs.")

    all_fully_covered = not blocking
    signoff_ok = not (
        signoff is not None
        and (
            signoff.test_plan_status.strip().lower() != "passed"
            or signoff.open_blocker_or_critical_bugs
        )
    )
    if all_fully_covered and signoff_ok:
        llm_result.status = ValidationStatus.PASS
        llm_result.errors = []
    else:
        llm_result.status = ValidationStatus.FAIL
        llm_result.errors = errors or ["QA acceptance-criteria validation failed."]

    llm_result.validation_summary = _sync_summary(
        llm_result.validation_summary,
        llm_result.status,
    )
    return llm_result


def _reconcile_row(
    row: QACoverageMatrixRow,
    *,
    criterion: QAAcceptanceCriterion,
    tests_by_id: dict[str, QATestCase],
) -> QACoverageMatrixRow:
    ac_id = _normalize_ac_id(criterion.ac_id) or criterion.ac_id
    coverage = normalize_coverage(row.coverage)
    mapped_ids = extract_test_case_ids(row.test_cases)
    mapped_tests = [tests_by_id[tc_id] for tc_id in mapped_ids if tc_id in tests_by_id]
    unknown_ids = [tc_id for tc_id in mapped_ids if tc_id not in tests_by_id]

    evidence = row.evidence_reason.strip()
    test_result = normalize_test_result(row.test_result)

    if not tests_by_id:
        if coverage in {FULLY_COVERED, PARTIALLY_COVERED, COVERED_BUT_FAILED}:
            coverage = NOT_COVERED
            test_result = "N/A"
            evidence = evidence or "No test cases were extracted from the QA document."
    elif coverage == FULLY_COVERED and not mapped_tests:
        coverage = UNABLE_TO_DETERMINE if mapped_ids else NOT_COVERED
        evidence = evidence or (
            "Fully Covered requires a mapped test case that exists in the extracted list."
        )
    elif mapped_ids and unknown_ids and not mapped_tests:
        coverage = UNABLE_TO_DETERMINE
        evidence = evidence or (
            "Mapped test case IDs were not present in the extracted test list."
        )
    elif mapped_tests:
        statuses = [normalize_test_result(item.status) or test_result for item in mapped_tests]
        if any(status == "Failed" for status in statuses):
            if coverage == FULLY_COVERED:
                coverage = COVERED_BUT_FAILED
            test_result = "Failed"
        elif all(status == "Pass" for status in statuses):
            test_result = "Pass"
            if coverage == PARTIALLY_COVERED:
                coverage = FULLY_COVERED
                evidence = evidence or "Mapped test cases passed."
        elif any(status.lower() in _INCOMPLETE_RESULTS or status in {
            "Not Executed",
            "Blocked",
            "Pending",
            "N/A",
        } for status in statuses):
            if coverage == FULLY_COVERED:
                coverage = UNABLE_TO_DETERMINE
            if not test_result or test_result == "Pass":
                test_result = next(
                    (
                        status
                        for status in statuses
                        if status not in {"Pass", ""}
                    ),
                    "N/A",
                )

    if coverage == FULLY_COVERED and not is_successful_result(test_result):
        coverage = (
            COVERED_BUT_FAILED if test_result == "Failed" else UNABLE_TO_DETERMINE
        )

    return QACoverageMatrixRow(
        ac_id=ac_id,
        acceptance_criterion=criterion.text,
        test_cases=row.test_cases.strip(),
        coverage=coverage,
        test_result=test_result,
        evidence_reason=evidence,
    )


def _index_llm_rows(
    rows: list[QACoverageMatrixRow],
) -> dict[str, QACoverageMatrixRow]:
    indexed: dict[str, QACoverageMatrixRow] = {}
    for row in rows:
        ac_id = _normalize_ac_id(row.ac_id)
        if ac_id and ac_id not in indexed:
            indexed[ac_id] = row
    return indexed


def _normalize_ac_id(value: str | None) -> str:
    match = _AC_ID.search(str(value or ""))
    if not match:
        return str(value or "").strip().upper()
    return f"AC-{int(match.group(1)):02d}"


def _is_missing_ac_error(error: str) -> bool:
    lowered = error.lower()
    return any(
        marker in lowered
        for marker in (
            "no explicit acceptance criteria",
            "missing explicit acceptance criteria",
            "no acceptance criteria found",
        )
    )


def _sync_summary(summary: str, status: ValidationStatus) -> str:
    text = (summary or "").strip()
    if not text:
        return (
            "## QA Validation Summary\n\n"
            f"**Overall Status:** {status.value}"
        )
    updated, count = re.subn(
        r"\*\*Overall Status:\*\*\s*(PASS|FAIL|ERROR)",
        f"**Overall Status:** {status.value}",
        text,
        count=1,
        flags=re.IGNORECASE,
    )
    if count:
        return updated
    return f"{text}\n\n**Overall Status:** {status.value}"
