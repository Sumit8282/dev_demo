# Deep Agents Integration Plan (No LangGraph)

This plan adds **Deep Agent capabilities** to the existing release-automation workflow without introducing LangGraph, `create_deep_agent`, or the official `deepagents` package.

The release pipeline stays a **deterministic workflow**. Deep Agents sit *inside* the LLM-heavy steps as a harness (planning, files, subagents, memory). They do not become the source of truth for PASS/FAIL, merge, build, or approvals.

---

## 1. What a Deep Agent is

A normal agent is a tool-calling loop: think → call a tool → append the result → repeat. That is what this repo already does with LangChain `create_agent` in `backend/app/agents/llm_runner.py`.

That loop is **shallow**. After ~10–20 steps it drifts: the original goal falls out of attention, the prompt fills with raw MCP dumps, and one context window holds both the plan and every failed lookup.

Industry systems that stay coherent on long tasks (Claude Code, Deep Research, Manus, LangChain Deep Agents) converge on **four pillars**:

| Pillar | Mechanism | Failure it fixes |
| --- | --- | --- |
| **Planning** | `write_todos` / `todo.md` rewritten each step | Goal drift |
| **Virtual filesystem** | `ls` / `read_file` / `write_file` / `edit_file` | Context overflow |
| **Subagents** | Isolated `task(...)` workers with their own context | Context pollution |
| **Memory** | Persist notes / outcomes across runs | Amnesia between releases |

The model does not get smarter. The **harness** does. The same LLM stays on track when the plan is recited, bulky evidence lives in files, and messy work is delegated.

Token cost is real: Anthropic’s multi-agent research system used about **15×** the tokens of a single chat. Use depth only where the task is open-ended and error-prone, not on every step.

### 1.1 Why we will not use LangGraph

LangChain’s official `deepagents` library (`create_deep_agent`) is an agent harness **built on LangGraph** for durable graphs, checkpoints, and interrupts.

This project already has:

- A fixed release state machine (`VALIDATING` → L3 → merge → build → RM → deploy)
- Deterministic fallback `run_orchestrator_tool_sequence`
- Code-owned gates (Jira AC constraints, QA coverage evaluator)
- Human approvals via FastAPI, not graph interrupts

A LangGraph rewrite would replace the workflow we already trust. **Constraint for this plan: do not add LangGraph, `langgraph`, `deepagents`, or `create_deep_agent`.**

### 1.2 What we will use instead

Implement the four pillars as **plain LangChain tools** on the existing `create_agent` loop:

- `langchain.agents.create_agent` (already in `llm_runner.py`)
- Custom tools: `write_todos`, file tools, `spawn_task`
- `asyncio.gather` for parallel subagents (already used in the QA hybrid)
- In-memory / SQLite workspace per `release_id` (not LangGraph state)
- Existing MCP clients, structured Pydantic outputs, and Python post-processors

This is the same pattern as LangChain’s “deep agents from scratch” notebooks (`write_todos`, virtual files, `task` tool) without compiling a graph.

```text
Existing workflow (deterministic)
    GitHub → Jira → QA → risk/L3 → merge → build → RM → deploy
                         │
                         ▼
Deep harness (only on LLM steps)
    todos + workspace files + isolated subagents + optional memory
                         │
                         ▼
Python still owns PASS/FAIL, merge, CI, approvals
```

---

## 2. Current workflow (where agents already sit)

From `WORKFLOW.md` and the code:

```text
POST /api/releases
        │
        ▼
ReleaseOrchestratorAgent (create_agent + tools)
        │  always followed by run_orchestrator_tool_sequence
        ▼
GitHub MCP checks ──► JiraAgent ──► QAAgent ──► risk + L3Agent
        │                                              │
        │ fail                                         ├─ LOW → MergeAgent
        ▼                                              └─ MED/HIGH → human L3
   HALTED + PR comment                                      │
                                                            ▼
                                                       MergeAgent
                                                            ▼
                                                       BuildAgent (CI)
                                                            ▼
                                                       RMAgent → human RM
                                                            ▼
                                                       deployment + Jira
```

Today’s LLM agents are **shallow specialists**:

| Agent | Today | Already “deep-ish”? |
| --- | --- | --- |
| Orchestrator | One loop, 5 tools, then deterministic fallback | No |
| Jira | One structured call + MCP + AC post-processor | No |
| QA | Hybrid: AC extract ∥ TC extract → mapper → code evaluator | Partial (subagents, no todos/files/memory) |
| L3 | Tools for approval/mail + change-summary service | No |
| Merge / Build / RM | Gates, CI poll, mail | No (should stay that way) |

QA is the only place that already fans out. Deep Agents would complete that pattern (todos + workspace + retry), not replace the orchestrator.

---

## 3. Shared harness (build once, reuse)

Add a small library under `backend/app/agents/deep/` — **not** a new workflow engine.

```text
backend/app/agents/deep/
  todos.py          # write_todos / read_todos
  workspace.py      # virtual FS scoped to release_id
  subagents.py      # spawn_task + asyncio isolation
  memory.py         # optional cross-release notes
  harness.py        # create_agent + deep tools + existing tools
```

### 3.1 Planning (`write_todos`)

A no-op-for-the-world tool that rewrites a structured list into recent context:

```text
pending | in_progress | completed
```

Persist as `workspace://{release_id}/TODO.md` and emit a workflow event so the UI timeline can show the plan.

Rules:

- At most one `in_progress` item
- Recite the full list on every update (that is the point)
- Do not make todos the release state machine

### 3.2 Virtual filesystem

Per-release workspace, default **in-memory**, optional SQLite blob:

```text
releases/{release_id}/
  TODO.md
  github/pr.md
  jira/snapshot.md
  jira/acs.json
  qa/document.txt
  qa/test_cases.json
  qa/coverage_matrix.json
  l3/change_summary.md
  notes.md
```

Tools: `ls`, `read_file`, `write_file`, `edit_file`, `grep`.

Why: Jira descriptions, QA Word dumps, and PR file lists already blow the mapper prompt. Files keep the loop small; the agent reads only what it needs.

Do **not** write secrets, tokens, or raw `.env` into the workspace.

### 3.3 Subagents (`spawn_task`)

```text
spawn_task(name, instruction, tools?) → {status, artifact_path, summary}
```

Each subagent:

- Gets a **fresh** message list (isolation)
- May read/write the same workspace
- Returns a short summary + file path, not the raw dump
- Has a timeout and max tool rounds
- Can run in parallel with `asyncio.gather` when tasks are independent

Named workers we already have conceptually:

- `jira_ac_extractor`
- `qa_tc_extractor`
- `qa_coverage_mapper`
- `l3_change_summarizer`

### 3.4 Memory (phase 2)

Store compact notes keyed by `jira_issue_key` / file path, using the existing `FileFailureHistoryStore` idea:

- “Last time this file failed QA for reason X”
- “This ticket’s ACs usually live in comments”

Read-only into the planner. Never auto-PASS because memory said so.

### 3.5 Hard rules for every insertion

1. **Python owns the gate.** Deep output is a proposal. Existing evaluators (`_apply_authoritative_ac_constraints`, `apply_coverage_constraints`, merge gates, risk scorer) still decide.
2. **Deterministic sequence still runs.** `run_orchestrator_tool_sequence` stays after any LLM orchestrator.
3. **No LangGraph.** No checkpoints-as-workflow, no graph interrupts for L3/RM (those stay HTTP).
4. **Feature flag.** `USE_DEEP_AGENTS=false` by default; existing agents unchanged when off.
5. **Budgets.** Max steps, max subagents, max workspace bytes, per-release token log.
6. **Structured output stays.** Subagents that already return Pydantic models keep doing that.

---

## 4. Insertion points (the whole workflow)

Score: **Add** / **Later** / **Do not add**

### 4.1 Release orchestrator — LATER (thin planner only)

**Files:** `orchestrator_agent.py`, `orchestrator_tools.py`, `orchestrator.py`

**Why it looks attractive:** it already has a `create_agent` loop and tools (`validate_github_pull_request`, `validate_jira_ticket`, `validate_qa_signoff`, `prepare_l3_approval`, `post_release_failure_comment`).

**Why not make it a full Deep Agent first:**

- Order is safety-critical (GitHub before Jira before QA)
- Fallback already guarantees those steps
- A free `spawn_task` here could skip QA or merge early

**What to add later (thin):**

- `write_todos` that *mirrors* the fixed sequence (not invent a new one)
- Write compact tool results to `github/pr.md`, `jira/result.json`, `qa/result.json`
- Do **not** give the orchestrator a generic `spawn_task` that can invent new workflow steps

**Do not** let the Deep Orchestrator own merge/build/RM.

---

### 4.2 GitHub validation — DO NOT ADD

**Files:** `orchestrator.py` (`run_github_validation`), GitHub MCP, `github_fields.py`

This is field extraction and boolean checks (PR exists, open, branch match, comments, change stats). A Deep Agent adds latency and can hallucinate “PR looks fine.”

Optional later: after GitHub **passes**, write a short `github/pr.md` summary for downstream agents. That is a file write, not a Deep Agent.

---

### 4.3 Jira agent — ADD (first high-value slot)

**Files:** `jira_agent.py`, `jira_agent_*.md`, `jira_llm_validation.py`

This is the best first Deep Agent. The work is long-horizon and messy:

1. Fetch issue + comments (MCP)
2. Normalize ACs (code first, LLM if missing)
3. Compare PR title/description/comments/code summary
4. Build requirement matrix
5. Python strips invented ACs and recomputes PASS/FAIL

**Deep shape:**

```text
Jira Deep Agent
  write_todos:
    - prefetch ticket
    - extract ACs
    - map each AC to PR evidence
    - draft matrix
  workspace:
    jira/snapshot.md
    jira/comments.md
    jira/acs.json
    jira/matrix.json
  subagents:
    ac_extractor   (only if code parser empty)
    evidence_mapper (AC list + PR text → matrix rows)
```

Keep `_apply_authoritative_ac_constraints` as the gate. The Deep Agent must not invent AC-07 screenshot rows (the current post-processor already drops those).

---

### 4.4 QA agent — ADD (highest value; extend the hybrid)

**Files:** `qa_agent.py`, `qa_coverage_evaluator.py`, `qa_*` prompts

The hybrid is already a Deep Agent without the name:

- Agent 1 AC extract ∥ Agent 2 TC extract
- Agent 3 mapper
- Code evaluator owns PASS/FAIL

**What to add:**

| Pillar | QA use |
| --- | --- |
| Todos | extract ACs → extract TCs → map → reconcile gaps |
| Files | `qa/document.txt`, `qa/acs.json`, `qa/test_cases.json`, `qa/matrix.json` |
| Subagents | keep the three specialists; mapper reads files, not raw Word dumps |
| Memory (later) | “this project’s QA docs put status in column 4” |

**New deep loop (still no graph):**

1. Write artifacts to the workspace (code + extractors).
2. Mapper reads `acs.json` + `test_cases.json`.
3. `apply_coverage_constraints` runs.
4. If rows are `Unable to Determine` / omitted ACs, **one** `spawn_task("qa_gap_review")` that only re-reads those ACs and the matching TC files.
5. Evaluator runs again. Stop. No unbounded retry.

This is the highest accuracy ROI because QA already failed on omitted ACs, keyword overlap, and fat prompts.

---

### 4.5 Risk scoring — DO NOT ADD (maybe a writer later)

**Files:** `release_risk_scorer.py`

Risk is deterministic (files changed, lines, failure history). Do not let an LLM retune the score.

**Later:** a small summarizer that writes `l3/risk_narrative.md` *from* the computed `ReleaseRiskScore` for the L3 email. It must not change the LOW/MEDIUM/HIGH enum.

---

### 4.6 L3 agent + change summary — ADD (second wave)

**Files:** `l3_agent.py`, `l3_change_summary_service.py`

L3 mail quality is a research/writing task: many files, PR comments, Jira ACs, QA matrix.

**Deep shape:**

```text
L3 Deep Agent
  todos: gather diffs → summarize clusters → draft mail → fact-check against files
  workspace: l3/files/*.md, l3/change_summary.md, l3/mail_draft.md
  subagents:
    diff_clusterer     (group changed files)
    change_summarizer  (already a service; wrap as isolated task)
    mail_drafter       (reads summary + risk, does not invent risk)
```

Human approve/reject stays on `POST /l3/approve|reject`. No “HITL interrupt” runtime.

---

### 4.7 Merge agent — DO NOT ADD

**Files:** `merge_agent.py`

Pre-merge gates + GitHub merge. Wrong tool call is an incorrect merge. Keep deterministic.

---

### 4.8 Build agent — DO NOT ADD

**Files:** `build_agent.py`, `github_actions_client.py`

Observe/dispatch CI and poll. No planning or subagents.

---

### 4.9 RM agent — LATER (draft only)

**Files:** `rm_agent.py`

Same as L3: Deep Agent may **draft** the RM notification from workspace artifacts (`qa/matrix.json`, `l3/change_summary.md`, build result). It must not decide approve/reject.

---

### 4.10 Failure comment + halt path — LATER (small)

When validation fails, a short Deep writer can assemble a better GitHub comment from `jira/matrix.json` + `qa/matrix.json` instead of a generic list. Still one comment, still only after deterministic FAIL.

---

### 4.11 Human approvals and Jira transitions — DO NOT ADD

L3/RM HTTP endpoints, deployment complete, and `JiraWorkflowService` transitions stay code. A Deep Agent must not transition Jira or approve a release.

---

### 4.12 Insertion map

```text
[Add]     Jira Deep Agent          — AC + PR evidence, files, optional extract subagent
[Add]     QA Deep Agent            — extend hybrid with todos, workspace, one gap-review
[Add]     L3 summary Deep Agent    — second wave, writing/research
[Later]   Orchestrator todos/files — mirror sequence only
[Later]   RM / failure-comment drafts
[No]      GitHub checks, risk math, merge, build/CI, approvals, Jira transitions
[No]      LangGraph / official deepagents package
```

Priority if we do only two: **QA first, Jira second.** Those are the long, messy, LLM-judged steps. L3 is quality-of-life for emails.

---

## 5. Target architecture (QA example)

This is the template for every “Add” slot.

```text
QAAgent.validate_async
        │
        ├─ code: load docx, parse ACs, extract TC-n table rows
        ├─ write workspace: qa/document.txt, qa/acs.json
        │
        ├─ asyncio.gather
        │     ├─ subagent qa_ac_extract   (only if code ACs empty)
        │     └─ subagent qa_tc_extract
        │
        ├─ write qa/test_cases.json (merged)
        ├─ subagent qa_mapper (reads JSON files, not raw doc)
        ├─ apply_coverage_constraints      ← gate
        │
        ├─ if gaps and USE_DEEP_AGENTS:
        │     spawn_task qa_gap_review (only gap ACs)
        │     apply_coverage_constraints again
        │
        └─ QAValidationResult (unchanged API)
```

The orchestrator still calls `QAAgent.validate_async`. Downstream API/UI do not change.

Same idea for Jira: prefetch → files → optional extract → map → `_apply_authoritative_ac_constraints`.

---

## 6. Phased delivery

### Phase 0 — Harness only (no behavior change)

- Add `app/agents/deep/` with todos, workspace, spawn_task
- Unit tests with fake LLMs
- `USE_DEEP_AGENTS=false`
- No agent wired yet

### Phase 1 — QA Deep (accuracy)

- Workspace artifacts for AC/TC/matrix
- Todos visible in workflow events
- Optional single gap-review subagent
- Keep hybrid + `apply_coverage_constraints`
- Tests: omitted AC still FAIL; false PASS still overridden; flag off = current path

### Phase 2 — Jira Deep

- Snapshot/comments/ACs as files
- Evidence mapper as isolated subagent
- Keep authoritative AC constraint
- Tests: invented REQ/AC-07 still dropped

### Phase 3 — L3 Deep writer

- Change summary + mail from workspace
- Risk enum still from `release_risk_scorer`
- Compare mail quality on a few real releases

### Phase 4 — Thin orchestrator + drafts (optional)

- Orchestrator `TODO.md` that only recites the fixed sequence
- Better failure comments / RM drafts
- Still no Deep control of merge/build/approve

Do not start Phase 4 until 1–2 are stable. An orchestrator that can “get creative” is the highest operational risk.

---

## 7. Config and observability

Suggested settings (names only):

| Setting | Default | Purpose |
| --- | --- | --- |
| `USE_DEEP_AGENTS` | `false` | Master switch |
| `DEEP_AGENTS_QA` | `true` when master on | Phase 1 |
| `DEEP_AGENTS_JIRA` | `false` | Phase 2 |
| `DEEP_AGENTS_L3` | `false` | Phase 3 |
| `DEEP_MAX_STEPS` | `20` | Loop cap |
| `DEEP_MAX_SUBAGENTS` | `4` | Fan-out cap |
| `DEEP_GAP_REVIEW` | `true` | One QA remapping pass |

Log/event fields: `todos`, `workspace_files`, `subagent_name`, `ac_source`, token counts. Reuse `WorkflowRunContext.emit` so the frontend timeline can show “QA: mapping AC-03 (in_progress)”.

---

## 8. Testing plan

- Harness: todo rewrite, file round-trip, subagent isolation (child messages not in parent)
- QA: existing `test_qa_agent.py` + `test_qa_coverage_evaluator.py` must pass with flag off
- QA flag on: gap-review cannot mark Fully Covered without a mapped extracted TC
- Jira: `test_apply_authoritative_ac_constraints_drops_extra_ac_rows` still passes
- Workflow: `test_release_workflow.py` stubs unchanged (Deep is inside Jira/QA, not new orchestrator tools)
- No browser change required unless we surface todos in the UI (optional Phase 4)

---

## 9. Risks

| Risk | Mitigation |
| --- | --- |
| Official `deepagents` pulls LangGraph | Do not install it; build four tools ourselves |
| Orchestrator skips QA | Never give it open `spawn_task`; keep `run_orchestrator_tool_sequence` |
| Token / latency explosion | Flag, budgets, QA/Jira only, one gap-review |
| Subagent invents ACs or tests | Evaluators remain mandatory; workspace JSON is input, not truth |
| Workspace leaks ticket data | Scope by release_id; TTL; no secrets |
| Todos treated as workflow state | Todos are logs; `WorkflowStatus` enum is unchanged |

---

## 10. Decision summary

| Question | Answer |
| --- | --- |
| Use LangGraph? | **No** |
| Use `pip install deepagents`? | **No** (LangGraph runtime) |
| Use Deep Agent *pattern*? | **Yes** — todos, files, subagents, later memory |
| Runtime? | Existing `create_agent` + asyncio + Python gates |
| First insertion? | **QA agent** |
| Second? | **Jira agent** |
| Third? | **L3 change summary / mail** |
| Never? | GitHub checks, risk math, merge, build, approvals, Jira transitions |
| Orchestrator? | Recite-only todos later; not a free Deep Agent |

The workflow stays the product. Deep Agents are a better **thinking harness** for the two steps that already need multi-step LLM judgment: Jira alignment and QA coverage.
