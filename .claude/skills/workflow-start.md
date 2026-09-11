# workflow-start — Opensearch2026 Project

Start a new work session: retrieve issue, plan the approach, create feature branch, and open a draft PR.

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

## Main Steps (3 Steps)

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

Then enter planning mode to propose an implementation strategy:

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

Wait for user approval of the plan before proceeding to branch creation.

### 3. Create Feature Branch

Suggest a branch name following this project's pattern:
- **Feature:** `feat/issue-<N>-<slug>` (e.g., `feat/issue-42-reranker-latency`)
- **Fix:** `fix/issue-<N>-<slug>` (e.g., `fix/issue-38-websocket-auth`)
- **Docs:** `docs/issue-<N>-<slug>` (e.g., `docs/issue-12-add-contributing`)

Confirm the branch name with the user, then create and push:

```bash
# Create and push branch
git checkout -b <branch-name>
git push --set-upstream origin <branch-name>

# Verify tracking
git branch -vv
# Should show: "* <branch-name> <hash> [origin/<branch-name>]"
```

### 4. Create Draft PR

Always open a draft PR to establish the issue↔branch↔PR link:

```bash
gh pr create \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --draft \
  --title "Issue #<N>: <title>" \
  --body "Closes #<N>

## Summary
(To be filled in as work progresses)

## Test Plan
- [ ] Running tests locally before pushing
"
```

**Note:** The PR is created in draft state. `/workflow-check` will audit and mark it ready for review once work is complete.

Get the PR number from the output; you'll need it for `/workflow-check`.

### 5. Proceed to Coding

You're ready to start coding. You have:

```
Issue #<N>: <title>
Branch: <branch-name>
PR: #<PR-number> (draft)
Plan: approved
Tasks: from plan breakdown
```

The branch is created, PR is drafted, and the plan is approved. Proceed to implementing the tasks from the plan.

---

## Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Branch naming** | `feat/issue-<N>-slug`, `fix/issue-<N>-slug`, `docs/issue-<N>-slug` |
| **Issue tracking** | GitHub Issues; use `#<N>` (not Jira tickets) |
| **Test before push** | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` |
| **No local hook** | Pre-commit/pre-push hooks don't enforce code quality; you must run tests by hand |
| **Next step** | Code, test, push → run `/workflow-check <PR-number>` when ready |

## Notes

- **This creates the issue↔branch↔PR link immediately.** The PR is drafted; `/workflow-check` will mark it ready once audited.
- **No Slack** — this project has no Slack integration.
- **CLAUDE.md is source of truth** — refer to it for tech stack, patterns, commands.
- **Auth is enforced** — always `agileresearchservices` for this project.

## See Also

- **Next step:** Proceed to coding. Once tests pass locally, run `/workflow-check <PR-number>` to audit and mark ready.
- **After merge:** Run `/workflow-deploy <PR-number>` to verify deployment.
- **Project config:** `CLAUDE.md` (source of truth for this project)
- **Memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
