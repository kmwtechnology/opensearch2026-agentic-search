# workflow-start — Opensearch2026 Project

Start a new work session: review context, plan the approach, create a feature branch, tie it to an issue, and break work into tasks.

## Setup & Auth (Run Once)

**This skill is self-contained.** You can run it independently at any time.

### 1. Ensure gh Account is agileresearchservices

```bash
# Check which account is currently active
ACTIVE_ACCOUNT=$(gh auth status 2>&1 | sed -n 's/.*Logged in to github.com account \([^ (]*\).*/\1/p' | head -1)

if [ "$ACTIVE_ACCOUNT" != "agileresearchservices" ]; then
  echo "Current account: $ACTIVE_ACCOUNT. Switching to agileresearchservices..."
  gh auth switch -u agileresearchservices
  echo "✓ Switched to agileresearchservices"
else
  echo "✓ Already using agileresearchservices"
fi

# Verify auth succeeded
gh auth status
```

**If auth fails:** You need to authenticate manually.
```bash
# Run this and follow the web login:
! gh auth login -h github.com -p https -w
```

### 2. Verify Local Context

```bash
# Check git is on main and clean
git branch           # should show: * main
git status           # should show: "working tree clean"

# If not clean, stash first
git stash
```

After setup, the rest of this skill assumes auth is ready and local state is clean.

## Steps

### 1. Retrieve Issue Context

You need a GitHub issue number (pass `--issue <N>` to this skill if running standalone, or reference the current issue).

```bash
# Get full issue details
gh issue view <N> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json number,title,body,state,assignees,labels
```

**Check:**
- Is the issue OPEN? (If closed, ask the user if they want to continue anyway.)
- Who's assigned? (If someone else, clarify ownership before proceeding.)
- What labels? (Look for priority, type, area tags.)

**Save these details** for the rest of the workflow:
- Issue number (`#<N>`)
- Issue title (exact wording)
- Issue state (OPEN or CLOSED)

### 2. Review Project Context

**Read these breadcrumbs:**
- `CLAUDE.md` (lines 1–50) — this project's guidance, structure, and key patterns
- `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` — recent fixes, decisions, known gotchas

**Ask:** Is there prior context that changes how we approach this issue? (e.g., a blocked PR, a recent regression, a known tradeoff, related issues)

### 3. Restate Scope

Propose a concise scope statement (2–3 sentences) to the user:
- **What** we're fixing/adding
- **Why** (user impact, blocker, or motivation)
- **Non-goals** (what we're explicitly NOT doing)

Wait for user confirmation before proceeding.

### 4. Ensure Clean Local State

```bash
# Check git status
git status
# Output should show: "On branch main" and "working tree clean"

# Sync main with remote (not just local refs)
git checkout main
git pull origin main
```

If uncommitted changes exist, ask the user to stash or commit first.

### 5. Propose & Create Feature Branch

Suggest a branch name following this project's pattern:
- **Feature:** `feat/issue-<N>-<slug>` (e.g., `feat/issue-42-reranker-latency`)
- **Fix:** `fix/issue-<N>-<slug>` (e.g., `fix/issue-38-websocket-auth`)
- **Docs:** `docs/issue-<N>-<slug>` (e.g., `docs/issue-12-add-contributing`)

Confirm the branch name with the user, then create and push:

```bash
# Create local branch
git checkout -b <branch-name>

# Push to remote with tracking
git push --set-upstream origin <branch-name>

# Verify
git branch -vv
# Should show: "* <branch-name> <hash> [origin/<branch-name>]"
```

### 6. Break Work Into Tasks (Optional)

For multi-step work, optionally list discrete, completable tasks. Examples:
- "Read current Reranker implementation (langchain_agent/reranker.py:88-120)"
- "Add latency capture to reranker_node (main.py:~line 2100)"
- "Update integration tests (tests/integration/test_quality_gate.py)"
- "Run make smoke-local-quick and verify passing"
- "Open PR with Closes #<N> in body"

For one-off fixes, skip this if it's straightforward.

### 7. Confirm & Proceed to Coding

Summarize what you're about to do:

```
Issue #<N>: <title>
Branch: <branch-name>
Scope: <2-3 sentence restatement>
Tasks: <list or "straightforward, proceeding directly to code">
```

Wait for a green light from the user, then proceed to coding.

### 8. (Optional) Create Draft PR Immediately

To establish the issue↔branch↔PR link now (rather than waiting until after coding), create a draft PR:

```bash
gh pr create \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --draft \
  --title "[WIP] Issue #<N>: <title>" \
  --body "Closes #<N>

## Summary
(To be filled in as work progresses)"
```

This links the issue to the PR from the start, making context retrieval easier later. If you skip this, create the PR after coding with `/workflow-check`.

## Breadcrumbs & Self-Contained Context

**All you need to know to run this skill independently:**

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (use `gh auth status` to verify) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` (or `--repo` flag in all `gh` commands) |
| **Default branch** | `main` |
| **Branch naming** | `feat/issue-<N>-<slug>`, `fix/issue-<N>-<slug>`, `docs/issue-<N>-<slug>` |
| **Issue tracking** | GitHub Issues (not Jira); see all issues: `gh issue list --repo kmwtechnology/opensearch2026-agentic-search` |
| **Project config** | `CLAUDE.md` (source of truth for guidance, tech stack, patterns) |
| **Session memory** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Test commands** | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` (run before pushing) |

## Notes & Common Gotchas

- **No local pre-commit hook** — `.git/hooks/pre-push` is Git LFS's own hook only. You must run `make ci` and `make smoke-local-quick` by hand before pushing. Nothing local prevents you from pushing broken code.
- **No Slack integration** — skip any "post to #channel" steps; this project has no Slack notifications.
- **GitHub Issues, not Jira** — use `gh issue` CLI for all lookups. No ticket prefixes (`TICKET-NNN`); just `#<N>`.
- **CLAUDE.md is source of truth** — if design or architecture changes during this work, update `CLAUDE.md` before merging the PR (that's step 7 of the 14-step workflow).

## See Also

- **Next step:** Proceed to coding. Once you believe the work is complete, run `/workflow-check <PR-number>` to audit before marking ready for review.
- **Project `CLAUDE.md`** — lines 1–50 for project orientation, lines 99–148 for commands
- **Home memory index:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **GitHub issues list:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state open`
