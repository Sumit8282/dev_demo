"""GitHub pull request field extraction helpers."""

from __future__ import annotations

from typing import Any


def _walk_dicts(value: Any):
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _walk_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_dicts(item)


def _extract_branch_ref(node: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        branch = node.get(key)
        if isinstance(branch, str) and branch.strip():
            return branch.strip()
        if isinstance(branch, dict):
            for ref_key in ("ref", "name", "label"):
                ref = branch.get(ref_key)
                if isinstance(ref, str) and ref.strip():
                    return ref.strip()
    return None


def extract_source_branch(pr_data: dict[str, Any]) -> str | None:
    """Extract PR head/source branch from GitHub MCP pull request payload."""
    for node in _walk_dicts(pr_data):
        for container_key in ("head", "source", "sourceBranch", "headRef"):
            container = node.get(container_key)
            if isinstance(container, dict):
                ref = _extract_branch_ref(container, "ref", "name", "label")
                if ref:
                    return ref
            elif isinstance(container, str) and container.strip():
                return container.strip()

        direct = _extract_branch_ref(node, "headRef", "head_ref", "source_branch", "sourceBranch")
        if direct:
            return direct

    return None


def extract_target_branch(pr_data: dict[str, Any]) -> str | None:
    """Extract PR base/target branch from GitHub MCP pull request payload."""
    for node in _walk_dicts(pr_data):
        for container_key in ("base", "target", "targetBranch", "baseRef"):
            container = node.get(container_key)
            if isinstance(container, dict):
                ref = _extract_branch_ref(container, "ref", "name", "label")
                if ref:
                    return ref
            elif isinstance(container, str) and container.strip():
                return container.strip()

        direct = _extract_branch_ref(node, "baseRef", "base_ref", "target_branch", "targetBranch")
        if direct:
            return direct

    return None


def extract_pr_head_sha(pr_data: dict[str, Any]) -> str | None:
    """Extract the PR head commit SHA from a GitHub MCP pull request payload."""
    for node in _walk_dicts(pr_data):
        for key in ("head_sha", "headSha", "headSHA"):
            value = node.get(key)
            if isinstance(value, str) and len(value.strip()) >= 7:
                return value.strip()
        head = node.get("head")
        if isinstance(head, dict):
            for key in ("sha", "oid", "commit_sha"):
                value = head.get(key)
                if isinstance(value, str) and len(value.strip()) >= 7:
                    return value.strip()
    return None


def extract_pr_title(pr_data: dict[str, Any]) -> str | None:
    for node in _walk_dicts(pr_data):
        title = node.get("title")
        if isinstance(title, str) and title.strip():
            return title.strip()
    return None


def extract_pr_state(pr_data: dict[str, Any]) -> str | None:
    for node in _walk_dicts(pr_data):
        state = node.get("state")
        if isinstance(state, str) and state.strip():
            return state.strip()
    return None


def extract_pr_merged(pr_data: dict[str, Any]) -> bool | None:
    """Return whether the PR is already merged, if present in the payload."""
    for node in _walk_dicts(pr_data):
        merged = node.get("merged")
        if isinstance(merged, bool):
            return merged
        if isinstance(merged, str):
            lowered = merged.strip().lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
    return None


def validate_pr_open_for_release(pr_data: dict[str, Any]) -> tuple[bool, str | None]:
    """Return whether the PR is open and not merged (required to start release validation)."""
    if extract_pr_merged(pr_data) is True:
        return False, "GitHub pull request is already merged. Release validation cannot continue."

    state = (extract_pr_state(pr_data) or "").lower()
    if state == "closed":
        return False, "GitHub pull request is closed. Release validation cannot continue."
    if state != "open":
        return False, (
            f"GitHub pull request is not open (state: {state or 'unknown'}). "
            "Release validation cannot continue."
        )
    return True, None


def extract_pr_mergeable(pr_data: dict[str, Any]) -> bool | None:
    """Return GitHub mergeable flag when available."""
    for node in _walk_dicts(pr_data):
        mergeable = node.get("mergeable")
        if isinstance(mergeable, bool):
            return mergeable
        if isinstance(mergeable, str):
            lowered = mergeable.strip().lower()
            if lowered in {"true", "false"}:
                return lowered == "true"
    return None


def extract_pr_number(pr_data: dict[str, Any]) -> int | None:
    for node in _walk_dicts(pr_data):
        number = node.get("number")
        if isinstance(number, int) and number > 0:
            return number
        if isinstance(number, str) and number.isdigit():
            return int(number)
    return None


def extract_pr_description(pr_data: dict[str, Any]) -> str | None:
    """Extract PR body/description from GitHub MCP pull request payload."""
    for node in _walk_dicts(pr_data):
        for key in ("body", "description", "summary", "text"):
            value = node.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def extract_pr_author(pr_data: dict[str, Any]) -> str | None:
    """Extract PR author / developer who raised the pull request."""
    for node in _walk_dicts(pr_data):
        for key in ("user", "author", "creator", "opened_by"):
            person = node.get(key)
            if isinstance(person, dict):
                for name_key in ("login", "name", "displayName", "display_name"):
                    name = person.get(name_key)
                    if isinstance(name, str) and name.strip():
                        return name.strip()
            elif isinstance(person, str) and person.strip():
                return person.strip()
    return None


def pr_exists(pr_data: dict[str, Any]) -> bool:
    if not pr_data:
        return False
    if pr_data.get("error") or pr_data.get("errors"):
        return False

    raw = pr_data.get("raw")
    if isinstance(raw, str):
        lowered = raw.lower()
        if "not found" in lowered or "404" in lowered:
            return False

    for node in _walk_dicts(pr_data):
        number = node.get("number")
        if isinstance(number, int) and number > 0:
            return True
        for key in ("id", "node_id", "url", "html_url"):
            value = node.get(key)
            if isinstance(value, (str, int)) and str(value).strip():
                return True

    return bool(extract_source_branch(pr_data) or extract_target_branch(pr_data))


def normalize_branch_name(branch: str) -> str:
    return branch.strip()


def branches_match(expected: str, actual: str) -> bool:
    return normalize_branch_name(expected) == normalize_branch_name(actual)


def extract_pull_request_comments(comments_data: Any) -> list[dict[str, str]]:
    """Normalize PR comment payloads into a compact list for metadata."""
    comments: list[dict[str, str]] = []

    def _append_comment(item: dict[str, Any]) -> None:
        body = item.get("body") or item.get("text") or item.get("message")
        if not isinstance(body, str) or not body.strip():
            return
        author = "unknown"
        user = item.get("user") or item.get("author")
        if isinstance(user, dict):
            login = user.get("login") or user.get("name")
            if isinstance(login, str) and login.strip():
                author = login.strip()
        elif isinstance(user, str) and user.strip():
            author = user.strip()
        created = item.get("created_at") or item.get("createdAt") or item.get("timestamp") or ""
        comments.append(
            {
                "author": author,
                "body": body.strip()[:500],
                "created_at": str(created),
            }
        )

    if isinstance(comments_data, list):
        for item in comments_data:
            if isinstance(item, dict):
                _append_comment(item)
    elif isinstance(comments_data, dict):
        for key in ("comments", "items", "data", "nodes", "edges"):
            nested = comments_data.get(key)
            if isinstance(nested, list):
                for item in nested:
                    if isinstance(item, dict):
                        node = item.get("node") if isinstance(item.get("node"), dict) else item
                        if isinstance(node, dict):
                            _append_comment(node)
            elif isinstance(nested, dict):
                comments.extend(extract_pull_request_comments(nested))

        if not comments:
            _append_comment(comments_data)

    return comments


def extract_pr_change_summary(pr_data: dict[str, Any]) -> dict[str, int | None]:
    """Extract PR-level line/file counts from GitHub MCP pull request payload."""
    for node in _walk_dicts(pr_data):
        additions = node.get("additions")
        deletions = node.get("deletions")
        changed_files = node.get("changed_files")
        if additions is None and deletions is None and changed_files is None:
            continue
        summary: dict[str, int | None] = {
            "lines_added": _coerce_non_negative_int(additions),
            "lines_deleted": _coerce_non_negative_int(deletions),
            "files_changed_count": _coerce_non_negative_int(changed_files),
        }
        if any(value is not None for value in summary.values()):
            return summary
    return {}


def parse_pull_request_files(files_data: Any) -> list[dict[str, int | str]]:
    """Normalize GitHub MCP get_files payload into compact file change records."""
    raw_items: list[Any] = []
    if isinstance(files_data, list):
        raw_items = files_data
    elif isinstance(files_data, dict):
        for key in ("files", "items", "data", "nodes"):
            nested = files_data.get(key)
            if isinstance(nested, list):
                raw_items = nested
                break

    files: list[dict[str, int | str]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        filename = item.get("filename") or item.get("path") or item.get("file")
        if not isinstance(filename, str) or not filename.strip():
            continue
        patch = item.get("patch") or item.get("diff") or ""
        record: dict[str, int | str] = {
            "filename": filename.strip(),
            "status": str(item.get("status") or "").strip(),
            "additions": _coerce_non_negative_int(item.get("additions")) or 0,
            "deletions": _coerce_non_negative_int(item.get("deletions")) or 0,
        }
        if isinstance(patch, str) and patch.strip():
            record["patch"] = patch.strip()[:20000]
        files.append(record)
    return files


def build_pull_request_change_stats(
    pr_data: dict[str, Any],
    files_data: Any,
) -> dict[str, Any]:
    """Combine PR summary counts and per-file details for orchestrator logging."""
    summary = extract_pr_change_summary(pr_data)
    files = parse_pull_request_files(files_data)

    lines_added = summary.get("lines_added")
    lines_deleted = summary.get("lines_deleted")
    files_changed_count = summary.get("files_changed_count")

    if lines_added is None and files:
        lines_added = sum(int(file["additions"]) for file in files)
    if lines_deleted is None and files:
        lines_deleted = sum(int(file["deletions"]) for file in files)
    if files_changed_count is None and files:
        files_changed_count = len(files)

    changed_file_names = [str(file["filename"]) for file in files]

    return {
        "files_changed_count": files_changed_count or 0,
        "lines_added": lines_added or 0,
        "lines_deleted": lines_deleted or 0,
        "changed_file_names": changed_file_names,
        "changed_files": files,
    }


def _coerce_non_negative_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None
