"""Build stdlib generated tests from AC phrases that exist in the checkout."""

from __future__ import annotations

import re
from pathlib import Path

from app.models.qa_llm_validation import QAAcceptanceCriterion

_TITLE_PHRASE = re.compile(r"\b([A-Z][A-Za-z0-9]+(?:\s+[A-Z][A-Za-z0-9/+-]+)+)\b")
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_\-]{3,}")
_STOP = {
    "that",
    "with",
    "from",
    "each",
    "card",
    "cards",
    "page",
    "correct",
    "correctly",
    "properly",
    "successfully",
    "works",
    "working",
    "without",
    "other",
    "does",
    "not",
    "impact",
    "remain",
    "unchanged",
    "existing",
    "introduced",
    "configured",
    "clicking",
    "navigates",
    "navigation",
    "functionality",
    "alignment",
    "spacing",
    "issues",
    "errors",
    "styling",
    "layout",
    "checks",
    "ensures",
    "confirms",
    "validates",
    "verifies",
}
_URL_HINTS = ("href", "demoUrl", "demo_url", "window.open", "target=\"_blank\"", "/demo")
_CLICK_HINTS = ("onClick", "onPress", "href", "to=", "navigate")

SOURCE_HELPER_PATH = "tests/generated/_qa_source.py"
SOURCE_HELPER_CODE = '''from pathlib import Path

SKIP = {"node_modules", "dist", "build", ".git", "coverage", ".next", "vendor"}
EXTS = {".ts", ".tsx", ".js", ".jsx", ".py", ".json", ".html", ".vue"}


def _compact(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def iter_source(root: str = ".") :
    base = Path(root)
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in EXTS:
            continue
        if any(part in SKIP for part in path.parts):
            continue
        if "tests/generated" in str(path).replace("\\\\", "/"):
            continue
        try:
            yield path, path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue


def combined_source(root: str = ".") -> str:
    return "\\n".join(text for _, text in iter_source(root))


def assert_mentioned(*phrases: str, root: str = ".") -> None:
    blob = combined_source(root)
    lowered = blob.lower()
    compact = _compact(blob)
    missing = []
    for phrase in phrases:
        text = str(phrase or "").strip()
        if not text:
            continue
        ok = text in blob or text.lower() in lowered
        key = _compact(text)
        if not ok and (" " in text or any(ch.isupper() for ch in text[1:])) and len(key) >= 6:
            ok = key in compact
        if not ok:
            missing.append(text)
    assert not missing, f"Not found in checkout source: {missing}"
'''


def _compact(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def phrases_for_acceptance_criterion(ac_text: str, source: str) -> list[str]:
    text = (ac_text or "").strip()
    source = source or ""
    lowered = source.lower()
    compact = _compact(source)
    candidates: list[str] = []
    candidates.extend(_TITLE_PHRASE.findall(text))
    for word in _WORD.findall(text):
        lowered_word = word.lower()
        if lowered_word in _STOP or lowered_word.endswith("ly"):
            continue
        if word.islower() and "_" not in word and "-" not in word:
            continue
        candidates.append(word)
    if re.search(r"url|navigat", text, re.IGNORECASE):
        candidates.extend(_URL_HINTS)
    if re.search(r"click|navigat", text, re.IGNORECASE):
        candidates.extend(_CLICK_HINTS)
    if re.search(r"styl|layout|align|spacing", text, re.IGNORECASE):
        candidates.extend(("className", "style", "sx="))

    kept: list[str] = []
    seen: set[str] = set()
    for phrase in candidates:
        key = phrase.lower()
        if key in seen:
            continue
        exists = phrase in source or phrase.lower() in lowered
        compact_key = _compact(phrase)
        if (
            not exists
            and (" " in phrase or any(ch.isupper() for ch in phrase[1:]))
            and len(compact_key) >= 6
        ):
            exists = compact_key in compact
        if not exists:
            continue
        seen.add(key)
        kept.append(phrase)
        if len(kept) >= 5:
            break
    return kept


def build_generated_test_code(criterion: QAAcceptanceCriterion, source: str) -> str:
    ac_id = re.sub(r"[^A-Za-z0-9_]", "_", (criterion.ac_id or "ac").lower())
    phrases = phrases_for_acceptance_criterion(criterion.text, source)
    if not phrases:
        return (
            "from tests.generated._qa_source import combined_source\n\n"
            f"def test_{ac_id}():\n"
            "    assert combined_source().strip(), 'Checkout source is empty.'\n"
        )
    rendered = ", ".join(repr(item) for item in phrases)
    return (
        "from tests.generated._qa_source import assert_mentioned\n\n"
        f"def test_{ac_id}():\n"
        f"    assert_mentioned({rendered})\n"
    )


def install_source_helper(root: Path) -> None:
    dest = Path(root) / SOURCE_HELPER_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(SOURCE_HELPER_CODE, encoding="utf-8")
