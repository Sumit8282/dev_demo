# Release Automation Backend

FastAPI backend with LangGraph-orchestrated release validation agents. Jira validation uses the **real Atlassian Rovo MCP** (`https://mcp.atlassian.com/v1/mcp`). GitHub PR comments use the **real official GitHub MCP Server** (remote HTTP or local Docker stdio). There is **no GitHub Agent**—GitHub MCP tools are invoked directly by the Orchestrator.

## Architecture

```
UI
 |
 | POST /api/releases
 v
FastAPI Backend
 |
 v
Orchestrator (LangGraph)
 |
 +----------------------+
 |                      |
 v                      v
Jira Agent         QA Sign-off Agent
 |                      |
 v                      v
Atlassian Rovo MCP   QA Service
 |                      |
 v                      v
Jira                 Sign-off source

Orchestrator (direct)
 |
 v
GitHub MCP
 |
 v
GitHub PR comment (on failure)
```

## Agent responsibilities

| Component | Responsibility |
|-----------|----------------|
| **Orchestrator** | Workflow coordination, delegation, result aggregation, deterministic routing, GitHub MCP PR comment on failure |
| **Jira Agent** | Jira ticket existence, status, Fix Version validation via Rovo MCP |
| **QA Agent** | QA sign-off validation via pluggable QA service |
| **GitHub MCP** | PR read + PR comment (Orchestrator only; no GitHub Agent) |

## LangGraph workflow

```
START
  -> initialize_release
  -> jira_validation
  -> qa_validation
  -> evaluate_validation
  -> conditional_router
       PASS  -> l3_approval_pending -> END
       FAIL  -> github_pr_comment -> END (HALTED)
       ERROR -> validation_error -> END (VALIDATION_ERROR)
```

Final routing is **deterministic code**, not LLM-driven:

```python
if jira.status == PASS and qa.status == PASS:
    workflow_status = L3_APPROVAL_PENDING
elif jira.status == ERROR or qa.status == ERROR:
    workflow_status = VALIDATION_ERROR
else:
    workflow_status = HALTED  # posts GitHub PR comment
```

## Environment variables

Copy `.env.example` to `.env` and fill in values:

| Variable | Description |
|----------|-------------|
| `APP_ENV` | `development` or production |
| `LOG_LEVEL` | Logging level (default `INFO`) |
| `JIRA_MCP_URL` | `https://mcp.atlassian.com/v1/mcp` |
| `JIRA_EMAIL` | Atlassian account email |
| `JIRA_API_TOKEN` | Personal API token (Basic auth) |
| `JIRA_ALLOWED_RELEASE_STATUSES` | Comma-separated valid statuses |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Fine-grained PAT |
| `GITHUB_MCP_TRANSPORT` | `http` (default) or `stdio` |
| `GITHUB_MCP_URL` | Remote MCP URL (default `https://api.githubcopilot.com/mcp/`) |
| `QA_DEV_SIGNOFF_STATUS` | Dev only: `completed` or `missing` |

Credentials are read from environment only. They are **never logged** or returned in API responses.

## Jira Rovo MCP configuration

1. Ensure your Atlassian org admin has enabled **API token authentication** for Rovo MCP.
2. Create a personal API token with Jira read scopes.
3. Set `JIRA_EMAIL` and `JIRA_API_TOKEN`.
4. Auth header is built at runtime: `Authorization: Basic base64(email:api_token)`.

The Jira MCP client discovers available tools dynamically and selects the issue retrieval tool at runtime.

## GitHub MCP configuration

**Option A – Remote HTTP (recommended)**

```env
GITHUB_MCP_TRANSPORT=http
GITHUB_MCP_URL=https://api.githubcopilot.com/mcp/
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

**Option B – Local Docker stdio**

```env
GITHUB_MCP_TRANSPORT=stdio
GITHUB_MCP_DOCKER_IMAGE=ghcr.io/github/github-mcp-server
GITHUB_MCP_TOOLSETS=pull_requests,issues
```

Required PAT permissions (minimum):

- Pull requests: Read & Write (comment and merge)
- Metadata: Read
- Actions: Read (required when `CI_PROVIDER=github_actions` and `CI_TRIGGER_MODE=observe`)
- Actions: Read & write (required when `CI_TRIGGER_MODE=dispatch`)
- Commit statuses: Read (optional)

Do **not** enable admin permissions.

## Release CI/CD (GitHub Actions)

After a successful merge, the Build Agent generates a release build.

| `CI_PROVIDER` | Behavior |
|---|---|
| `stub` (default) | Local demo: invents a `BUILD-YYYYMMDD-XXX` id and continues to RM |
| `github_actions` | Observes or dispatches `.github/workflows/release-build.yml` in the PR repo |

| `CI_TRIGGER_MODE` | Behavior |
|---|---|
| `observe` (default) | Finds the workflow run for `merge_sha` and polls until it finishes |
| `dispatch` | Calls `workflow_dispatch` on `GITHUB_ACTIONS_WORKFLOW`, then polls |

Failed runs set `workflow_status=BUILD_FAILED` and do **not** create an RM approval request.

## How to run

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt
copy .env.example .env        # configure credentials
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Health check: `GET http://localhost:8000/health`

## How to test MCP connectivity

```bash
cd backend
python -m scripts.test_mcp_connectivity
```

This verifies:

1. Jira Rovo MCP authentication and tool discovery
2. GitHub MCP authentication and tool discovery

Credentials must be present in `.env`. Missing credentials produce a clear SKIP/FAIL message without exposing secrets.

## API examples

### POST /api/releases

```json
{
  "release_branch": "release/v2.4.0",
  "github_pr_url": "https://github.com/company/repository/pull/123",
  "jira_url": "https://company.atlassian.net/browse/ABC-123",
  "qa_signoff_required": true,
  "environment": "UAT2",
  "release_date": "2026-08-15"
}
```

**Response (202):**

```json
{
  "release_id": "REL-A1B2C3D4",
  "workflow_status": "VALIDATING",
  "message": "Release workflow started."
}
```

### GET /api/releases/{release_id}

Poll until `workflow_status` is terminal.

**PASS example:**

```json
{
  "workflow_status": "L3_APPROVAL_PENDING",
  "overall_validation_status": "PASS",
  "jira_validation": { "status": "PASS", ... },
  "qa_validation": { "status": "PASS", ... },
  "github_comment_posted": false
}
```

**FAIL example:**

```json
{
  "workflow_status": "HALTED",
  "overall_validation_status": "FAIL",
  "failure_reasons": ["QA sign-off is required but has not been completed."],
  "github_comment_posted": true
}
```

## Running tests

```bash
cd backend
pytest -v
```

Unit tests mock MCP client interfaces at the boundary. Production code uses real MCP integrations.

## Gmail SMTP (L3 and RM approval notifications)

When validations pass and `MAIL_ENABLED=true`, L3 and RM approval notifications are sent via Gmail SMTP.

### Gmail setup

1. Create a dedicated Gmail account for release notifications (or use an existing one).
2. Enable **2-Step Verification** on the Google account.
3. Create an **App password**: Google Account → Security → 2-Step Verification → App passwords.
4. Set `GMAIL_USER` to the Gmail address and `GMAIL_APP_PASSWORD` to the 16-character app password.

### Environment variables

| Variable | Description |
|----------|-------------|
| `MAIL_ENABLED` | `true` to send L3/RM approval emails |
| `GMAIL_USER` | Gmail account address (SMTP login) |
| `GMAIL_APP_PASSWORD` | Google App Password (not your regular Gmail password) |
| `MAIL_FROM` | Optional From address (defaults to `GMAIL_USER`) |
| `L3_MANAGER_EMAIL` | Comma-separated L3 recipient(s) |
| `RM_MANAGER_EMAIL` | Comma-separated RM recipient(s) |
| `PORTAL_BASE_URL` | Frontend base URL for approval links |

### Test mail send

Preview only (no email sent):

```bash
cd backend
python -m scripts.test_mail_send
python -m scripts.test_rm_mail_send
```

Send a test email explicitly:

```bash
python -m scripts.test_mail_send --send
python -m scripts.test_rm_mail_send --send
```

Production L3 and RM notifications are sent automatically when the release workflow
completes from the UI — no JSON drafts are stored on disk.

## Security considerations

- API tokens stored in `.env` only; `.env` is gitignored
- Least-privilege GitHub PAT (PR comment + read only)
- Jira MCP read-only validation (no Jira writes in this phase)
- No silent fallback from MCP to direct REST APIs
- External service failures yield `VALIDATION_ERROR`, never PASS

## Replacing MCP configuration later

- **Jira**: Update `JIRA_MCP_URL`, credentials, or allowed statuses in `.env`
- **GitHub**: Switch `GITHUB_MCP_TRANSPORT` between `http` and `stdio`, or change `GITHUB_MCP_URL` / Docker image
- **QA**: Replace `ProductionQAService` in `app/services/qa_service.py` with your real sign-off source

Tool names are discovered at runtime—no hard-coded Jira/GitHub tool names in business logic.
