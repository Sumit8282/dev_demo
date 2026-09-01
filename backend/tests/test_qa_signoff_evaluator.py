"""QA sign-off evaluator tests."""

import pytest

from app.models.qa_signoff import SignOffRequest
from app.services.qa_signoff_evaluator import (
    evaluate_signoff,
    filename_matches_pr_title,
    titles_match,
)


def test_evaluate_signoff_approved():
    request = SignOffRequest(
        pr_title="SCRUM-6: Implement offerings",
        test_plan_status="Passed",
        open_blocker_or_critical_bugs=False,
        pr_tags=["regression"],
        summary="All tests passed.",
    )
    result = evaluate_signoff(request)
    assert result.approved is True
    assert "QA sign-off" in result.pr_tags


def test_evaluate_signoff_failed_status():
    request = SignOffRequest(
        pr_title="SCRUM-6: Implement offerings",
        test_plan_status="Failed",
        open_blocker_or_critical_bugs=False,
    )
    result = evaluate_signoff(request)
    assert result.approved is False
    assert "not Passed" in result.reason


def test_evaluate_signoff_open_bugs():
    request = SignOffRequest(
        pr_title="SCRUM-6: Implement offerings",
        test_plan_status="Passed",
        open_blocker_or_critical_bugs=True,
    )
    result = evaluate_signoff(request)
    assert result.approved is False


def test_titles_match_ignores_punctuation():
    assert titles_match("SCRUM-6: Implement offerings", "SCRUM-6 Implement offerings")


def test_filename_matches_pr_title():
    assert filename_matches_pr_title("SCRUM-6 Implement offerings.docx", "SCRUM-6: Implement offerings")
    assert not filename_matches_pr_title("wrong-name.docx", "SCRUM-6: Implement offerings")
