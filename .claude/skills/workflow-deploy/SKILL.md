---
name: workflow-deploy
description: "Address review feedback and merge the PR for opensearch2026-agentic-search. Steps 12-13. There is no production deploy to verify (issue #110, local-only demo)."
---

# workflow-deploy — Opensearch2026 Project

Final steps: address review feedback and merge the PR. Runs steps 12–13 of the 14-step workflow.

**No step 14.** As of issue #110 (2026-09-15) this project has no Cloud Run deploy — it runs local-only for the conference demo. As of issue #113 (2026-09-15), GitHub Actions CI is gone too (`.github/workflows/build-deploy.yml` deleted outright) — `make ci` run locally is the only gate. Once a PR merges, there is nothing to watch or verify remotely — see "Post-Merge (Local)" below instead of a deploy-watch step.

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

### 2. Verify You Have a PR Number

You need a PR number to run this skill (pass `--pr <N>`).

If you don't have a PR number yet, run `/workflow-check <PR-number>` to audit first.

After setup, the rest of this skill assumes auth is ready and you have a PR number.

## Quick PR Info Retrieval

If you have a PR number but lost context:

```bash
# Get full PR details
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json number,title,body,draft,state,reviews,checks

# Get linked issue
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json body -q '.body' | grep -i "closes\|fixes\|resolves"

# Get branch name
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName'
```

## Step 12: Address Review Feedback ✓

A reviewer has left comments on your PR. Your job: reply to *every* comment (commit fixes or written explanations) before merging.

### Workflow: Read & Respond

**1. Read all comments:**
```bash
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json comments \
  -q '.comments[] | "[\(.author.login)] \(.body)"'
```

**2. For each comment:**

- **"Fix this" (actionable)** → Commit the fix, push, reply `Fixed in <commit-sha>`
- **"Consider X" (optional feedback)** → Reply with reasoning (e.g., "Deferring to #N" or "Done in <commit>")
- **"This won't work because..." (blocker)** → Fix, push, reply what you changed

**3. Reply to a comment:**
```bash
gh pr comment <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --body "Fixed in abc1234. [Explain the change]"
```

**4. After pushing all fixes:**
```bash
cd langchain_agent && make ci
# No GitHub Actions CI to wait for (issue #113) — this is the only gate
```

**5. Re-request review (if needed):**
```bash
# Get current reviewer(s)
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json reviewRequests -q '.reviewRequests[] | .login'

# Re-request review from one or more reviewers
gh pr edit <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --add-reviewer <reviewer-handle>
# OR multiple: --add-reviewer user1,user2,user3
```

### Commit Guidelines for Feedback

- **Push fixes as new commits, not force-pushes or amends.** Reviewers see what changed without re-reading the whole PR.
- **Commit messages:** imperative mood, clear reason.
  - ✓ "Fix typo in reranker docs"
  - ✓ "Increase timeout from 10s to 30s per review feedback"
  - ✗ "wip" or "fix"

### Example: Multi-Comment Flow

```
[Reviewer leaves 3 comments]
→ gh pr view <PR> --json comments
→ Fix comment 1, commit, push
→ make ci  # local gate, no CI to wait for
→ gh pr comment <PR> --body "Fixed in abc1234"
→ Reply to comment 2: "That's handled by line 88; see quality_gate_node"
→ Reply to comment 3: "Deferring to PR #N as discussed"
→ gh pr review --request-review <reviewer>
[Wait for second review]
```

### Handling Disagreements

If you disagree with feedback:

1. **Understand their concern first** (ask clarifying questions in the thread)
2. **Provide a reasoned reply** citing code, docs, or constraints
   - Example: "The existing pattern uses lazy imports to avoid GCP cost overhead — see #18"
3. **Let the reviewer decide** (they can approve, request changes, or escalate)

## Step 13: Merge ✓

Once local `make ci` is green and the PR has approval, merge to `main` using **squash** strategy.

### Merge Command

```bash
# Confirm make ci is green one final time (no GitHub Actions CI to check — issue #113)
cd langchain_agent && make ci

# Merge with squash (keeps main clean)
gh pr merge <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --squash \
  --delete-branch
```

**Why squash?** Keeps `main`'s history clean; the full PR history lives in GitHub for reference.

### Repo Settings (Verified)

```bash
# Check repo settings (FYI)
gh repo view kmwtechnology/opensearch2026-agentic-search \
  --json squashMergeAllowed,deleteBranchOnMerge
# Returns: {"squashMergeAllowed": true, "deleteBranchOnMerge": false}
```

**Important:** `deleteBranchOnMerge: false` means GitHub will NOT auto-delete the branch. **You must pass `--delete-branch` explicitly** when merging. Also, there is **no branch protection** configured (private repo, requires GitHub Pro) and **no GitHub Actions CI at all** (issue #113) — `make ci` run locally before merging is the only gate.

### If `gh pr merge` Prompts Interactively

```bash
# Falls back to interactive selection
gh pr merge <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search
# Select: "Squash and merge"
```

### Post-Merge Cleanup (Local)

```bash
# Switch to main
git checkout main

# Sync with remote
git pull origin main

# Delete local branch (the remote was deleted by --delete-branch)
git branch -D <feature-branch>

# Verify
git branch -v
# Should show: "* main <hash>"
```

## Post-Merge (Local) ✓

The PR is merged. There is no deploy to watch and no GitHub Actions CI to
check on `main` (issue #113 removed it entirely) — verify locally instead.

### 1. Verify Locally

```bash
cd langchain_agent
make dev            # Docker + backend + frontend
```

Try the feature in the live local web UI (`http://localhost:5173`) and confirm it works end-to-end — this is now the only "production" this project has.

### 2. Close the Issue

Link the PR to the issue (you should have used `Closes #N` in the PR body):

```bash
# Check if auto-close worked
gh issue view <N> \
  --repo kmwtechnology/opensearch2026-agentic-search
# Should show: "Pull request #<PR> merged this issue"
```

**If auto-close didn't work, close manually:**

```bash
gh issue close <N> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --comment "Fixed in PR #<PR-number>."
```

### 3. Update Memory (If Findings Emerged)

If the work surfaced non-obvious findings, create a memory file:

```bash
cat > ~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/finding_$(date +%Y-%m-%d)_<slug>.md <<'EOF'
---
name: <kebab-case-slug>
description: <one-line hook>
metadata:
  type: feedback | project | reference
---

[Your finding]

**Why:** [Why this matters]

**How to apply:** [When to use this]
EOF
```

Then add a line to the memory index:

```bash
echo "- [Finding Title](finding_$(date +%Y-%m-%d)_<slug>.md) — one-line hook" >> \
  ~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md
```

## Post-Merge Checklist

Before calling this step "done":

- [ ] CI on `main` is green, or the 0-steps runner/billing issue is confirmed (see memory) and local `make ci` was green pre-merge
- [ ] Feature verified locally (`make dev`, tried in the browser)
- [ ] Issue is closed (auto-closed or manually)
- [ ] Memory updated if findings emerged
- [ ] No follow-up issues filed (if edge cases discovered, file them as new tickets)

## Common Issues & Recovery

| Issue | Recovery |
|-------|----------|
| Local app is broken after merge | **Revert:** `git revert <commit-sha>`, push to `main`. Then debug locally and file a new issue. |
| Issue didn't auto-close | Manually close: `gh issue close <N> --comment "Fixed in PR #<PR>."` |

## Breadcrumbs & Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Merge command** | `gh pr merge <PR> --squash --delete-branch` |
| **Get PR comments** | `gh pr view <PR> --json comments` |
| **Post PR comment** | `gh pr comment <PR> --body "..."` |
| **Add reviewer** | `gh pr edit <PR> --add-reviewer <handle>` |
| **CI gate** | `make ci` locally — no GitHub Actions CI exists (issue #113) |
| **Close issue** | `gh issue close <N> --comment "..."` |
| **Memory location** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Project config** | `CLAUDE.md` (source of truth) |

## Notes & Common Gotchas

- **No automatic branch deletion** — you must pass `--delete-branch` to `gh pr merge`. GitHub doesn't auto-delete even after merge.
- **No branch protection, no CI at all** — nothing automatically gates the merge. `make ci` run locally before merging is the only check.
- **No deploy at all, local-only (issue #110, tooling removed #113)** — there is no `deploy.sh`/`gcp-init.sh` anymore; nothing to run.
- **No Slack** — skip any "post to Slack" steps.
- **GitHub Issues, not Jira** — use `gh issue` for all issue operations.

## See Also

- **Previous step:** `/workflow-check <PR-number>` to audit the PR
- **GCP deploy removal:** issue #110 (deploy path) and issue #113 (GitHub Actions CI + remaining GCP tooling) for what changed and why
- **Project `CLAUDE.md`** — source of truth for tech stack, patterns, commands
- **Home memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **View all PRs:** `gh pr list --repo kmwtechnology/opensearch2026-agentic-search --state all`
- **View all issues:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state all`
