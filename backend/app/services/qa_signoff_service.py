"""QA sign-off attachment loading and non-required validation."""

from __future__ import annotations

import json
import logging
from typing import Any

from app.models.validation import QAChecks, QAValidationResult, ValidationStatus
from app.services.attachment_store import get_qa_signoff_attachment_path
from app.services.qa_signoff_docx import extract_docx_text, parse_signoff_attachment

logger = logging.getLogger(__name__)


class QASignoffService:
    def validate_not_required(
        self,
        *,
        qa_signoff_not_required_reason: str | None,
    ) -> QAValidationResult:
        return QAValidationResult(
            status=ValidationStatus.PASS,
            checks=QAChecks(
                signoff_required=False,
                signoff_completed=True,
                signoff_not_required_reason=qa_signoff_not_required_reason,
            ),
            metadata={
                "signoff_not_required_reason": qa_signoff_not_required_reason or "",
            },
        )

    def load_qa_document_text(
        self,
        *,
        release_id: str,
        attachment: dict[str, Any],
    ) -> tuple[str, str]:
        """Return attachment filename and full document text for LLM validation."""
        filename = str(attachment.get("filename") or "").strip()
        if not filename:
            raise ValueError("QA sign-off attachment is required but was not provided.")

        path = get_qa_signoff_attachment_path(release_id, filename)
        content = path.read_bytes()
        lower_name = filename.lower()

        if lower_name.endswith(".json"):
            try:
                payload = json.loads(content.decode("utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                raise ValueError(f"Uploaded JSON file must contain valid JSON. Error: {exc}") from exc
            text = json.dumps(payload, indent=2)
        elif lower_name.endswith(".docx"):
            text = extract_docx_text(content)
            if not text.strip():
                raise ValueError("The Word document does not contain readable text.")
        else:
            raise ValueError("QA sign-off attachment must be a .docx or .json file.")

        return filename, text

    def load_structured_signoff(
        self,
        *,
        release_id: str,
        attachment: dict[str, Any],
    ):
        """Parse attachment into SignOffRequest for metadata enrichment."""
        filename = str(attachment.get("filename") or "").strip()
        path = get_qa_signoff_attachment_path(release_id, filename)
        return parse_signoff_attachment(path.read_bytes(), filename)


def get_qa_signoff_service() -> QASignoffService:
    return QASignoffService()
