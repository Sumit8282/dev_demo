"""Execute agent-generated tests against a live GitHub PR checkout."""

from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

from app.config import Settings, get_settings
from app.models.qa_llm_validation import QAGeneratedTest
from app.services.generated_test_source import install_source_helper

logger = logging.getLogger(__name__)

_RUN_TIMEOUT_SECONDS = 45
_CLONE_TIMEOUT_SECONDS = 120
_ZIP_TIMEOUT_SECONDS = 120
GITHUB_API_URL = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class GeneratedTestRunner:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _token(self) -> str:
        try:
            raw = self.settings.github_personal_access_token.get_secret_value()
            return raw.strip() if isinstance(raw, str) else ""
        except Exception:
            return ""

    async def run(
        self,
        tests: list[QAGeneratedTest],
        *,
        owner: str = "",
        repo: str = "",
        sha: str = "",
        checkout_dir: Path | None = None,
    ) -> list[QAGeneratedTest]:
        owner = owner.strip()
        repo = repo.strip()
        sha = sha.strip()
        if checkout_dir is not None:
            return await self._run_in_checkout(tests, checkout_dir, owner=owner, repo=repo, sha=sha)
        if owner and repo and sha:
            with tempfile.TemporaryDirectory(
                prefix="qa-github-",
                ignore_cleanup_errors=True,
            ) as tmp:
                dest = Path(tmp) / "repo"
                dest.mkdir()
                try:
                    await self._checkout_github_sha(owner, repo, sha, dest)
                except Exception as exc:
                    detail = _format_exc(exc)
                    logger.warning("[GENERATED_TEST] GitHub checkout failed: %s", detail)
                    failed: list[QAGeneratedTest] = []
                    for item in tests:
                        item.status = "FAIL"
                        item.reason = f"Could not clone GitHub {owner}/{repo}@{sha}: {detail}"
                        failed.append(item)
                    return failed
                return await self._run_in_checkout(
                    tests, dest, owner=owner, repo=repo, sha=sha
                )
        return [await self._run_isolated(item) for item in tests]

    async def _checkout_github_sha(
        self, owner: str, repo: str, sha: str, dest: Path
    ) -> None:
        errors: list[str] = []
        try:
            await self._download_github_zipball(owner, repo, sha, dest)
            return
        except Exception as exc:
            errors.append(f"zipball {_format_exc(exc)}")
            logger.warning("[GENERATED_TEST] Zipball checkout failed, trying git: %s", errors[-1])
        try:
            await self._clone_with_git(owner, repo, sha, dest)
        except Exception as exc:
            errors.append(f"git {_format_exc(exc)}")
            raise RuntimeError("; ".join(errors)) from exc

    async def _download_github_zipball(
        self, owner: str, repo: str, sha: str, dest: Path
    ) -> None:
        token = self._token()
        if not token:
            raise RuntimeError("GitHub token is not configured.")
        logger.info("[GENERATED_TEST] Downloading %s/%s@%s zipball", owner, repo, sha)
        content = await self._http_get_bytes(
            f"{GITHUB_API_URL}/repos/{owner}/{repo}/zipball/{sha}",
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": GITHUB_API_VERSION,
                "Authorization": f"Bearer {token}",
                "User-Agent": "release-portal-qa",
            },
        )
        self._extract_zipball(content, dest)

    async def _http_get_bytes(self, url: str, headers: dict[str, str]) -> bytes:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, read=_ZIP_TIMEOUT_SECONDS),
            follow_redirects=True,
        ) as client:
            response = await client.get(url, headers=headers)
            if response.status_code >= 400:
                raise RuntimeError(
                    f"GitHub zipball HTTP {response.status_code}: {response.text[:200] or 'no body'}"
                )
            return response.content

    def _extract_zipball(self, content: bytes, dest: Path) -> None:
        if not content:
            raise RuntimeError("GitHub zipball was empty.")
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            archive.extractall(dest)
        children = [path for path in dest.iterdir() if path.name != "__MACOSX"]
        if len(children) == 1 and children[0].is_dir():
            root = children[0]
            for item in root.iterdir():
                target = dest / item.name
                if target.exists():
                    raise RuntimeError(f"Zipball extracted a conflicting path: {item.name}")
                shutil.move(str(item), str(target))
            root.rmdir()

    async def _clone_with_git(self, owner: str, repo: str, sha: str, dest: Path) -> None:
        git = _git_executable()
        token = self._token()
        remote = f"https://github.com/{owner}/{repo}.git"
        if token:
            remote = f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
        logger.info("[GENERATED_TEST] Cloning %s/%s@%s with %s", owner, repo, sha, git)
        await self._run_git([git, "init"], cwd=dest)
        await self._run_git([git, "remote", "add", "origin", remote], cwd=dest)
        await self._run_git(
            [git, "fetch", "--depth", "1", "origin", sha],
            cwd=dest,
            timeout=_CLONE_TIMEOUT_SECONDS,
        )
        await self._run_git([git, "checkout", "--force", "FETCH_HEAD"], cwd=dest)

    async def _run_git(
        self,
        command: list[str],
        *,
        cwd: Path,
        timeout: int = 30,
    ) -> None:
        try:
            result = await _run_process(command, cwd=cwd, timeout=timeout)
        except FileNotFoundError as exc:
            raise RuntimeError(f"git executable was not found: {_format_exc(exc)}") from exc
        except subprocess.TimeoutExpired:
            raise RuntimeError(f"{_safe_command(command)} timed out after {timeout}s")
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or b"").decode("utf-8", errors="replace")[-300:]
            raise RuntimeError(
                f"{_safe_command(command)} failed: {_redact_secrets(detail) or 'no output'}"
            )

    async def _run_in_checkout(
        self,
        tests: list[QAGeneratedTest],
        checkout: Path,
        *,
        owner: str,
        repo: str,
        sha: str,
    ) -> list[QAGeneratedTest]:
        install_source_helper(checkout)
        results: list[QAGeneratedTest] = []
        for item in tests:
            result = await self._run_one(item, checkout)
            prefix = (
                f"Ran against GitHub {owner}/{repo}@{sha}. "
                if owner and repo and sha
                else "Ran against GitHub checkout. "
            )
            result.reason = prefix + (result.reason or "")
            results.append(result)
        return results

    async def _run_isolated(self, item: QAGeneratedTest) -> QAGeneratedTest:
        with tempfile.TemporaryDirectory(prefix="qa-generated-") as tmp:
            return await self._run_one(item, Path(tmp), isolated=True)

    async def _run_one(
        self,
        item: QAGeneratedTest,
        root: Path,
        *,
        isolated: bool = False,
    ) -> QAGeneratedTest:
        code = (item.test_code or "").strip()
        if not code:
            item.status = "FAIL"
            item.reason = "Generated test script is empty."
            return item
        forbidden = _forbidden_import(code)
        if forbidden:
            item.status = "FAIL"
            item.reason = (
                f"Generated test imported {forbidden}. "
                "Use Python stdlib pathlib/re to read source files in the checkout."
            )
            return item

        try:
            script = self._safe_script_path(root, item.test_file, isolated=isolated)
        except ValueError as exc:
            item.status = "FAIL"
            item.reason = str(exc)
            return item
        script.parent.mkdir(parents=True, exist_ok=True)
        script.write_text(code + "\n", encoding="utf-8")

        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(root), env.get("PYTHONPATH", "")]
        ).rstrip(os.pathsep)
        env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
        env["PYTEST_ADDOPTS"] = ""

        command = [
            sys.executable,
            "-m",
            "pytest",
            str(script),
            "-q",
            "--tb=short",
            "--noconftest",
            "--rootdir",
            str(root),
            "-o",
            "addopts=",
        ]
        try:
            result = await _run_process(
                command,
                cwd=root,
                env=env,
                timeout=_RUN_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            item.status = "FAIL"
            item.reason = f"Generated test timed out after {_RUN_TIMEOUT_SECONDS}s."
            return item

        output = ((result.stdout or b"") + b"\n" + (result.stderr or b"")).decode(
            "utf-8", errors="replace"
        )
        snippet = " ".join(output.strip().split())[-400:]
        if result.returncode == 0:
            item.status = "PASS"
            item.reason = snippet or "Pytest completed successfully."
        else:
            item.status = "FAIL"
            item.reason = snippet or "Pytest failed."
        logger.info(
            "[GENERATED_TEST] %s %s -> %s",
            item.ac_id,
            item.generated_test or item.test_file,
            item.status,
        )
        return item

    def _safe_script_path(self, root: Path, test_file: str, *, isolated: bool) -> Path:
        if isolated:
            return root / "test_generated.py"
        raw = (test_file or "tests/test_generated.py").replace("\\", "/").lstrip("/")
        if not raw or ".." in raw.split("/"):
            raise ValueError("Generated test file path is invalid.")
        resolved = (root / raw).resolve()
        try:
            resolved.relative_to(root.resolve())
        except ValueError as exc:
            raise ValueError("Generated test file path escapes the GitHub checkout.") from exc
        return resolved


async def _run_process(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None = None,
    timeout: int,
) -> subprocess.CompletedProcess[bytes]:
    return await asyncio.to_thread(
        subprocess.run,
        command,
        cwd=str(cwd),
        env=env,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


_FORBIDDEN_IMPORTS = (
    "selenium",
    "playwright",
    "playwright.sync_api",
    "requests",
    "httpx",
)


def _forbidden_import(code: str) -> str:
    lowered = code.lower()
    for name in _FORBIDDEN_IMPORTS:
        if f"import {name}" in lowered or f"from {name}" in lowered:
            return name
    return ""


def _git_executable() -> str:
    found = shutil.which("git")
    if found:
        return found
    candidates = [
        Path.home() / "AppData/Local/Programs/Git/cmd/git.exe",
        Path(r"C:\Program Files\Git\cmd\git.exe"),
        Path(r"C:\Program Files\Git\bin\git.exe"),
        Path(r"C:\Program Files (x86)\Git\cmd\git.exe"),
    ]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise RuntimeError("git executable was not found on PATH")


def _format_exc(exc: BaseException) -> str:
    text = str(exc).strip() or repr(exc)
    return _redact_secrets(f"{type(exc).__name__}: {text}")


def _safe_command(command: list[str]) -> str:
    return " ".join(_redact_secrets(part) for part in command)


def _redact_secrets(text: str) -> str:
    token_prefix = "x-access-token:"
    if token_prefix not in text:
        return text
    start = text.find(token_prefix)
    end = text.find("@", start)
    if end == -1:
        return text.replace(token_prefix, "x-access-token:***")
    return text[: start + len(token_prefix)] + "***" + text[end:]
