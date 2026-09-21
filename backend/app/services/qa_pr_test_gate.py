"""Lane 1: collect real PR/repo/CI evidence and map it to Jira ACs."""

from __future__ import annotations

import re
from typing import Any

from app.models.qa_llm_validation import QACoverageMatrixRow, QADraftTest

_TESTING_HEADING = re.compile(
    r"^#{1,4}\s*(testing|test plan|verification|qa|qa notes)\b",
    re.IGNORECASE,
)
_VERIFIED_LINE = re.compile(
    r"\b(tested|verified|verification|qa passed|manually checked)\b",
    re.IGNORECASE,
)

_TEST_PATH_MARKERS = (
    "/test/",
    "/tests/",
    "/__tests__/",
    "\\test\\",
    "\\tests\\",
    "test_",
    "_test.",
    ".spec.",
    ".test.",
    "spec/",
    "cypress/",
    "playwright/",
)

_TEST_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".java",
    ".cs",
    ".kt",
    ".go",
)


def is_test_file(filename: str | None) -> bool:
    path = str(filename or "").replace("\\", "/").strip().lower()
    if not path:
        return False
    if any(marker in path for marker in _TEST_PATH_MARKERS):
        return True
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test") and name.endswith(_TEST_EXTENSIONS)


def extract_github_metadata(github_validation: Any | None) -> dict[str, Any]:
    if github_validation is None:
        return {}
    if hasattr(github_validation, "metadata"):
        metadata = github_validation.metadata or {}
        return metadata if isinstance(metadata, dict) else {}
    if isinstance(github_validation, dict):
        nested = github_validation.get("metadata")
        if isinstance(nested, dict):
            return nested
        return github_validation
    return {}


def collect_pr_test_files(github_validation: Any | None) -> list[dict[str, Any]]:
    metadata = extract_github_metadata(github_validation)
    return collect_test_files(metadata.get("changed_files") or [], source="pr")


def collect_test_files(raw_files: Any, *, source: str) -> list[dict[str, Any]]:
    files: list[dict[str, Any]] = []
    if not isinstance(raw_files, list):
        return files
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or item.get("path") or "").strip()
        if not is_test_file(filename):
            continue
        files.append(
            {
                "filename": filename,
                "status": str(item.get("status") or source),
                "patch": str(item.get("patch") or item.get("content") or ""),
                "additions": item.get("additions") or 0,
                "deletions": item.get("deletions") or 0,
                "source": source,
            }
        )
    return files


def merge_test_files(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for item in group:
            filename = str(item.get("filename") or "").strip()
            if not filename:
                continue
            key = filename.replace("\\", "/").lower()
            existing = merged.get(key)
            if existing is None:
                merged[key] = dict(item)
                continue
            if not existing.get("patch") and item.get("patch"):
                existing["patch"] = item["patch"]
            if existing.get("source") != "pr" and item.get("source") == "pr":
                existing["source"] = "pr"
                existing["status"] = item.get("status") or existing.get("status")
    return list(merged.values())


def changed_production_files(github_validation: Any | None) -> list[str]:
    metadata = extract_github_metadata(github_validation)
    raw_files = metadata.get("changed_files") or []
    names: list[str] = []
    if not isinstance(raw_files, list):
        return names
    for item in raw_files:
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename") or "").strip()
        if filename and not is_test_file(filename):
            names.append(filename)
    return names


def related_test_path_candidates(filename: str) -> list[str]:
    path = str(filename or "").replace("\\", "/").strip()
    if not path or is_test_file(path):
        return []
    directory, _, name = path.rpartition("/")
    stem, ext = _split_stem_ext(name)
    if not stem:
        return []
    prefixes = [directory] if directory else [""]
    if directory.startswith("src/"):
        prefixes.append("src")
    prefixes.extend(["tests", "test", f"{directory}/__tests__" if directory else "__tests__"])
    candidates: list[str] = []
    for prefix in prefixes:
        base = f"{prefix}/" if prefix else ""
        candidates.extend(
            [
                f"{base}test_{stem}{ext or '.py'}",
                f"{base}{stem}_test{ext or '.py'}",
                f"{base}{stem}.test{ext or '.ts'}",
                f"{base}{stem}.spec{ext or '.ts'}",
            ]
        )
    seen: set[str] = set()
    unique: list[str] = []
    for item in candidates:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def select_related_test_paths(
    repo_paths: list[str],
    *,
    changed_files: list[str],
    limit: int = 15,
) -> list[str]:
    test_paths = [path.replace("\\", "/") for path in repo_paths if is_test_file(path)]
    if not test_paths:
        return []
    wanted = {candidate.lower() for name in changed_files for candidate in related_test_path_candidates(name)}
    stems = {_file_stem(name).lower() for name in changed_files if not is_test_file(name)}
    stems.discard("")
    ranked: list[tuple[int, str]] = []
    for path in test_paths:
        score = 0
        lowered = path.lower()
        if lowered in wanted:
            score += 100
        stem = _file_stem(path).lower()
        for changed_stem in stems:
            if changed_stem and changed_stem in stem:
                score += 10
                break
        if score:
            ranked.append((score, path))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in ranked[:limit]]


_SOURCE_EXTENSIONS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".vue",
    ".html",
    ".json",
    ".java",
    ".xml",
    ".properties",
    ".yml",
    ".yaml",
)
_SOURCE_SKIP_MARKERS = (
    "/node_modules/",
    "/dist/",
    "/build/",
    "/.git/",
    "/coverage/",
    "/.next/",
    "/vendor/",
)


def is_source_file(filename: str | None) -> bool:
    path = str(filename or "").replace("\\", "/").strip()
    if not path or is_test_file(path):
        return False
    lowered = f"/{path.lower()}"
    if any(marker in lowered for marker in _SOURCE_SKIP_MARKERS):
        return False
    return any(path.lower().endswith(ext) for ext in _SOURCE_EXTENSIONS)


def select_source_paths(
    repo_paths: list[str],
    *,
    changed_files: list[str],
    limit: int = 80,
) -> list[str]:
    sources = [path.replace("\\", "/") for path in repo_paths if is_source_file(path)]
    if not sources:
        return []
    changed = {name.replace("\\", "/").lower() for name in changed_files if name}
    stems = {_file_stem(name).lower() for name in changed_files if not is_test_file(name)}
    stems.discard("")
    ranked: list[tuple[int, str]] = []
    for path in sources:
        score = 1
        lowered = path.lower()
        if lowered in changed:
            score += 100
        if any(hint in lowered for hint in ("offering", "card", "demo", "url", "accelerat", "whats")):
            score += 15
        stem = _file_stem(path).lower()
        for changed_stem in stems:
            if changed_stem and changed_stem in stem:
                score += 20
                break
        ranked.append((score, path))
    ranked.sort(key=lambda item: (-item[0], item[1]))
    return [path for _, path in ranked[:limit]]


def format_generated_test_repo_context(
    *,
    source_files: list[str] | None = None,
    changed_files: list[str] | None = None,
    source_excerpt: str = "",
) -> str:
    lines: list[str] = []
    changed = [name for name in (changed_files or []) if name]
    sources = [name for name in (source_files or []) if name]
    if changed:
        lines.append("Changed production files:")
        lines.extend(f"- {name}" for name in changed[:40])
    if sources:
        if lines:
            lines.append("")
        lines.append("Source files in the GitHub checkout:")
        lines.extend(f"- {name}" for name in sources[:80])
    excerpt = (source_excerpt or "").strip()
    if excerpt:
        if lines:
            lines.append("")
        lines.append("Source excerpts (copy strings from here; do not invent keys):")
        lines.append(excerpt[:12000])
    return "\n".join(lines) or "(no source file list; search the checkout with pathlib.Path('.').rglob)"


def extract_pr_testing_writeup(github_validation: Any | None) -> str:
    metadata = extract_github_metadata(github_validation)
    chunks: list[str] = []
    description = str(metadata.get("pr_description") or "").strip()
    section = _section_after_testing_heading(description)
    if section:
        chunks.append(section)
    elif description and _VERIFIED_LINE.search(description):
        chunks.append(description)
    comments = metadata.get("comments") or []
    if isinstance(comments, list):
        for item in comments:
            body = ""
            if isinstance(item, dict):
                body = str(item.get("body") or "").strip()
            elif isinstance(item, str):
                body = item.strip()
            if not body:
                continue
            comment_section = _section_after_testing_heading(body)
            if comment_section:
                chunks.append(comment_section)
            elif _VERIFIED_LINE.search(body):
                chunks.append(body)
    return "\n\n".join(chunk for chunk in chunks if chunk).strip()


def build_pr_test_document(
    test_files: list[dict[str, Any]],
    *,
    head_sha: str = "",
    repo_test_files: list[dict[str, Any]] | None = None,
    testing_writeup: str = "",
    ci_status: str = "",
) -> str:
    files = merge_test_files(test_files, repo_test_files or [])
    writeup = str(testing_writeup or "").strip()
    ci = str(ci_status or "").strip()
    result_label = "Failed" if ci.lower() == "failure" else "Passed"
    if not files and not writeup:
        sha_line = f"Head SHA: {head_sha}\n" if head_sha else ""
        ci_line = f"CI status: {ci}\n" if ci else ""
        return (
            f"{sha_line}{ci_line}"
            "No automated tests or PR Testing write-up were found for this change.\n"
            "Lane 1 uses Jira ACs plus real GitHub evidence: PR test diffs, related "
            "repo tests at this SHA, the PR Testing section, and CI status."
        )

    lines = [
        "Real QA evidence from GitHub. Use only what is shown. Do not invent tests.",
    ]
    if head_sha:
        lines.append(f"Head SHA: {head_sha}")
    if ci:
        lines.append(f"CI status: {ci}")

    index = 1
    pr_files = [item for item in files if item.get("source") == "pr"]
    repo_files = [item for item in files if item.get("source") != "pr"]
    if pr_files:
        lines.append("")
        lines.append("## Tests changed in this pull request")
        index = _append_test_file_section(lines, pr_files, start=index, result_label=result_label)
    if repo_files:
        lines.append("")
        lines.append("## Existing tests in the repo at this SHA")
        index = _append_test_file_section(lines, repo_files, start=index, result_label=result_label)
    if writeup:
        lines.append("")
        lines.append("## PR Testing / verification write-up")
        lines.append("Treat each verification bullet as an executed check from the PR.")
        for bullet in _writeup_bullets(writeup):
            lines.append(f"TC-{index:03d} {bullet} | {result_label}")
            index += 1
    return "\n".join(lines)


def _append_test_file_section(
    lines: list[str],
    files: list[dict[str, Any]],
    *,
    start: int,
    result_label: str,
) -> int:
    index = start
    for item in files:
        filename = item.get("filename") or f"test-{index}"
        origin = "PR" if item.get("source") == "pr" else "repo"
        patch = str(item.get("patch") or "").strip()
        lines.append("")
        lines.append(
            f"### TC-{index:03d} {filename} | {result_label} | present in {origin} "
            f"({item.get('status') or 'existing'})"
        )
        if patch:
            lines.append("```")
            lines.append(patch[:8000])
            lines.append("```")
        else:
            lines.append("(file exists; diff not available)")
        index += 1
    return index


def _writeup_bullets(text: str) -> list[str]:
    bullets: list[str] = []
    for raw in text.splitlines():
        line = raw.strip().lstrip("-*").strip()
        if not line or line.startswith("#"):
            continue
        bullets.append(line[:400])
    return bullets or [text.strip()[:800]]


def _section_after_testing_heading(text: str) -> str:
    lines = str(text or "").splitlines()
    start: int | None = None
    for index, line in enumerate(lines):
        if _TESTING_HEADING.search(line.strip()):
            start = index + 1
            break
    if start is None:
        return ""
    collected: list[str] = []
    for line in lines[start:]:
        if line.startswith("#") and not _TESTING_HEADING.search(line.strip()):
            break
        collected.append(line)
    return "\n".join(collected).strip()


def _split_stem_ext(name: str) -> tuple[str, str]:
    if "." not in name:
        return name, ""
    stem, ext = name.rsplit(".", 1)
    return stem, f".{ext}"


def _file_stem(path: str) -> str:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem, _ext = _split_stem_ext(name)
    cleaned = re.sub(r"(\.test|\.spec|_test|test_)$", "", stem, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(test_)", "", cleaned, flags=re.IGNORECASE)
    return cleaned


def uncovered_acceptance_criteria(coverage_matrix: list[QACoverageMatrixRow]) -> list[QACoverageMatrixRow]:
    return [row for row in coverage_matrix if row.coverage != "Fully Covered"]


def format_lane2_comment(
    *,
    head_sha: str,
    uncovered: list[QACoverageMatrixRow],
    drafts: list[QADraftTest],
) -> str:
    lines = [
        "## QA Lane 2 — draft tests for uncovered acceptance criteria",
        "",
        "Lane 1 checked live Jira ACs against real GitHub evidence (PR tests, related repo tests, PR Testing write-up, CI) and found coverage gaps.",
        f"Checked commit: `{head_sha or 'unknown'}`.",
        "",
        "These drafts are suggestions only. Review them, commit the tests you accept, then "
        "create the release again so Lane 1 re-runs against the new SHA.",
        "",
        "### Uncovered acceptance criteria",
    ]
    if uncovered:
        for row in uncovered:
            lines.append(f"- {row.ac_id}: {row.acceptance_criterion} ({row.coverage})")
    else:
        lines.append("- (none listed)")
    lines.append("")
    lines.append("### Draft tests")
    if not drafts:
        lines.append("No draft tests were generated. Add tests that cover the ACs above.")
        return "\n".join(lines)
    for draft in drafts:
        lines.append(f"#### {draft.ac_id} → `{draft.suggested_path}`")
        if draft.rationale:
            lines.append(draft.rationale)
        lines.append(f"```{draft.language}")
        lines.append(draft.test_code.strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
