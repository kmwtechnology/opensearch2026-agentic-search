# workflow-start — Opensearch2026 Project

Start a new work session: review context, plan the approach, break work into tasks.

## Steps

### 1. Issue Context

Retrieve the GitHub issue (pass `--issue <N>` or `--issue-url <URL>`):

```bash
gh issue view <N> --json title,body,state,assignees
```

Save the issue number, state, and summary. If it's already closed, ask the user if they want to continue anyway.

### 2. Review Project Memory & Recent Status

Load and skim:
- `memory/MEMORY.md` (index) — for context on recent work
- `memory/project_status_recent_fixes.md` — what's currently shipping
- `memory/reference_repository_layout.md` — directory structure (for orientation)

Ask: **Is there prior context that changes how we approach this?** (e.g., a blocked PR, a recent regression, a known tradeoff).

### 3. Restate Scope

Propose a concise scope statement (2–3 sentences):
- **What** we're fixing/adding
- **Why** (user impact or blocker)
- **Non-goals** (what we're explicitly NOT doing)

Wait for user confirmation before proceeding.

### 4. Local Environment

Check:
```bash
git status                    # must be clean
git branch -v | head -5       # confirm main is up to date locally
```

If uncommitted changes exist, ask the user to stash or commit first.

### 5. Propose Feature Branch

Suggest a branch name following the project's pattern:
- **Feature:** `feat/issue-<N>-<slug>` (e.g., `feat/issue-42-reranker-latency`)
- **Fix:** `fix/issue-<N>-<slug>` (e.g., `fix/issue-38-websocket-auth`)
- **Docs:** `docs/issue-<N>-<slug>`

Ask for confirmation, then create it:
```bash
git checkout -b <branch-name>
git push -u origin <branch-name>
```

### 6. Break Into Tasks

For multi-step work, use TaskCreate to list discrete, completable steps. Examples:
- "Read current Reranker implementation (langchain_agent/modules/reranker.py)"
- "Add latency capture to reranker_node"
- "Update integration tests"
- "Run smoke-local-quick locally"
- "Open PR with Closes #N in body"

For one-off fixes, skip this if it's obvious.

### 7. Confirm Before Coding

Summarize:
- Issue #N: *title*
- Branch: `<branch-name>`
- Scope: *restatement*
- Tasks: *list* (or "straightforward, skipping task list")

Wait for a green light from the user, then move to coding.

## Notes

- **GitHub Issues, not Jira** — this project tracks work in GitHub Issues. Use `gh issue` CLI for all lookups.
- **No Slack** — skip any default "post to #channel" step; this project has no Slack integration.
- **Local test suite** — later steps will run `PYTHONPATH=. pytest`, `make ci`, `make smoke-local-quick`, etc. Orient yourself on what's in `tests/unit/`, `tests/integration/`, `tests/e2e/` now.
- **CLAUDE.md lock-in** — if design changes mid-PR, update the project's CLAUDE.md memory file before merging (step 7 of the global 14-step workflow).

## See Also

- Project `CLAUDE.md` for full 14-step workflow
- `memory/reference_testing_troubleshooting.md` for test troubleshooting
- `langchain_agent/ARCHITECTURE.md` for pipeline details
