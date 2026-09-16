"""Jira issue field extraction helpers."""

from __future__ import annotations

import re
from typing import Any


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def extract_issue_status(issue_data: dict[str, Any]) -> str | None:
    for node in _walk_dicts(issue_data):
        status = node.get("status")
        if isinstance(status, dict):
            for key in ("name", "statusCategory", "statusCategoryName"):
                candidate = status.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
                if isinstance(candidate, dict):
                    name = candidate.get("name")
                    if isinstance(name, str) and name.strip():
                        return name.strip()
        if isinstance(status, str) and status.strip():
            return status.strip()

        fields = node.get("fields")
        if isinstance(fields, dict):
            field_status = fields.get("status")
            if isinstance(field_status, dict):
                name = field_status.get("name")
                if isinstance(name, str) and name.strip():
                    return name.strip()

    return None


def extract_fix_versions(issue_data: dict[str, Any]) -> list[str]:
    versions: list[str] = []

    for node in _walk_dicts(issue_data):
        for key in ("fixVersions", "fixVersion", "fix_versions"):
            raw = node.get(key)
            if isinstance(raw, list):
                for item in raw:
                    if isinstance(item, str) and item.strip():
                        versions.append(item.strip())
                    elif isinstance(item, dict):
                        for version_key in ("name", "value", "version"):
                            name = item.get(version_key)
                            if isinstance(name, str) and name.strip():
                                versions.append(name.strip())
            elif isinstance(raw, str) and raw.strip():
                versions.append(raw.strip())

    # Preserve order while deduplicating
    seen: set[str] = set()
    unique: list[str] = []
    for version in versions:
        if version not in seen:
            seen.add(version)
            unique.append(version)
    return unique


_ADF_BLOCK_TYPES = {
    "blockquote",
    "bulletList",
    "codeBlock",
    "expand",
    "heading",
    "listItem",
    "mediaSingle",
    "orderedList",
    "panel",
    "paragraph",
    "rule",
    "table",
    "tableRow",
    "taskItem",
    "taskList",
}

_ADF_LIST_TYPES = {"bulletList", "orderedList", "taskList"}


def _is_adf_block(value: Any) -> bool:
    return isinstance(value, dict) and str(value.get("type") or "") in _ADF_BLOCK_TYPES


def _adf_list_to_text(value: dict[str, Any]) -> str:
    lines: list[str] = []
    for item in value.get("content") or []:
        text = _adf_to_plain_text(item).strip()
        if not text:
            continue
        first_line = text.split("\n", 1)[0]
        if not (_BULLET_PREFIX.match(first_line) or _AC_ID_PREFIX.match(first_line)):
            text = f"- {text}"
        lines.append(text)
    return "\n".join(lines)


def _adf_to_plain_text(value: Any) -> str:
    """Flatten Jira Atlassian Document Format (ADF) to plain text."""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [part for part in (_adf_to_plain_text(item) for item in value) if part]
        if not parts:
            return ""
        joiner = "\n" if any(_is_adf_block(item) for item in value) else " "
        return joiner.join(parts)
    if isinstance(value, dict):
        node_type = str(value.get("type") or "")
        if node_type == "hardBreak":
            return "\n"
        if node_type in _ADF_LIST_TYPES:
            return _adf_list_to_text(value)
        parts: list[str] = []
        text = value.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text)
        for key in ("content", "paragraph", "body", "value"):
            nested = value.get(key)
            if nested is not None:
                flattened = _adf_to_plain_text(nested)
                if flattened:
                    parts.append(flattened)
        if not parts:
            return ""
        joiner = "\n" if node_type in _ADF_BLOCK_TYPES else " "
        return joiner.join(parts)
    return ""


_AC_SECTION_HEADERS = (
    "acceptance criteria",
    "acceptance criterion",
    "acceptance tests",
    "testing criteria",
    "test criteria",
)

_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
_AC_ID_PREFIX = re.compile(r"^\s*AC[-\s]?\d+\s*[:.)-]\s*", re.IGNORECASE)
_CHECKBOX_PREFIX = re.compile(r"^\[(?: |x|X)\]\s+")
_AC_HEADER_PREFIX = re.compile(
    r"^(?:#{1,6}\s*)?(?:acceptance criteria|acceptance criterion|acceptance tests|testing criteria|test criteria)\s*:?\s*",
    re.IGNORECASE,
)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z*])")


def _section_header_key(line: str) -> str:
    text = line.strip()
    if text.startswith("#"):
        text = text.lstrip("#").strip()
    return text.lower().rstrip(":")


def _is_acceptance_criteria_header(line: str) -> bool:
    key = _section_header_key(line)
    return key in _AC_SECTION_HEADERS or key.startswith("acceptance criteria")


def _header_remainder(line: str) -> str:
    remainder = _AC_HEADER_PREFIX.sub("", line.strip(), count=1).strip()
    return remainder


def _clean_criterion_text(line: str) -> str:
    current = _BULLET_PREFIX.sub("", line)
    current = _AC_ID_PREFIX.sub("", current).strip()
    return _CHECKBOX_PREFIX.sub("", current).strip()


def _is_complete_sentence(text: str) -> bool:
    stripped = text.rstrip()
    return bool(stripped) and stripped[-1] in ".?!"


def _is_item_start(line: str) -> bool:
    return bool(_BULLET_PREFIX.match(line) or _AC_ID_PREFIX.match(line))


def _split_requirement_sentences(text: str) -> list[str]:
    parts = _SENTENCE_SPLIT.split(text.strip())
    return [part.strip() for part in parts if part.strip()]


def extract_acceptance_criteria(description: str | None) -> list[str]:
    """Parse numbered, bulleted, or paragraph acceptance criteria from a Jira description."""
    if not description or not description.strip():
        return []

    lines = description.replace("\r\n", "\n").split("\n")
    section_lines: list[str] = []
    in_section = False

    for line in lines:
        stripped = line.strip()
        if _is_acceptance_criteria_header(stripped):
            in_section = True
            remainder = _header_remainder(stripped)
            if remainder:
                section_lines.append(remainder)
            continue
        if in_section:
            if not stripped:
                continue
            if stripped.startswith("#"):
                break
            if _is_acceptance_criteria_header(stripped):
                remainder = _header_remainder(stripped)
                if remainder:
                    section_lines.append(remainder)
                continue
            lowered = stripped.lower().rstrip(":")
            if stripped.endswith(":") and lowered not in _AC_SECTION_HEADERS:
                if lowered in {"testing", "notes", "out of scope", "scope", "test notes"}:
                    break
            section_lines.append(stripped)

    if not section_lines:
        return []

    criteria: list[str] = []
    current = ""
    for line in section_lines:
        if _is_item_start(line):
            if current:
                criteria.append(current.strip())
            current = _clean_criterion_text(line)
            continue
        cleaned = _clean_criterion_text(line)
        if current and not _is_complete_sentence(current):
            current = f"{current} {cleaned}".strip()
            continue
        if current:
            criteria.append(current.strip())
        pieces = _split_requirement_sentences(cleaned)
        if len(pieces) > 1:
            criteria.extend(pieces[:-1])
            current = pieces[-1]
        else:
            current = pieces[0] if pieces else ""
    if current:
        criteria.append(current.strip())

    return [item for item in criteria if item]


def format_jira_ticket_snapshot(
    *,
    issue_key: str,
    description: str | None,
    acceptance_criteria: list[str],
    status: str | None = None,
    fix_versions: list[str] | None = None,
) -> str:
    """Format pre-fetched Jira context injected into the Jira agent user prompt."""
    lines = [f"Issue key: **{issue_key}**"]
    if status:
        lines.append(f"Status: {status}")
    if fix_versions:
        lines.append(f"Fix versions: {', '.join(fix_versions)}")
    lines.append("")
    lines.append("Description excerpt:")
    excerpt = (description or "(empty)").strip()
    if len(excerpt) > 1200:
        excerpt = f"{excerpt[:1197]}..."
    lines.append(excerpt)
    lines.append("")
    if acceptance_criteria:
        lines.append(
            f"Acceptance criteria on ticket ({len(acceptance_criteria)} total — "
            "evaluate ONLY these; do not add AC rows beyond this list):"
        )
        for index, criterion in enumerate(acceptance_criteria, start=1):
            lines.append(f"- AC-{index:02d}: {criterion}")
    else:
        lines.append(
            "No explicit acceptance criteria section found on the ticket. "
            "Use requirements from the description only; do not invent testing ACs."
        )
    return "\n".join(lines)


def extract_issue_description(issue_data: dict[str, Any]) -> str | None:
    """Extract Jira issue description as plain text."""
    for node in _walk_dicts(issue_data):
        for key in ("description", "body"):
            raw = node.get(key)
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            if isinstance(raw, dict):
                text = _adf_to_plain_text(raw).strip()
                if text:
                    return text
    return None


def extract_issue_comments(issue_data: dict[str, Any]) -> list[dict[str, str]]:
    """Extract Jira issue comments as plain-text author/body pairs."""
    comments: list[dict[str, str]] = []

    def _append_comment(item: dict[str, Any]) -> None:
        body_raw = item.get("body") or item.get("text") or item.get("message")
        body = _adf_to_plain_text(body_raw).strip() if body_raw is not None else ""
        if not body:
            return
        author = "unknown"
        author_raw = item.get("author") or item.get("updateAuthor") or item.get("user")
        if isinstance(author_raw, dict):
            for key in ("displayName", "name", "emailAddress"):
                value = author_raw.get(key)
                if isinstance(value, str) and value.strip():
                    author = value.strip()
                    break
        elif isinstance(author_raw, str) and author_raw.strip():
            author = author_raw.strip()
        comments.append({"author": author, "body": body[:1000]})

    for node in _walk_dicts(issue_data):
        comment_container = node.get("comment")
        if isinstance(comment_container, dict):
            nested = comment_container.get("comments")
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        _append_comment(item)
        for key in ("comments", "issueComments"):
            nested = node.get(key)
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        _append_comment(item)

    return _dedupe_comments(comments)


def _dedupe_comments(comments: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for comment in comments:
        key = (comment.get("author", ""), comment.get("body", ""))
        if key in seen:
            continue
        seen.add(key)
        unique.append(comment)
    return unique


def normalize_jira_status(status: str) -> str:
    """Normalize Jira status names for case-insensitive comparison."""
    normalized = status.strip().lower()
    if normalized == "close":
        return "closed"
    return normalized


def is_allowed_jira_status(status: str | None, allowed_statuses: list[str]) -> bool:
    """Return True when status matches an allowed release status (case-insensitive)."""
    if not status or not allowed_statuses:
        return False
    normalized_actual = normalize_jira_status(status)
    normalized_allowed = {normalize_jira_status(item) for item in allowed_statuses}
    return normalized_actual in normalized_allowed


def jira_ticket_not_found_message(issue_key: str) -> str:
    return f"Jira ticket {issue_key} does not exist."


def is_jira_ticket_not_found_message(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    return (
        "does not exist" in lowered
        or "not found" in lowered
        or "was not found" in lowered
    )


def resolve_jira_ticket_not_found_message(
    issue_key: str,
    errors: list[str] | None = None,
) -> str:
    canonical = jira_ticket_not_found_message(issue_key)
    if errors:
        for error in errors:
            if is_jira_ticket_not_found_message(error):
                return canonical
    return canonical


def issue_exists(issue_data: dict[str, Any]) -> bool:
    if not issue_data:
        return False
    if issue_data.get("error") or issue_data.get("errors"):
        return False

    for node in _walk_dicts(issue_data):
        for key in ("key", "issueKey", "issue_key", "id"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return True
            if isinstance(value, (int, float)):
                return True

    raw = issue_data.get("raw")
    if isinstance(raw, str) and raw.strip():
        lowered = raw.lower()
        if "not found" in lowered or "does not exist" in lowered:
            return False
        return True

    return bool(issue_data)
