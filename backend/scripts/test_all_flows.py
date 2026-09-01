"""End-to-end release workflow tester against a running FastAPI backend.

Uses real Jira Rovo MCP and GitHub MCP through the API (no mocks).

Examples (from backend/ with venv active):

  # Run all scenarios
  python scripts/test_all_flows.py ^
    --github-pr-url https://github.com/satalkar21/AI_Studio_Main/pull/1 ^
    --jira-url-pass PR - https://xoriant-team-d79bg42j.atlassian.net/browse/SCRUM-6 ^
    --jira-url-fail https://YOUR-DOMAIN.atlassian.net/browse/BAD-999 ^
    --release-branch feature/SCRUM-6-offerings


  # Single scenario (posts a real GitHub PR comment on failure flows)
  python scripts/test_all_flows.py --scenario qa_fail --github-pr-url ... --jira-url-pass ...

Environment variable fallbacks:
  TEST_BASE_URL, TEST_GITHUB_PR_URL, TEST_JIRA_URL_PASS, TEST_JIRA_URL_FAIL,
  TEST_RELEASE_BRANCH, TEST_ENVIRONMENT, TEST_RELEASE_DATE
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

# Allow `python scripts/test_all_flows.py` from backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

TERMINAL_STATUSES = {"L3_APPROVAL_PENDING", "HALTED", "VALIDATION_ERROR"}


@dataclass(frozen=True)
class Scenario:
    name: str
    description: str
    qa_signoff_required: bool
    jira_url_key: str  # "pass" or "fail"
    expected_workflow_status: str
    expect_github_comment: bool | None  # None = don't assert
    qa_signoff_not_required_reason: str | None = None


DEFAULT_QA_NOT_REQUIRED_REASON = "Automated test – QA sign-off not required"


SCENARIOS: dict[str, Scenario] = {
    "pass": Scenario(
        name="pass",
        description="Jira PASS + QA PASS (qa_signoff_required=false) -> L3_APPROVAL_PENDING",
        qa_signoff_required=False,
        jira_url_key="pass",
        expected_workflow_status="L3_APPROVAL_PENDING",
        expect_github_comment=False,
        qa_signoff_not_required_reason="Automated test – QA sign-off not required",
    ),
    "pass_with_qa": Scenario(
        name="pass_with_qa",
        description="Jira PASS + QA PASS with sign-off required (set QA_DEV_SIGNOFF_STATUS=completed, restart server)",
        qa_signoff_required=True,
        jira_url_key="pass",
        expected_workflow_status="L3_APPROVAL_PENDING",
        expect_github_comment=False,
    ),
    "qa_fail": Scenario(
        name="qa_fail",
        description="Jira PASS + QA FAIL -> HALTED + GitHub PR comment",
        qa_signoff_required=True,
        jira_url_key="pass",
        expected_workflow_status="HALTED",
        expect_github_comment=True,
    ),
    "jira_fail": Scenario(
        name="jira_fail",
        description="Jira FAIL + QA PASS -> HALTED + GitHub PR comment",
        qa_signoff_required=False,
        jira_url_key="fail",
        expected_workflow_status="HALTED",
        expect_github_comment=True,
        qa_signoff_not_required_reason=DEFAULT_QA_NOT_REQUIRED_REASON,
    ),
    "both_fail": Scenario(
        name="both_fail",
        description="Jira FAIL + QA FAIL -> HALTED + GitHub PR comment with both failures",
        qa_signoff_required=True,
        jira_url_key="fail",
        expected_workflow_status="HALTED",
        expect_github_comment=True,
    ),
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _print_json(label: str, payload: Any) -> None:
    print(f"\n{label}")
    print(json.dumps(payload, indent=2, default=str))


def _wait_for_terminal(
    client: httpx.Client,
    release_id: str,
    *,
    timeout_seconds: int,
    poll_interval: float,
) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_status = "VALIDATING"

    while time.time() < deadline:
        response = client.get(f"/api/releases/{release_id}")
        response.raise_for_status()
        state = response.json()
        workflow_status = state.get("workflow_status", "VALIDATING")
        last_status = workflow_status

        if workflow_status in TERMINAL_STATUSES:
            return state

        print(f"  ... still {workflow_status}, waiting {poll_interval}s")
        time.sleep(poll_interval)

    raise TimeoutError(
        f"Release {release_id} did not reach a terminal status within {timeout_seconds}s "
        f"(last status: {last_status})"
    )


def _submit_release(
    client: httpx.Client,
    *,
    release_branch: str,
    github_pr_url: str,
    jira_url: str,
    qa_signoff_required: bool,
    environment: str,
    release_date: str,
    qa_signoff_not_required_reason: str | None = None,
) -> str:
    payload = {
        "release_branch": release_branch,
        "github_pr_url": github_pr_url,
        "jira_url": jira_url,
        "qa_signoff_required": qa_signoff_required,
        "environment": environment,
        "release_date": release_date,
    }
    if not qa_signoff_required and qa_signoff_not_required_reason:
        payload["qa_signoff_not_required_reason"] = qa_signoff_not_required_reason
    response = client.post("/api/releases", json=payload)
    if response.status_code == 422:
        raise ValueError(f"Invalid request: {response.json()}")
    response.raise_for_status()
    body = response.json()
    return body["release_id"]


def _assert_scenario(scenario: Scenario, state: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    workflow_status = state.get("workflow_status")
    if workflow_status != scenario.expected_workflow_status:
        errors.append(
            f"Expected workflow_status={scenario.expected_workflow_status}, got {workflow_status}"
        )

    if scenario.expect_github_comment is not None:
        posted = bool(state.get("github_comment_posted"))
        if posted != scenario.expect_github_comment:
            errors.append(
                f"Expected github_comment_posted={scenario.expect_github_comment}, got {posted}"
            )

    jira_validation = state.get("jira_validation") or {}
    qa_validation = state.get("qa_validation") or {}

    if scenario.name in {"pass", "pass_with_qa", "qa_fail"}:
        if jira_validation.get("status") != "PASS":
            errors.append(f"Expected Jira PASS, got {jira_validation.get('status')}")

    if scenario.name in {"jira_fail", "both_fail"}:
        if jira_validation.get("status") == "PASS":
            errors.append(
                "Expected Jira FAIL for jira_fail/both_fail, but Jira returned PASS. "
                "Use a Jira ticket with invalid status or fix version (--jira-url-fail)."
            )

    if scenario.name in {"pass", "pass_with_qa", "jira_fail"}:
        if qa_validation.get("status") != "PASS":
            errors.append(f"Expected QA PASS, got {qa_validation.get('status')}")

    if scenario.name in {"qa_fail", "both_fail"}:
        if qa_validation.get("status") != "FAIL":
            errors.append(f"Expected QA FAIL, got {qa_validation.get('status')}")

    return errors


def _run_scenario(
    client: httpx.Client,
    scenario: Scenario,
    *,
    release_branch: str,
    github_pr_url: str,
    jira_urls: dict[str, str],
    environment: str,
    release_date: str,
    timeout_seconds: int,
    poll_interval: float,
) -> bool:
    print("\n" + "=" * 72)
    print(f"SCENARIO: {scenario.name}")
    print(scenario.description)
    print("=" * 72)

    jira_url = jira_urls[scenario.jira_url_key]
    print(f"  release_branch      : {release_branch}")
    print(f"  github_pr_url       : {github_pr_url}")
    print(f"  jira_url            : {jira_url}")
    print(f"  qa_signoff_required : {scenario.qa_signoff_required}")

    release_id = _submit_release(
        client,
        release_branch=release_branch,
        github_pr_url=github_pr_url,
        jira_url=jira_url,
        qa_signoff_required=scenario.qa_signoff_required,
        qa_signoff_not_required_reason=scenario.qa_signoff_not_required_reason,
        environment=environment,
        release_date=release_date,
    )
    print(f"  release_id          : {release_id}")

    state = _wait_for_terminal(
        client,
        release_id,
        timeout_seconds=timeout_seconds,
        poll_interval=poll_interval,
    )
    _print_json("Final state:", state)

    errors = _assert_scenario(scenario, state)
    if errors:
        print("RESULT: FAIL")
        for error in errors:
            print(f"  - {error}")
        if state.get("failure_reasons"):
            print("  failure_reasons:")
            for reason in state["failure_reasons"]:
                print(f"    * {reason}")
        return False

    print("RESULT: PASS")
    if scenario.expect_github_comment:
        print("  -> Check your GitHub PR for the validation failure comment.")
    return True


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test all release workflow flows via FastAPI.")
    parser.add_argument(
        "--base-url",
        default=_env("TEST_BASE_URL", "http://localhost:8000"),
        help="FastAPI base URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--github-pr-url",
        default=_env("TEST_GITHUB_PR_URL"),
        required=not bool(_env("TEST_GITHUB_PR_URL")),
        help="Real GitHub PR URL, e.g. https://github.com/owner/repo/pull/123",
    )
    parser.add_argument(
        "--jira-url-pass",
        default=_env("TEST_JIRA_URL_PASS"),
        required=not bool(_env("TEST_JIRA_URL_PASS")),
        help="Jira ticket that should PASS validation (valid status + matching fix version)",
    )
    parser.add_argument(
        "--jira-url-fail",
        default=_env("TEST_JIRA_URL_FAIL", _env("TEST_JIRA_URL_PASS")),
        help="Jira ticket that should FAIL validation (wrong status/fix version). Defaults to --jira-url-pass.",
    )
    parser.add_argument(
        "--release-branch",
        default=_env("TEST_RELEASE_BRANCH"),
        required=not bool(_env("TEST_RELEASE_BRANCH")),
        help="Release branch (any format; release/vX.Y.Z extracts version for Jira fix-version check)",
    )
    parser.add_argument(
        "--environment",
        default=_env("TEST_ENVIRONMENT", "UAT2"),
        help="Target environment (default: UAT2)",
    )
    parser.add_argument(
        "--release-date",
        default=_env("TEST_RELEASE_DATE", date.today().isoformat()),
        help="Release date YYYY-MM-DD (default: today)",
    )
    parser.add_argument(
        "--scenario",
        default="all",
        help="Scenario name or comma-separated list, or 'all' (default: all)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=120,
        help="Seconds to wait for workflow completion (default: 120)",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=2.0,
        help="Polling interval in seconds (default: 2)",
    )
    parser.add_argument(
        "--skip-health-check",
        action="store_true",
        help="Skip GET /health before running scenarios",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    if args.scenario == "all":
        selected = ["pass", "qa_fail", "jira_fail", "both_fail"]
    else:
        selected = [part.strip() for part in args.scenario.split(",") if part.strip()]

    unknown = [name for name in selected if name not in SCENARIOS]
    if unknown:
        print(f"Unknown scenario(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(SCENARIOS)}")
        return 2

    print("Release Automation – full flow tester")
    print(f"Backend: {args.base_url}")
    print(f"Scenarios: {', '.join(selected)}")

    if "pass_with_qa" in selected or (
        args.scenario == "all" and _env("TEST_INCLUDE_QA_PASS")
    ):
        print(
            "\nNote: pass_with_qa requires QA_DEV_SIGNOFF_STATUS=completed in .env "
            "and a backend restart."
        )

    if args.jira_url_fail == args.jira_url_pass and any(
        name in selected for name in ("jira_fail", "both_fail")
    ):
        print(
            "\nWarning: --jira-url-fail is the same as --jira-url-pass. "
            "jira_fail / both_fail may not produce Jira FAIL unless the ticket "
            "does not match --release-branch fix version."
        )

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30.0) as client:
        if not args.skip_health_check:
            health = client.get("/health")
            health.raise_for_status()
            print(f"Health: {health.json()}")

        jira_urls = {"pass": args.jira_url_pass, "fail": args.jira_url_fail}
        results: dict[str, bool] = {}

        for name in selected:
            ok = _run_scenario(
                client,
                SCENARIOS[name],
                release_branch=args.release_branch,
                github_pr_url=args.github_pr_url,
                jira_urls=jira_urls,
                environment=args.environment,
                release_date=args.release_date,
                timeout_seconds=args.timeout,
                poll_interval=args.poll_interval,
            )
            results[name] = ok

    print("\n" + "=" * 72)
    print("SUMMARY")
    print("=" * 72)
    for name, ok in results.items():
        print(f"  {name:16} {'PASS' if ok else 'FAIL'}")

    passed = sum(1 for ok in results.values() if ok)
    print(f"\nTotal: {passed}/{len(results)} passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
