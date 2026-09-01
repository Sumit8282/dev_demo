"""Deterministic QA sign-off evaluation (ported from backend 7)."""

from __future__ import annotations

import re

from app.models.qa_signoff import SignOffRequest, SignOffResponse


def normalize_title(value: str) -> str:
    """Normalize PR/document titles for comparison."""
    cleaned = re.sub(r"[^\w\s-]", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def titles_match(left: str, right: str) -> bool:
    return normalize_title(left) == normalize_title(right)


def filename_matches_pr_title(filename: str, pr_title: str) -> bool:
    """Return True when attachment filename (without extension) matches PR title."""
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    return titles_match(stem, pr_title)


def _normalize_tags(tags: list[str]) -> list[str]:
    normalized = list(tags)
    existing = {tag.lower() for tag in tags}
    if "qa sign-off" not in existing:
        normalized.append("QA sign-off")
    return normalized


def evaluate_signoff(request: SignOffRequest) -> SignOffResponse:
    """Evaluate QA sign-off eligibility from parsed document fields."""
    status_passed = request.test_plan_status.strip().lower() == "passed"
    approved = status_passed and not request.open_blocker_or_critical_bugs
    tags = request.pr_tags.copy()

    if approved:
        tags = _normalize_tags(tags)
        message = "QA sign-off granted."
        reason = (
            "Test plan status is Passed and there are no open blocker or critical bugs."
        )
    else:
        message = "QA sign-off not granted."
        reasons: list[str] = []
        if not status_passed:
            reasons.append("Test plan status is not Passed.")
        if request.open_blocker_or_critical_bugs:
            reasons.append("Open blocker or critical bugs are present.")
        reason = " ".join(reasons) if reasons else "Does not meet QA sign-off conditions."

    return SignOffResponse(
        approved=approved,
        message=message,
        reason=reason,
        pr_tags=tags,
    )
