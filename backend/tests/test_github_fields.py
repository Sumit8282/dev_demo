"""GitHub PR field extraction tests."""

from app.utils.github_fields import (
    branches_match,
    extract_pr_author,
    extract_pr_description,
    extract_pull_request_comments,
    extract_source_branch,
    extract_target_branch,
    pr_exists,
    validate_pr_open_for_release,
)


def test_extract_source_and_target_branches():
    payload = {
        "number": 1,
        "head": {"ref": "feature/SCRUM-6-offerings"},
        "base": {"ref": "main"},
    }
    assert extract_source_branch(payload) == "feature/SCRUM-6-offerings"
    assert extract_target_branch(payload) == "main"
    assert pr_exists(payload) is True


def test_branches_match_exact():
    assert branches_match("release/v2.4.0", "release/v2.4.0") is True
    assert branches_match("feature/SCRUM-6-offerings", "feature/SCRUM-6-offering") is False


def test_extract_pull_request_comments():
    payload = {
        "comments": [
            {
                "user": {"login": "dev1"},
                "body": "Looks good",
                "created_at": "2026-08-12T10:00:00Z",
            }
        ]
    }
    comments = extract_pull_request_comments(payload)
    assert len(comments) == 1
    assert comments[0]["author"] == "dev1"
    assert comments[0]["body"] == "Looks good"


def test_extract_pr_author():
    payload = {
        "number": 1,
        "user": {"login": "gauri-dev", "name": "Gauri Satalkar"},
        "head": {"ref": "release/v2.4.0"},
    }
    assert extract_pr_author(payload) == "gauri-dev"


def test_validate_pr_open_for_release():
    open_payload = {"number": 1, "state": "open", "merged": False}
    assert validate_pr_open_for_release(open_payload) == (True, None)

    merged_payload = {"number": 1, "state": "closed", "merged": True}
    ok, message = validate_pr_open_for_release(merged_payload)
    assert ok is False
    assert message and "merged" in message.lower()

    closed_payload = {"number": 1, "state": "closed", "merged": False}
    ok, message = validate_pr_open_for_release(closed_payload)
    assert ok is False
    assert message and "closed" in message.lower()


def test_extract_pr_description():
    payload = {
        "number": 1,
        "body": "Fix offerings dropdown click handler for release.",
        "head": {"ref": "release/v2.4.0"},
    }
    assert extract_pr_description(payload) == "Fix offerings dropdown click handler for release."


def test_build_pull_request_change_stats():
    from app.utils.github_fields import build_pull_request_change_stats

    pr_payload = {
        "number": 11,
        "additions": 42,
        "deletions": 1,
        "changed_files": 3,
    }
    files_payload = [
        {"filename": ".gitignore", "status": "added", "additions": 21, "deletions": 0},
        {
            "filename": "frontend/package-lock.json",
            "status": "modified",
            "additions": 18,
            "deletions": 1,
        },
        {
            "filename": "frontend/src/components/Header.tsx",
            "status": "modified",
            "additions": 3,
            "deletions": 0,
        },
    ]

    stats = build_pull_request_change_stats(pr_payload, files_payload)

    assert stats["files_changed_count"] == 3
    assert stats["lines_added"] == 42
    assert stats["lines_deleted"] == 1
    assert stats["changed_file_names"] == [
        ".gitignore",
        "frontend/package-lock.json",
        "frontend/src/components/Header.tsx",
    ]
