"""QA sign-off service tests."""

import json
from pathlib import Path

import pytest

from app.services.qa_signoff_service import QASignoffService


@pytest.fixture
def signoff_service():
    return QASignoffService()


def _write_json_attachment(tmp_path: Path, release_id: str, filename: str, payload: dict) -> None:
    release_dir = tmp_path / release_id
    release_dir.mkdir(parents=True, exist_ok=True)
    (release_dir / filename).write_text(json.dumps(payload), encoding="utf-8")


def test_signoff_not_required_passes(signoff_service):
    result = signoff_service.validate_not_required(
        qa_signoff_not_required_reason="Hotfix exempt",
    )
    assert result.status.value == "PASS"
    assert result.checks.signoff_not_required_reason == "Hotfix exempt"


def test_load_qa_document_text_from_json(signoff_service, tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.services.qa_signoff_service.get_qa_signoff_attachment_path",
        lambda _rid, name: tmp_path / "REL-1" / name,
    )
    payload = {"pr_title": "Example", "test_plan_status": "Passed"}
    _write_json_attachment(tmp_path, "REL-1", "signoff.json", payload)

    filename, text = signoff_service.load_qa_document_text(
        release_id="REL-1",
        attachment={"filename": "signoff.json"},
    )

    assert filename == "signoff.json"
    assert "Example" in text


def test_load_qa_document_text_missing_filename(signoff_service):
    with pytest.raises(ValueError, match="attachment is required"):
        signoff_service.load_qa_document_text(
            release_id="REL-1",
            attachment={},
        )
