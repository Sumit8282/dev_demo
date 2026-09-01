"""Attachment storage tests."""

import pytest
from fastapi import HTTPException

from app.services.attachment_store import _safe_filename, save_qa_signoff_attachment


def test_safe_filename_rejects_unsupported_extension():
    with pytest.raises(HTTPException) as exc_info:
        _safe_filename("signoff.pdf")
    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_save_qa_signoff_attachment(tmp_path, monkeypatch):
    monkeypatch.setattr("app.services.attachment_store.UPLOAD_ROOT", tmp_path)

    class FakeUpload:
        filename = "SCRUM-6 Implement offerings.json"
        content_type = "application/json"

        async def read(self):
            return b'{"pr_title":"SCRUM-6: Implement offerings","test_plan_status":"Passed","open_blocker_or_critical_bugs":false}'

    saved = await save_qa_signoff_attachment("REL-TEST001", FakeUpload())
    assert saved["filename"] == "SCRUM-6 Implement offerings.json"
    content = b'{"pr_title":"SCRUM-6: Implement offerings","test_plan_status":"Passed","open_blocker_or_critical_bugs":false}'
    assert saved["size_bytes"] == len(content)
