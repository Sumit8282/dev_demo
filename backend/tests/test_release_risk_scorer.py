"""Release risk scorer tests."""

from app.services.release_risk_scorer import FileChange, ReleaseRiskScorer


def test_release_risk_scorer_example_pr():
    pr_files = [
        FileChange("src/payments/processor.py", lines_added=210, lines_deleted=85),
        FileChange("src/auth/token_service.py", lines_added=45, lines_deleted=10),
        FileChange("src/notifications/emailer.py", lines_added=30, lines_deleted=5),
        FileChange("tests/test_payments.py", lines_added=120, lines_deleted=40),
        FileChange("config/settings.yaml", lines_added=3, lines_deleted=1),
    ]
    failure_history = {
        "src/payments/processor.py": 0.72,
        "src/auth/token_service.py": 0.30,
        "src/notifications/emailer.py": 0.15,
        "tests/test_payments.py": 0.10,
    }

    result = ReleaseRiskScorer().score(pr_files, failure_history)

    assert result.level == "MEDIUM"
    assert 0.35 <= result.score < 0.65
    assert result.breakdown["file_count_score"] == 0.25
    assert len(result.high_risk_files) == 1
    assert result.high_risk_files[0]["filepath"] == "src/payments/processor.py"


def test_release_risk_scorer_low_risk_small_change():
    files = [FileChange("docs/readme.md", lines_added=2, lines_deleted=1)]
    result = ReleaseRiskScorer().score(files, {})

    assert result.level == "LOW"
    assert result.score < 0.35
    assert result.high_risk_files == []


def test_release_risk_scorer_high_risk_large_change():
    files = [
        FileChange(
            "src/payments/processor.py",
            lines_added=900,
            lines_deleted=200,
        )
    ]
    failure_history = {"src/payments/processor.py": 0.9}

    result = ReleaseRiskScorer().score(files, failure_history)

    assert result.level == "HIGH"
    assert result.score > 0.65
    assert len(result.high_risk_files) == 1


def test_build_file_changes_from_github_metadata():
    from app.services.release_risk_scorer import build_file_changes_from_github_metadata

    metadata = {
        "changed_files": [
            {"filename": "backend/app/main.py", "additions": 10, "deletions": 2},
            {"filename": "frontend/src/App.tsx", "additions": 5, "deletions": 1},
        ],
        "files_changed_count": 2,
        "lines_added": 15,
        "lines_deleted": 3,
    }

    changes = build_file_changes_from_github_metadata(metadata)

    assert len(changes) == 2
    assert changes[0].filepath == "backend/app/main.py"
    assert changes[0].lines_changed == 12
    assert changes[1].lines_changed == 6
