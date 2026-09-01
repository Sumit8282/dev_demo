"""Persist RM approval notification drafts to local JSON files."""

from __future__ import annotations

import json
from pathlib import Path

from app.models.rm_approval import RMApprovalNotificationDraft

NOTIFICATION_DRAFT_ROOT = Path(__file__).resolve().parents[2] / "data" / "rm_mail_drafts"


def notification_draft_path(release_id: str) -> Path:
    return NOTIFICATION_DRAFT_ROOT / f"{release_id}.json"


def save_rm_approval_notification_draft(
    release_id: str,
    notification_draft: RMApprovalNotificationDraft,
) -> str:
    """Write the RM notification JSON to disk and return the absolute file path."""
    NOTIFICATION_DRAFT_ROOT.mkdir(parents=True, exist_ok=True)
    path = notification_draft_path(release_id)
    draft_data = notification_draft.model_dump(mode="json")
    payload = {
        "approval_link": notification_draft.approval_url,
        **draft_data,
    }
    path.write_text(
        json.dumps(payload, indent=2),
        encoding="utf-8",
    )
    return str(path)


def update_rm_notification_draft_status(release_id: str, status: str) -> None:
    path = notification_draft_path(release_id)
    if not path.is_file():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    metadata["mail_status"] = status
    payload["metadata"] = metadata
    payload["mail_status"] = status
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_rm_approval_notification_draft(release_id: str) -> RMApprovalNotificationDraft | None:
    path = notification_draft_path(release_id)
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    return RMApprovalNotificationDraft.model_validate(payload)
