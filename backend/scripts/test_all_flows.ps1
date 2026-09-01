# End-to-end release workflow tester (PowerShell wrapper)
#
# 1. Start backend first:
#    cd backend
#    .venv\Scripts\activate
#    uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
#
# 2. Fill in your real URLs below, then run:
#    .\scripts\test_all_flows.ps1
#
# Optional: verify MCP connectivity first
#    python scripts\test_mcp_connectivity.py

param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$GithubPrUrl = "",          # e.g. https://github.com/OWNER/REPO/pull/123
    [string]$JiraUrlPass = "",          # Jira ticket that should PASS
    [string]$JiraUrlFail = "",          # Jira ticket that should FAIL (optional)
    [string]$ReleaseBranch = "",        # e.g. release/v2.4.0 (must match Jira fix version)
    [string]$Environment = "UAT2",
    [string]$Scenario = "all",          # all | pass | qa_fail | jira_fail | both_fail
    [int]$Timeout = 120
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot\..

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Error "Virtual env not found. Run from backend/ after: python -m venv .venv"
}

if (-not $GithubPrUrl) {
    $GithubPrUrl = Read-Host "GitHub PR URL (https://github.com/owner/repo/pull/123)"
}
if (-not $JiraUrlPass) {
    $JiraUrlPass = Read-Host "Jira URL PASS (valid ticket for release)"
}
if (-not $JiraUrlFail) {
    $JiraUrlFail = Read-Host "Jira URL FAIL (invalid ticket, or press Enter to reuse PASS URL)"
    if (-not $JiraUrlFail) { $JiraUrlFail = $JiraUrlPass }
}
if (-not $ReleaseBranch) {
    $ReleaseBranch = Read-Host "Release branch (e.g. release/v2.4.0)"
}

$argsList = @(
    "scripts/test_all_flows.py",
    "--base-url", $BaseUrl,
    "--github-pr-url", $GithubPrUrl,
    "--jira-url-pass", $JiraUrlPass,
    "--jira-url-fail", $JiraUrlFail,
    "--release-branch", $ReleaseBranch,
    "--environment", $Environment,
    "--scenario", $Scenario,
    "--timeout", $Timeout
)

Write-Host "`n=== MCP connectivity (optional pre-check) ===" -ForegroundColor Cyan
& .venv\Scripts\python.exe scripts/test_mcp_connectivity.py
if ($LASTEXITCODE -ne 0) {
    Write-Warning "MCP connectivity check failed. Fix .env and restart backend before flow tests."
}

Write-Host "`n=== Running workflow scenarios ===" -ForegroundColor Cyan
& .venv\Scripts\python.exe @argsList
exit $LASTEXITCODE
