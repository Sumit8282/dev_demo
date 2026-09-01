"""QA sign-off attachment storage."""

from __future__ import annotations

import re
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

UPLOAD_ROOT = Path(__file__).resolve().parents[2] / "uploads" / "qa_signoffs"
MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024
ALLOWED_EXTENSIONS = {".docx", ".json"}


def _safe_filename(filename: str) -> str:
    name = Path(filename).name.strip()
    if not name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Attachment filename is invalid.",
        )
    sanitized = re.sub(r"[^\w.\- ]", "_", name)
    extension = Path(sanitized).suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported attachment type. Allowed extensions: {allowed}",
        )
    return sanitized


def attachment_dir(release_id: str) -> Path:
    return UPLOAD_ROOT / release_id


async def save_qa_signoff_attachment(release_id: str, upload: UploadFile) -> dict[str, str | int]:
    filename = _safe_filename(upload.filename or "qa-signoff.docx")
    content = await upload.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="QA sign-off attachment is empty.",
        )
    if len(content) > MAX_ATTACHMENT_BYTES:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="QA sign-off attachment exceeds the 10 MB limit.",
        )

    release_dir = attachment_dir(release_id)
    release_dir.mkdir(parents=True, exist_ok=True)
    destination = release_dir / filename
    destination.write_bytes(content)

    return {
        "filename": filename,
        "content_type": upload.content_type or "application/octet-stream",
        "size_bytes": len(content),
        "storage_path": str(destination),
    }


def get_qa_signoff_attachment_path(release_id: str, filename: str) -> Path:
    safe_name = _safe_filename(filename)
    path = attachment_dir(release_id) / safe_name
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="QA sign-off attachment not found.",
        )
    return path
