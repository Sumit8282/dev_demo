"""Generated test runner unit tests."""

import asyncio
import io
import zipfile
from pathlib import Path

import pytest
from pydantic import SecretStr

from app.config import Settings
from app.models.qa_llm_validation import QAGeneratedTest
from app.services.generated_test_runner import GeneratedTestRunner


def _settings(token: str = "") -> Settings:
    return Settings(GITHUB_PERSONAL_ACCESS_TOKEN=SecretStr(token))


def _zipball_bytes() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            "satalkar21-AI_Studio_Main-7acb47ea/offerings.py",
            "OFFERINGS = []\n",
        )
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_runner_executes_passing_pytest_file():
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-01",
                generated_test="test_offerings_are_clickable",
                test_file="tests/test_offerings.py",
                summary="Checks offerings cards.",
                status="FAIL",
                test_code="def test_offerings_are_clickable():\n    assert True\n",
            )
        ]
    )

    assert results[0].status == "PASS"
    assert "successfully" in results[0].reason.lower() or results[0].status == "PASS"


@pytest.mark.asyncio
async def test_runner_marks_failing_pytest_file():
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-02",
                generated_test="test_offerings_removed",
                test_file="tests/test_offerings.py",
                summary="Checks offerings removal.",
                status="PASS",
                test_code="def test_offerings_removed():\n    assert False, 'expected failure'\n",
            )
        ]
    )

    assert results[0].status == "FAIL"
    assert results[0].reason


@pytest.mark.asyncio
async def test_runner_skips_empty_script():
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-03",
                generated_test="test_missing",
                test_file="tests/test_missing.py",
                status="PASS",
                test_code="",
            )
        ]
    )

    assert results[0].status == "FAIL"
    assert "empty" in results[0].reason.lower()


@pytest.mark.asyncio
async def test_runner_executes_against_repo_checkout(tmp_path: Path):
    (tmp_path / "offerings.py").write_text("OFFERINGS = []\n", encoding="utf-8")
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-01",
                generated_test="test_offerings_removed",
                test_file="tests/test_offerings.py",
                summary="Uses the checked-out module.",
                test_code=(
                    "from offerings import OFFERINGS\n"
                    "def test_offerings_removed():\n"
                    "    assert OFFERINGS == []\n"
                ),
            )
        ],
        owner="acme",
        repo="app",
        sha="abc1234",
        checkout_dir=tmp_path,
    )

    assert results[0].status == "PASS"
    assert "acme/app@abc1234" in results[0].reason


@pytest.mark.asyncio
async def test_runner_marks_fail_when_clone_fails():
    runner = GeneratedTestRunner(settings=_settings())

    async def boom(*_args, **_kwargs):
        raise RuntimeError("git fetch failed")

    runner._checkout_github_sha = boom  # type: ignore[method-assign]
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-01",
                generated_test="test_offerings_removed",
                test_file="tests/test_offerings.py",
                test_code="def test_offerings_removed():\n    assert True\n",
            )
        ],
        owner="acme",
        repo="app",
        sha="deadbeef",
    )

    assert results[0].status == "FAIL"
    assert "Could not clone GitHub acme/app@deadbeef" in results[0].reason
    assert "RuntimeError" in results[0].reason


@pytest.mark.asyncio
async def test_runner_uses_github_zipball_when_git_is_unavailable(tmp_path: Path):
    runner = GeneratedTestRunner(settings=_settings("test-token"))

    async def fake_zip(_url: str, headers: dict[str, str]) -> bytes:
        assert "zipball/7acb47ea" in _url
        assert headers["Authorization"] == "Bearer test-token"
        return _zipball_bytes()

    async def git_should_not_run(*_args, **_kwargs):
        raise AssertionError("git clone should not run when zipball succeeds")

    runner._http_get_bytes = fake_zip  # type: ignore[method-assign]
    runner._clone_with_git = git_should_not_run  # type: ignore[method-assign]
    dest = tmp_path / "repo"
    dest.mkdir()
    await runner._checkout_github_sha("satalkar21", "AI_Studio_Main", "7acb47ea", dest)
    assert (dest / "offerings.py").read_text(encoding="utf-8") == "OFFERINGS = []\n"

    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-01",
                generated_test="test_offerings_removed",
                test_file="tests/test_offerings.py",
                summary="Uses the downloaded GitHub tree.",
                test_code=(
                    "from offerings import OFFERINGS\n"
                    "def test_offerings_removed():\n"
                    "    assert OFFERINGS == []\n"
                ),
            )
        ],
        owner="satalkar21",
        repo="AI_Studio_Main",
        sha="7acb47ea",
        checkout_dir=dest,
    )

    assert results[0].status == "PASS"
    assert "satalkar21/AI_Studio_Main@7acb47ea" in results[0].reason


@pytest.mark.asyncio
async def test_runner_works_when_asyncio_subprocess_is_unimplemented(monkeypatch):
    async def boom(*_args, **_kwargs):
        raise NotImplementedError()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", boom)
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-01",
                generated_test="test_offerings_are_clickable",
                test_file="tests/test_offerings.py",
                test_code="def test_offerings_are_clickable():\n    assert True\n",
            )
        ]
    )

    assert results[0].status == "PASS"
    assert "Could not clone" not in results[0].reason


@pytest.mark.asyncio
async def test_runner_stdlib_script_can_read_js_source(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "Offerings.tsx").write_text(
        'export const CARDS = [{ name: "MCP Factory", href: "/demo/mcp" }];\n',
        encoding="utf-8",
    )
    runner = GeneratedTestRunner(settings=_settings())
    results = await runner.run(
        [
            QAGeneratedTest(
                ac_id="AC-02",
                generated_test="test_mcp_factory_url",
                test_file="tests/generated/test_ac_02.py",
                test_code=(
                    "from pathlib import Path\n"
                    "def test_mcp_factory_url():\n"
                    "    text = Path('src/Offerings.tsx').read_text(encoding='utf-8')\n"
                    "    assert 'MCP Factory' in text\n"
                    "    assert '/demo/mcp' in text\n"
                ),
            )
        ],
        owner="satalkar21",
        repo="AI_Studio_Main",
        sha="7acb47ea",
        checkout_dir=tmp_path,
    )

    assert results[0].status == "PASS"
