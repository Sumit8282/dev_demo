"""Persist L3 approval mail drafts to local JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.l3_approval import L3ApprovalMailDraft

MAIL_DRAFT_ROOT = Path(__file__).resolve().parents[2] / "data" / "l3_mail_drafts"


def mail_draft_path(release_id: str) -> Path:
    return MAIL_DRAFT_ROOT / f"{release_id}.json"


def save_l3_approval_mail_draft(release_id: str, mail_draft: L3ApprovalMailDraft) -> str:
    """Write the mail draft JSON to disk and return the absolute file path."""
    MAIL_DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
    path = mail_draft_path(release_id)
    draft_data = mail_draft.model_dump(mode="json")
    payload = {
        "approval_link": mail_draft.approval_url,
        **draft_data,
    }
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return str(path)


def update_l3_mail_draft_status(release_id: str, status: str) -> None:
    path = mail_draft_path(release_id)
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    metadata["mail_status"] = status
    payload["metadata"] = metadata
    payload["mail_status"] = status
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_l3_approval_mail_draft(release_id: str) -> L3ApprovalMailDraft | None:
    path = mail_draft_path(release_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return L3ApprovalMailDraft.model_validate(payload)
