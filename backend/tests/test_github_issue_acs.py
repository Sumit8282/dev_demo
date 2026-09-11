"""GitHub issue acceptance-criteria collection tests."""

from app.services.github_issue_acs import (
    collect_github_issue_acceptance_criteria,
    criteria_from_github_issue,
)


def test_criteria_from_github_issue_uses_checkbox_section():
    criteria = criteria_from_github_issue(
        number=12,
        title="Offering cards",
        body="## Acceptance criteria\n- [ ] All offering cards are clickable.\n",
    )
    assert [item.ac_id for item in criteria] == ["GH-12-01"]
    assert criteria[0].text == "All offering cards are clickable."


def test_criteria_from_github_issue_falls_back_to_title():
    criteria = criteria_from_github_issue(
        number=13,
        title="Card navigation must work without errors",
        body="No structured section here.",
    )
    assert criteria[0].ac_id == "GH-13-01"
    assert criteria[0].text == "Card navigation must work without errors"


class _FakeIssueClient:
    def __init__(self, issues: dict[int, dict]):
        self.issues = issues

    async def get_issue(self, owner, repo, issue_number):
        return dict(self.issues.get(issue_number) or {"error": "Not found"})

    async def get_issue_comments(self, owner, repo, issue_number):
        return []


async def test_collect_skips_pull_request_payloads():
    collected = await collect_github_issue_acceptance_criteria(
        {
            "metadata": {
                "owner": "acme",
                "repo": "portal",
                "pull_number": 9,
                "pr_description": "Fixes #12",
            }
        },
        _FakeIssueClient(
            {
                12: {
                    "number": 12,
                    "title": "This is actually a PR",
                    "body": "Acceptance Criteria:\n- Should not be used",
                    "pull_request": {"url": "https://api.github.com/repos/acme/portal/pulls/12"},
                }
            }
        ),
    )
    assert collected["refs"]
    assert collected["fetched"] == []
    assert collected["criteria"] == []


async def test_collect_maps_issue_body_to_criteria():
    collected = await collect_github_issue_acceptance_criteria(
        {
            "metadata": {
                "owner": "acme",
                "repo": "portal",
                "pr_description": "Fixes #12",
            }
        },
        _FakeIssueClient(
            {
                12: {
                    "number": 12,
                    "title": "Offering cards",
                    "body": "## Acceptance criteria\n- [ ] Cards are clickable\n",
                }
            }
        ),
    )
    assert collected["github_issue_numbers"] == ["acme/portal#12"]
    assert collected["criteria"][0].ac_id == "GH-12-01"
    assert collected["criteria"][0].text == "Cards are clickable"
