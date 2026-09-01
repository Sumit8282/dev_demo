"""Jira field extraction tests."""

from app.utils.jira_fields import extract_acceptance_criteria, extract_issue_comments


def test_extract_acceptance_criteria_from_bullets():
    description = """
User story for dropdown cleanup.

Acceptance Criteria:
- Remove Offerings option from dropdown
- Keep other options unchanged
- Maintain dropdown layout and styling
"""
    criteria = extract_acceptance_criteria(description)
    assert len(criteria) == 3
    assert criteria[0].startswith("Remove Offerings")


def test_extract_issue_comments():
    payload = {
        "fields": {
            "comment": {
                "comments": [
                    {
                        "author": {"displayName": "Dev User"},
                        "body": {
                            "type": "doc",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [{"type": "text", "text": "Ready for L3"}],
                                }
                            ],
                        },
                    }
                ]
            }
        }
    }
    comments = extract_issue_comments(payload)
    assert len(comments) == 1
    assert comments[0]["author"] == "Dev User"
    assert "Ready for L3" in comments[0]["body"]
