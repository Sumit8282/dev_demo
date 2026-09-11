"""Generated-test phrase helper unit tests."""

from pathlib import Path

import pytest

from app.models.qa_llm_validation import QAAcceptanceCriterion, QAGeneratedTest
from app.services.generated_test_runner import GeneratedTestRunner
from app.services.generated_test_source import (
    build_generated_test_code,
    phrases_for_acceptance_criterion,
)
from tests.test_generated_test_runner import _settings


def test_phrases_use_strings_that_exist_in_source():
    source = 'export const urls = { mcpFactory: "https://demo.example/mcp" };\n'
    phrases = phrases_for_acceptance_criterion(
        "Clicking MCP Factory navigates to the correct Demo URL.",
        source,
    )
    assert "mcpFactory" in phrases or "demo" in " ".join(phrases).lower()
    assert "demoUrl" not in phrases
    assert "correctly" not in phrases


def test_navigation_ac_ignores_generic_adverbs():
    source = 'function onClick() { window.location.href = urls.mcpFactory }\n'
    phrases = phrases_for_acceptance_criterion(
        "Navigation works correctly without errors.",
        source,
    )
    assert "correctly" not in phrases
    assert any(item in phrases for item in ("onClick", "href", "navigate"))


@pytest.mark.asyncio
async def test_built_script_passes_when_ac_phrase_exists(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Offerings.tsx").write_text(
        'const cards = [{ name: "MCP Factory", href: "https://demo.example/mcp" }];\n',
        encoding="utf-8",
    )
    criterion = QAAcceptanceCriterion(
        ac_id="AC-02",
        text="Clicking MCP Factory navigates to the correct Demo URL.",
    )
    code = build_generated_test_code(criterion, (tmp_path / "src" / "Offerings.tsx").read_text())
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-02",
                generated_test="test_ac_02",
                test_file="tests/generated/ac-02_test.py",
                test_code=code,
            )
        ],
        owner="satalkar21",
        repo="AI_Studio_Main",
        sha="7acb47ea",
        checkout_dir=tmp_path,
    )
    assert results[0].status == "PASS"
