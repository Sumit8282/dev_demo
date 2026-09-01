import os
import tempfile
from pathlib import Path

# Keep pytest from writing to the development releases database.
_test_db = Path(tempfile.gettempdir()) / "release_automation_pytest.db"
os.environ.setdefault("RELEASE_DATABASE_PATH", str(_test_db))

import pytest

pytest_plugins = ("pytest_asyncio",)


@pytest.fixture
def medium_risk(monkeypatch):
    """Force MEDIUM risk so workflow tests expect L3 approval pending."""
    from app.services.release_risk_scorer import RiskResult

    monkeypatch.setattr(
        "app.agents.orchestrator.score_release_from_github_metadata",
        lambda *args, **kwargs: RiskResult(
            score=0.44,
            level="MEDIUM",
            breakdown={},
            high_risk_files=[],
        ),
    )


@pytest.fixture
def low_risk(monkeypatch):
    """Force LOW risk so workflow tests exercise auto-merge."""
    from app.services.release_risk_scorer import RiskResult

    monkeypatch.setattr(
        "app.agents.orchestrator.score_release_from_github_metadata",
        lambda *args, **kwargs: RiskResult(
            score=0.10,
            level="LOW",
            breakdown={},
            high_risk_files=[],
        ),
    )


@pytest.fixture
def sample_state():
    from datetime import date

    return {
        "release_id": "REL-TEST001",
        "release_branch": "release/v2.4.0",
        "release_version": "v2.4.0",
        "github_pr_url": "https://github.com/company/repository/pull/123",
        "github_owner": "company",
        "github_repo": "repository",
        "github_pr_number": 123,
        "jira_url": "https://company.atlassian.net/browse/ABC-123",
        "jira_issue_key": "ABC-123",
        "qa_signoff_required": True,
        "qa_signoff_not_required_reason": None,
        "environment": "UAT2",
        "release_date": date(2026, 8, 15),
    }
