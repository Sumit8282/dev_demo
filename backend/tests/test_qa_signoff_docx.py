"""QA sign-off attachment parsing tests."""

import json

import pytest

from app.services.qa_signoff_docx import parse_signoff_attachment


def test_parse_signoff_json_attachment():
    payload = {
        "pr_title": "SCRUM-6: Implement offerings",
        "test_plan_status": "Passed",
        "open_blocker_or_critical_bugs": False,
        "pr_tags": ["backend"],
        "summary": "Regression passed.",
    }
    content = json.dumps(payload).encode("utf-8")
    request = parse_signoff_attachment(content, "SCRUM-6 Implement offerings.json")
    assert request.pr_title == "SCRUM-6: Implement offerings"
    assert request.test_plan_status == "Passed"


def test_parse_signoff_rejects_pdf():
    with pytest.raises(ValueError, match=".docx or .json"):
        parse_signoff_attachment(b"%PDF", "signoff.pdf")


def test_parse_signoff_docx_label_on_next_line_layout():
    """Word table/form layouts often place labels and values on separate lines."""
    text = "\n".join(
        [
            "PR Title",
            "Implement SCRUM-6 offerings",
            "Test Plan Status",
            "Passed",
            "Open Blocker or Critical Bugs",
            "No",
            "PR Tags",
            "regression, offerings",
            "Summary",
            "Verified the Offerings dropdown navigation fix in UAT.",
        ]
    )
    from app.services.qa_signoff_docx import build_signoff_request_from_docx

    request = build_signoff_request_from_docx(text)
    assert request.pr_title == "Implement SCRUM-6 offerings"
    assert request.test_plan_status == "Passed"
    assert request.open_blocker_or_critical_bugs is False
    assert request.pr_tags == ["regression", "offerings"]
