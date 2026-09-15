---
name: workflow-start
description: "Start a work session on a GitHub issue in opensearch2026-agentic-search: retrieve the issue, plan the approach, and start coding directly on main. Cowboy mode — no feature branch or draft PR by default."
---

# workflow-start — Opensearch2026 Project (Cowboy Mode)

Start a new work session: retrieve issue, plan the approach, start coding on `main`. No branch, no PR — this repo has no branch protection on `main` (confirmed via `gh api .../branches/main` → `"protected": false`; classic protection and rulesets both return 403, GitHub Pro required, this repo doesn't have it).

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

**If auth fails:**
```bash
! gh auth login -h github.com -p https -w
```

### 2. Verify Local State

```bash
# Check git is on main and clean
git branch           # should show: * main
git status           # should show: "working tree clean"

# Sync main with remote
git pull origin main
```

If uncommitted changes exist, stash first: `git stash`

---

## Main Steps

### 1. Retrieve Issue Context

Fetch the GitHub issue (pass `--issue <N>` to this skill):

```bash
gh issue view <N> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json number,title,body,state,assignees,labels
```

**Check:**
- Is the issue OPEN? (If closed, confirm with user before proceeding)
- Who's assigned? (If someone else, clarify ownership)
- What labels? (Priority, type, area tags)

**Save:** Issue #, title, state for the rest of the workflow.

### 2. Plan the Approach

Restate scope (2–3 sentences) to the user:
- **What** we're fixing/adding
- **Why** (user impact, blocker, or motivation)
- **Non-goals** (what we're explicitly NOT doing)

For anything non-trivial, enter planning mode to propose an implementation strategy:

```
/plan
Issue #<N>: <title>
Scope: <2-3 sentence restatement>
[Issue body and any relevant context]
```

The plan should propose:
- **Approach:** high-level strategy
- **Critical files:** what needs to change
- **Architecture tradeoffs:** alternatives considered
- **Risk mitigations:** edge cases, testing strategy
- **Tasks:** step-by-step breakdown

Wait for user approval of the plan before proceeding to coding. Skip the formal `/plan` step for small, obvious fixes.

### 3. Start Coding — Directly on `main`

No branch, no draft PR. You're already on `main` (verified clean + up to date in Setup step 2) — start editing there.

```
Issue #<N>: <title>
Plan: approved
Tasks: from plan breakdown
```

Commit as you go (small, logical commits are still good practice even without a PR to review them). When you believe the work is ready to push, proceed to `/workflow-check` for the pre-push checklist.

**Want a PR anyway?** Nothing stops you from branching manually for something you explicitly want reviewed before it lands (`git checkout -b <name>`, `gh pr create`) — this skill just won't do it automatically. That's the opt-in exception, not the default path.

---

## Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Default flow** | Commit directly to `main` — no branch, no PR |
| **Issue tracking** | GitHub Issues; use `#<N>` (not Jira tickets) |
| **Test before push** | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` |
| **Local hooks** | `pre-commit` (installed by `setup.sh`) runs black/isort/flake8 on staged `.py` files; no pre-push hook exists — tests/smoke gates must still be run by hand |
| **Next step** | Code, test → run `/workflow-check` when ready to push |

## Notes

- **No branch protection on `main`** — this repo is private without GitHub Pro, so classic branch protection and rulesets are both unavailable (403 on the API); `main` reports `"protected": false`. Nothing on GitHub's side gates a direct push.
- **No Slack** — this project has no Slack integration.
- **CLAUDE.md is source of truth** — refer to it for tech stack, patterns, commands.
- **Auth is enforced** — always `agileresearchservices` for this project.

## See Also

- **Next step:** Proceed to coding. Once tests pass locally, run `/workflow-check` to run the pre-push checklist.
- **After push:** Run `/workflow-deploy` to verify and close the issue.
- **Project config:** `CLAUDE.md` (source of truth for this project)
- **Memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
