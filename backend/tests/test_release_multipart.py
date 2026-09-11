"""Multipart release creation tests."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import app

SAMPLE_DOCX = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "qa_signoff"
    / "SCRUM-6 Implement SCRUM-6 offerings.docx"
)


@pytest.fixture
def client():
    return TestClient(app)


def test_create_release_multipart_with_qa_attachment(client):
    assert SAMPLE_DOCX.is_file(), "Sample QA sign-off docx is missing"

    data = {
        "release_branch": "feature/SCRUM-6-offerings",
        "github_pr_url": "https://github.com/satalkar21/AI_Studio_Main/pull/1",
        "jira_url": "https://xoriant-team-d79bg42j.atlassian.net/browse/SCRUM-6",
        "qa_signoff_required": "true",
        "environment": "UAT",
        "release_date": "2026-08-12",
        "created_by": "pytest",
    }

    with SAMPLE_DOCX.open("rb") as handle:
        response = client.post(
            "/api/releases",
            data=data,
            files={
                "qa_signoff_attachment": (
                    SAMPLE_DOCX.name,
                    handle,
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )

    assert response.status_code == 202, response.text
    body = response.json()
    assert body["release_id"].startswith("REL-")

    detail = client.get(f"/api/releases/{body['release_id']}")
    assert detail.status_code == 200
    state = detail.json()
    assert state["qa_signoff_attachment"] is not None
    assert state["qa_signoff_attachment"]["filename"] == SAMPLE_DOCX.name


def test_create_release_pr_tests_mode_without_attachment(client):
    response = client.post(
        "/api/releases",
        json={
            "release_branch": "feature/SCRUM-6-offerings",
            "github_pr_url": "https://github.com/satalkar21/AI_Studio_Main/pull/1",
            "jira_url": "https://xoriant-team-d79bg42j.atlassian.net/browse/SCRUM-6",
            "qa_signoff_required": True,
            "qa_mode": "pr_tests",
            "environment": "UAT",
            "release_date": "2026-08-12",
            "created_by": "pytest",
        },
    )
    assert response.status_code == 202, response.text
    detail = client.get(f"/api/releases/{response.json()['release_id']}")
    assert detail.status_code == 200
    state = detail.json()
    assert state["qa_mode"] == "pr_tests"
    assert state["qa_signoff_required"] is True
    assert state["qa_signoff_attachment"] is None
