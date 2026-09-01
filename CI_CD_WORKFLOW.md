# CI/CD Workflow

This document describes the post-merge CI/CD step in the release portal: how a **build ID** is produced, which GitHub Actions files are involved, and how to get a **real** `GHA-` id instead of a stub `BUILD-` id.

The rest of the release flow (GitHub / Jira / QA validation, L3, merge, RM, deployment) is in [WORKFLOW.md](./WORKFLOW.md).

## 1. Where CI/CD sits

CI/CD starts **only after a successful PR merge**. It does not run during validation or L3.

```text
Create release (PR URL + release branch + Jira)
    → GitHub / Jira / QA validation
    → L3 approve (or auto-approve if LOW risk)
    → Merge PR on GitHub
    → CI/CD build          ← this document
    → RM approve
    → Deployment complete
```

The portal does not compile the application itself. GitHub Actions in the **PR repo** does. The portal finds or starts that run, stores the **build ID**, then continues to RM.

## 2. What a build ID is

A **build ID** is the unique name of **one CI run** after merge. Later steps (RM, Jira comments, UI) refer to that build, not only to the PR.

| Example | Meaning |
|---|---|
| `GHA-123456789` | Real GitHub Actions run id |
| `BUILD-20260828-782` | Stub / fake id (no Actions run) |

Use:

- RM approval screen and email (which artifact to deploy)
- Jira comment after build and after deployment
- Release details, workflow events, and dashboard `buildId`

## 3. Runtime flow

Current settings: `CI_PROVIDER=github_actions`, `CI_TRIGGER_MODE=dispatch`.

`dispatch` starts `release-build.yml` with portal inputs (`release_id`, `release_version`, `environment`) so they appear in the job log. `observe` finds a `push` run first; those inputs stay empty.

The portal uses the **Release Branch** from the New Release form (for this project: **`Release-v1`**). It does **not** fall back to `main` or `master`.

```text
MERGED
    → workflow_status = BUILD_PENDING
    → POST workflow_dispatch on Release-v1
         owner/repo from the PR URL
         workflow = release-build.yml
         inputs = release_id, release_version, environment
    → Wait until that run finishes
    → Success → BUILD_COMPLETED → Jira build comment → RM_APPROVAL_PENDING
    → Failure → BUILD_FAILED → stop (no RM)
```

If `CI_FALLBACK_TO_STUB=true`, a missing workflow produces a fake `BUILD-...` id and still goes to RM. That is **off** in the current `.env` (`false`).

### Statuses

| Status | Meaning |
|---|---|
| `BUILD_PENDING` | Looking for or waiting on the Actions run |
| `BUILD_COMPLETED` | Run succeeded; RM can start |
| `BUILD_FAILED` | No workflow, dispatch failed, tests failed, or timeout |

## 4. GitHub Actions files

| File in **this portal** | Purpose |
|---|---|
| [`.github/workflows/release-build.yml`](./.github/workflows/release-build.yml) | Release build job. **Copy this into the PR repo.** |
| [`.github/workflows/ci.yml`](./.github/workflows/ci.yml) | Portal-only CI (pytest + frontend build). **Do not copy** to the app repo. If it is already there, delete it. |

`release-build.yml` currently:

- Triggers on `push` and `workflow_dispatch`
- Checks out the repo
- Prints `release_id`, version, environment (portal inputs on dispatch; fallbacks on push), event, branch, commit, and `run_id`

It does not run this portal’s pytest/npm. That keeps it valid in application repos such as `AI_Studio_Main`.

## 5. Portal code that runs CI/CD

| File | Role |
|---|---|
| `backend/app/agents/build_agent.py` | Chooses GitHub Actions vs stub |
| `backend/app/services/github_actions_client.py` | Observe / dispatch / poll GitHub Actions API |
| `backend/app/api/release_routes.py` | `_execute_post_merge_workflow` after merge |
| `backend/app/models/build_result.py` | `build_id`, `job_url`, `commit_sha`, `status` |
| `backend/app/models/release.py` | `BUILD_PENDING`, `BUILD_COMPLETED`, `BUILD_FAILED` |
| `backend/app/config.py` | `CI_*` and `GITHUB_ACTIONS_*` settings |

## 6. Environment variables

Set these in `backend/.env` (see `backend/.env.example`).

| Variable | Typical value | Meaning |
|---|---|---|
| `CI_PROVIDER` | `github_actions` | Use GitHub Actions. `stub` invents `BUILD-...` ids. |
| `CI_TRIGGER_MODE` | `dispatch` | Start a run and pass portal `release_id` / version / environment. `observe` finds a push run first (those inputs stay empty). |
| `GITHUB_ACTIONS_WORKFLOW` | `release-build.yml` | Workflow **filename**, not a URL |
| `CI_FALLBACK_TO_STUB` | `false` | `true` = fake id if Actions is missing |
| `GITHUB_ACTIONS_POLL_INTERVAL_SECONDS` | `10` | Poll interval |
| `GITHUB_ACTIONS_POLL_TIMEOUT_SECONDS` | `1800` | Max wait for a run to finish |
| `GITHUB_ACTIONS_DISCOVER_TIMEOUT_SECONDS` | `120` | Max wait to **find** a run |

No GitHub Actions **URL** is pasted anywhere. The PR URL on the New Release form already identifies `owner/repo`.

## 7. One-time setup for a real `GHA-` id

The workflow must exist in the **PR repository** (example: `satalkar21/AI_Studio_Main`), not only in this portal folder.

### 7.1 Add the workflow file (manual)

1. Open the PR repo on GitHub.
2. Switch to branch **`Release-v1`** (do not use `main` unless that is your release branch).
3. Add `.github/workflows/release-build.yml`.
4. Paste the contents from this portal’s `.github/workflows/release-build.yml`.
5. Commit on **`Release-v1`**.
6. Confirm:

   `https://github.com/<owner>/<repo>/blob/Release-v1/.github/workflows/release-build.yml`

GitHub only registers `workflow_dispatch` from the repo **default branch**. If dispatch still returns 404 after the file is on `Release-v1`, set the default branch to **`Release-v1`** (Settings → General → Default branch).

### 7.2 GitHub PAT

`GITHUB_PERSONAL_ACCESS_TOKEN` in `backend/.env` needs access to the PR repo.

| Permission | Why |
|---|---|
| Pull requests: Read and write | Validate, comment, merge |
| Contents: Read | Read the workflow file on `Release-v1` |
| Metadata: Read | Repo metadata |
| Actions: Read | List and poll runs |
| **Actions: Read and write** | **Start** a run (`workflow_dispatch`) |

A 403 `Resource not accessible by personal access token` on `POST .../dispatches` means Actions **write** is missing.

A 404 on `GET/POST .../release-build.yml` usually means the file is **not** on that branch (or not on the default branch), not that another PAT scope is required.

### 7.3 New Release form

| Field | What to enter |
|---|---|
| Release Branch | `Release-v1` (branch **name**, not a URL) |
| PR | `https://github.com/owner/repo/pull/123` |
| JIRA | Jira issue URL |

Restart the backend after `.env` changes. Create a **new** release after adding the workflow; old releases keep their old build ids.

## 8. Common errors

| Error | Cause | What to do |
|---|---|---|
| `BUILD-YYYYMMDD-XXX` | Stub mode or stub fallback | Set `CI_PROVIDER=github_actions` and `CI_FALLBACK_TO_STUB=false`; add the workflow in the PR repo |
| Workflow GET/POST **404** | File missing on `Release-v1` / default branch | Commit `release-build.yml` on `Release-v1`; optionally set default branch to `Release-v1` |
| Dispatch **403** | PAT cannot start workflows | Actions: Read and write on the PR repo |
| No run within 120s | Merge did not start Actions, dispatch failed | Confirm Actions tab for that commit; check branch name matches `Release-v1` |

## 9. How to tell if the id is real

| Build ID | Real? |
|---|---|
| Starts with `GHA-` | Yes — GitHub Actions run |
| Starts with `BUILD-` | No — stub |

The UI may also show `job_url` pointing at `https://github.com/<owner>/<repo>/actions/runs/<id>`.
