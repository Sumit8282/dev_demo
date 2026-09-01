"""Release workflow state store backed by SQLite."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.models.l3_approval import L3ApprovalRequest
from app.models.release import QASignoffAttachment, ReleaseStateResponse, WorkflowStatus
from app.models.risk_score import ReleaseRiskScore
from app.models.rm_approval import RMApprovalRequest
from app.models.workflow_event import WorkflowEvent
from app.workflow.state import ReleaseState


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _serialize_state(state: ReleaseState) -> str:
    payload = dict(state)
    return json.dumps(payload, default=_json_default)


def _deserialize_state(raw: str) -> ReleaseState:
    data = json.loads(raw)
    if isinstance(data.get("release_date"), str):
        try:
            data["release_date"] = date.fromisoformat(data["release_date"])
        except ValueError:
            pass
    for key in ("created_at", "updated_at"):
        value = data.get(key)
        if isinstance(value, str):
            try:
                data[key] = datetime.fromisoformat(value.replace("Z", "+00:00"))
            except ValueError:
                pass
    return data  # type: ignore[return-value]


class ReleaseStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self._lock = threading.Lock()
        self._releases: dict[str, ReleaseState] = {}
        self._db_path = db_path or get_settings().release_db_path
        self._init_db()
        self._load_all()

    def _connect(self) -> sqlite3.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS releases (
                    release_id TEXT PRIMARY KEY,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()

    def _load_all(self) -> None:
        if not self._db_path.exists():
            return
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT release_id, payload FROM releases ORDER BY created_at ASC"
            ).fetchall()
        loaded: dict[str, ReleaseState] = {}
        for release_id, payload in rows:
            try:
                loaded[release_id] = _deserialize_state(payload)
            except json.JSONDecodeError:
                continue
        with self._lock:
            self._releases = loaded

    def _persist(self, state: ReleaseState) -> None:
        release_id = state["release_id"]
        created_at = state.get("created_at")
        updated_at = state.get("updated_at")
        if not isinstance(created_at, datetime):
            created_at = datetime.now(timezone.utc)
        if not isinstance(updated_at, datetime):
            updated_at = datetime.now(timezone.utc)
        payload = _serialize_state(state)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO releases (release_id, payload, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(release_id) DO UPDATE SET
                    payload = excluded.payload,
                    updated_at = excluded.updated_at
                """,
                (
                    release_id,
                    payload,
                    created_at.isoformat(),
                    updated_at.isoformat(),
                ),
            )
            conn.commit()

    def clear_all(self) -> None:
        with self._lock:
            self._releases.clear()
        with self._connect() as conn:
            conn.execute("DELETE FROM releases")
            conn.commit()

    def generate_release_id(self) -> str:
        return f"REL-{uuid.uuid4().hex[:8].upper()}"

    def create(self, state: ReleaseState) -> ReleaseState:
        now = datetime.now(timezone.utc)
        with self._lock:
            state = {
                **state,
                "workflow_status": WorkflowStatus.VALIDATING.value,
                "overall_validation_status": None,
                "failure_reasons": [],
                "github_comment_posted": False,
                "workflow_events": [],
                "created_at": now,
                "updated_at": now,
            }
            self._releases[state["release_id"]] = state
            self._persist(state)
        return state

    def get(self, release_id: str) -> ReleaseState | None:
        with self._lock:
            stored = self._releases.get(release_id)
            return dict(stored) if stored else None

    def list_all(self) -> list[ReleaseState]:
        with self._lock:
            releases = [dict(state) for state in self._releases.values()]
        return sorted(releases, key=lambda item: item["created_at"], reverse=True)

    def update(self, release_id: str, updates: dict) -> ReleaseState | None:
        with self._lock:
            current = self._releases.get(release_id)
            if not current:
                return None
            current.update(updates)
            current["updated_at"] = datetime.now(timezone.utc)
            self._releases[release_id] = current
            self._persist(current)
            return dict(current)

    def append_event(self, release_id: str, event: dict) -> ReleaseState | None:
        with self._lock:
            current = self._releases.get(release_id)
            if not current:
                return None
            events = list(current.get("workflow_events") or [])
            events.append(event)
            current["workflow_events"] = events
            current["updated_at"] = datetime.now(timezone.utc)
            self._releases[release_id] = current
            self._persist(current)
            return dict(current)

    @staticmethod
    def _serialize_attachment(raw: dict | None) -> QASignoffAttachment | None:
        if not raw:
            return None
        return QASignoffAttachment(
            filename=raw["filename"],
            content_type=raw["content_type"],
            size_bytes=raw["size_bytes"],
        )

    @staticmethod
    def _serialize_l3_approval_request(raw: dict | None) -> L3ApprovalRequest | None:
        if not raw:
            return None
        return L3ApprovalRequest.model_validate(raw)

    @staticmethod
    def _serialize_risk_score(raw: dict | None) -> ReleaseRiskScore | None:
        if not raw:
            return None
        return ReleaseRiskScore.model_validate(raw)

    @staticmethod
    def _serialize_rm_approval_request(raw: dict | None) -> RMApprovalRequest | None:
        if not raw:
            return None
        return RMApprovalRequest.model_validate(raw)

    @staticmethod
    def _serialize_workflow_events(raw: list | None) -> list[WorkflowEvent]:
        if not raw:
            return []
        return [WorkflowEvent.model_validate(item) for item in raw]

    def to_response(self, state: ReleaseState) -> ReleaseStateResponse:
        def _serialize_validation(value):
            if value is None:
                return None
            if hasattr(value, "model_dump"):
                return value.model_dump()
            return value

        return ReleaseStateResponse(
            release_id=state["release_id"],
            release_branch=state["release_branch"],
            release_version=state["release_version"],
            github_pr_url=state["github_pr_url"],
            github_owner=state["github_owner"],
            github_repo=state["github_repo"],
            github_pr_number=state["github_pr_number"],
            jira_url=state["jira_url"],
            jira_issue_key=state["jira_issue_key"],
            qa_signoff_required=state["qa_signoff_required"],
            qa_signoff_not_required_reason=state.get("qa_signoff_not_required_reason"),
            qa_signoff_attachment=self._serialize_attachment(state.get("qa_signoff_attachment")),
            environment=state["environment"],
            release_date=state["release_date"],
            created_by=state.get("created_by"),
            github_validation=_serialize_validation(state.get("github_validation")),
            jira_validation=_serialize_validation(state.get("jira_validation")),
            qa_validation=_serialize_validation(state.get("qa_validation")),
            overall_validation_status=state.get("overall_validation_status"),
            workflow_status=WorkflowStatus(state["workflow_status"]),
            failure_reasons=state.get("failure_reasons", []),
            github_comment_posted=state.get("github_comment_posted", False),
            l3_approval_request=self._serialize_l3_approval_request(state.get("l3_approval_request")),
            risk_score=self._serialize_risk_score(state.get("risk_score")),
            build_result=_serialize_validation(state.get("build_result")),
            rm_approval_request=self._serialize_rm_approval_request(state.get("rm_approval_request")),
            merge_result=_serialize_validation(state.get("merge_result")),
            workflow_events=self._serialize_workflow_events(state.get("workflow_events")),
            created_at=state["created_at"],
            updated_at=state["updated_at"],
        )


release_store = ReleaseStore()
