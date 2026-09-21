"""Jira field extraction tests."""

from app.utils.jira_fields import (
    extract_acceptance_criteria,
    extract_issue_comments,
    extract_issue_description,
)


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


def test_extract_acceptance_criteria_from_github_checkboxes():
    description = """
## Acceptance criteria
- [ ] All offering cards are clickable.
- [x] Clicking MCP Factory navigates to the correct Demo URL.

## Test notes
Compare before and after.
"""
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "All offering cards are clickable.",
        "Clicking MCP Factory navigates to the correct Demo URL.",
    ]


def test_extract_acceptance_criteria_keeps_jira_bullets_separated_by_blank_lines():
    description = """
Make What's New cards clickable.

Acceptance Criteria:

- Cards with a Demo URL must be clickable

- MCP Factory opens its Demo URL

- Cards without a URL stay non-clickable

Notes:
Do not change card styling.
"""
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "Cards with a Demo URL must be clickable",
        "MCP Factory opens its Demo URL",
        "Cards without a URL stay non-clickable",
    ]


def test_extract_acceptance_criteria_splits_jira_paragraph_sentences():
    description = """
Acceptance Criteria:
All offering cards are clickable.
Clicking MCP Factory navigates to the correct Demo URL.
Clicking Competitor Intelligence navigates to the correct Demo URL.
Clicking Account Intelligence navigates to the correct Demo URL.
Existing card styling and layout remain unchanged.
"""
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "All offering cards are clickable.",
        "Clicking MCP Factory navigates to the correct Demo URL.",
        "Clicking Competitor Intelligence navigates to the correct Demo URL.",
        "Clicking Account Intelligence navigates to the correct Demo URL.",
        "Existing card styling and layout remain unchanged.",
    ]


def test_extract_acceptance_criteria_splits_same_line_jira_sentences():
    description = (
        "Acceptance Criteria: All offering cards are clickable. "
        "Clicking MCP Factory navigates to the correct Demo URL. "
        "Existing card styling and layout remain unchanged."
    )
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "All offering cards are clickable.",
        "Clicking MCP Factory navigates to the correct Demo URL.",
        "Existing card styling and layout remain unchanged.",
    ]


def test_extract_acceptance_criteria_keeps_wrapped_github_checkbox_as_one():
    description = """
## Acceptance criteria
- [ ] All offering cards are clickable
  when a Demo URL is configured.
- [x] Clicking MCP Factory navigates to the correct Demo URL.

## Test notes
Ignore this line.
"""
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "All offering cards are clickable when a Demo URL is configured.",
        "Clicking MCP Factory navigates to the correct Demo URL.",
    ]


def test_extract_issue_description_preserves_adf_list_items():
    payload = {
        "fields": {
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "attrs": {"level": 2},
                        "content": [{"type": "text", "text": "Acceptance Criteria"}],
                    },
                    {
                        "type": "bulletList",
                        "content": [
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "Cards with a Demo URL must be clickable",
                                            }
                                        ],
                                    }
                                ],
                            },
                            {
                                "type": "listItem",
                                "content": [
                                    {
                                        "type": "paragraph",
                                        "content": [
                                            {
                                                "type": "text",
                                                "text": "MCP Factory opens its Demo URL",
                                            }
                                        ],
                                    }
                                ],
                            },
                        ],
                    },
                ],
            }
        }
    }
    description = extract_issue_description(payload)
    assert description is not None
    criteria = extract_acceptance_criteria(description)
    assert criteria == [
        "Cards with a Demo URL must be clickable",
        "MCP Factory opens its Demo URL",
    ]


def test_extract_issue_description_splits_adf_paragraph_criteria():
    payload = {
        "fields": {
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "heading",
                        "content": [{"type": "text", "text": "Acceptance Criteria"}],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {"type": "text", "text": "All offering cards are clickable."},
                        ],
                    },
                    {
                        "type": "paragraph",
                        "content": [
                            {
                                "type": "text",
                                "text": "Clicking MCP Factory navigates to the correct Demo URL.",
                            },
                        ],
                    },
                ],
            }
        }
    }
    description = extract_issue_description(payload)
    assert description is not None
    assert extract_acceptance_criteria(description) == [
        "All offering cards are clickable.",
        "Clicking MCP Factory navigates to the correct Demo URL.",
    ]


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
