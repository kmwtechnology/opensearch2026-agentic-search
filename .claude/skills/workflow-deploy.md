# workflow-deploy — Opensearch2026 Project

Final steps: address review feedback, merge the PR, and verify in production. Runs steps 12–14 of the 14-step workflow.

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
gh pr checks <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search
# Wait for CI to go green
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
→ gh pr checks <PR>  # wait for CI
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

Once the PR has a green CI and approval, merge to `main` using **squash** strategy.

### Merge Command

```bash
# Confirm CI is green one final time
gh pr checks <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search

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

**Important:** `deleteBranchOnMerge: false` means GitHub will NOT auto-delete the branch. **You must pass `--delete-branch` explicitly** when merging. Also, there is **no branch protection** configured (private repo, requires GitHub Pro), so **there's no automatic gate enforcing green CI before merge** — you must verify CI is green yourself with `gh pr checks` before running `gh pr merge`.

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

## Step 14: Post-Deploy ✓

The PR is merged. Now watch deployment and verify it shipped.

### 1. Monitor CI/Deployment on `main`

There is **no manual deploy script** (deploy.sh/gcp-init.sh do not exist). Deployment is fully automated:

**Flow:** Push to `main` → `build-deploy.yml` runs → (if all jobs pass) → `deploy-cloud-run` runs

**Jobs (run in parallel):**
- `unit-tests`
- `integration-tests`
- `lint-backend`
- `frontend-tests`
- `shellcheck`

**Then (if all above pass):**
- `build-docker` (builds & pushes image to GCP Artifact Registry)
- `deploy-cloud-run` (deploys image to Cloud Run)

**Then (if deploy succeeds):**
- `notify` (posts summary to GitHub Actions summary)

```bash
# Check the latest main run
gh run list --workflow build-deploy.yml \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --branch main \
  --limit 1

# Watch the run in real-time
gh run watch <run-id> \
  --repo kmwtechnology/opensearch2026-agentic-search

# OR: view logs after completion
gh run view <run-id> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --log
```

**Real project constants** (hardcoded in `build-deploy.yml`):
- `PROJECT_ID`: `gen-lang-client-0250737934`
- `REGION`: `us-central1`
- `SERVICE_NAME`: `agentic-hybrid-search`

### 2. Verify Deployment to Cloud Run

Once `deploy-cloud-run` succeeds, the image is live.

**Get the live service URL** (Cloud Run URLs are hash-suffixed, not derivable):

```bash
SERVICE_URL=$(gcloud run services describe agentic-hybrid-search \
  --region us-central1 \
  --project gen-lang-client-0250737934 \
  --format 'value(status.url)')

echo "Live service: $SERVICE_URL"
```

**Quick manual health checks:**

```bash
# Health endpoint
curl -s "$SERVICE_URL/health" | jq .

# Config endpoint (requires admin token)
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" \
  "$SERVICE_URL/api/config" | jq .
```

**Better: Run the automated smoke suite** (more comprehensive):

```bash
# Trigger the smoke-tests.yml workflow (manual dispatch)
gh workflow run smoke-tests.yml \
  --repo kmwtechnology/opensearch2026-agentic-search \
  -f service_url="$SERVICE_URL" \
  -f timeout_minutes=15

# Get the run ID
SMOKE_RUN=$(gh run list --workflow smoke-tests.yml \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --limit 1 \
  --json databaseId -q '.[0].databaseId')

# Watch it
gh run watch $SMOKE_RUN \
  --repo kmwtechnology/opensearch2026-agentic-search
```

**User-facing test:** Try a search in the live web UI (`$SERVICE_URL`) and verify your fix works end-to-end.

### 3. Close the Issue

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
  --comment "Fixed in PR #<PR-number>. Deployed to Cloud Run at $SERVICE_URL"
```

### 4. Update Memory (If Findings Emerged)

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

## Deployment Checklist

Before calling this step "done":

- [ ] CI on `main` is fully green (all jobs, including `deploy-cloud-run`)
- [ ] Cloud Run service updated (verify with `gcloud run services describe`)
- [ ] Live API responds to health checks (`curl ... /health`)
- [ ] Feature works in production (tested in live web UI or via API)
- [ ] Issue is closed (auto-closed or manually)
- [ ] Memory updated if findings emerged
- [ ] No follow-up issues filed (if edge cases discovered, file them as new tickets)

## Common Issues & Recovery

| Issue | Recovery |
|-------|----------|
| Build failed in CI after merge | Diagnose: `gh run view <run-id> --log`. Commit fix, push to `main`. CI re-runs automatically. |
| `build-docker` succeeded but `deploy-cloud-run` didn't run/failed | Check if all *prerequisite* jobs passed (`unit-tests`, `integration-tests`, `lint-backend`, `frontend-tests`, `shellcheck`). `deploy-cloud-run` is gated on ALL. If it ran but failed, check WIF auth (see memory ref below). |
| Production app is broken | **Revert immediately:** `git revert <commit-sha>`, push to `main`. CI redeploys old version. Then debug locally and file a new issue. |
| Issue didn't auto-close | Manually close: `gh issue close <N> --comment "Fixed in PR #<PR>. Deployed."` |
| Deployment took >10 min | Likely Lucille Docker image rebuild (one-time cost). Check `build-deploy.yml` logs. |
| Smoke tests timeout | Increase `timeout_minutes` when dispatching, or run manual health checks instead. |

## Breadcrumbs & Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Merge command** | `gh pr merge <PR> --squash --delete-branch` |
| **Get PR comments** | `gh pr view <PR> --json comments` |
| **Post PR comment** | `gh pr comment <PR> --body "..."` |
| **Add reviewer** | `gh pr edit <PR> --add-reviewer <handle>` |
| **Get live service URL** | `gcloud run services describe agentic-hybrid-search --region us-central1 --project gen-lang-client-0250737934 --format 'value(status.url)'` |
| **Run smoke tests** | `gh workflow run smoke-tests.yml -f service_url="..."` |
| **Check deployment status** | `gh run list --workflow build-deploy.yml --branch main --limit 1` |
| **Close issue** | `gh issue close <N> --comment "..."` |
| **Memory location** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Project config** | `CLAUDE.md` (source of truth) |

## Notes & Common Gotchas

- **No automatic branch deletion** — you must pass `--delete-branch` to `gh pr merge`. GitHub doesn't auto-delete even after merge.
- **No branch protection** — CI doesn't automatically gate the merge. You must check `gh pr checks` yourself before merging.
- **No manual deploy script** — `deploy.sh` and `gcp-init.sh` don't exist. Deployment is GitHub Actions only.
- **Deployment is all-or-nothing** — `deploy-cloud-run` waits for ALL prerequisite jobs to pass. One flaky test blocks the deploy.
- **No Slack** — skip any "post to Slack" steps.
- **GitHub Issues, not Jira** — use `gh issue` for all issue operations.
- **WIF auth required** — Cloud Run deploy uses Workload Identity Federation. If it fails, check the memory ref on GCP IAM setup.

## See Also

- **Previous step:** `/workflow-check <PR-number>` to audit the PR
- **Deployment details:** Memory reference on GCP WIF IAM binding
- **CI/CD workflows:** Memory reference on GitHub Actions
- **Project `CLAUDE.md`** — source of truth for tech stack, patterns, commands
- **Home memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **View all PRs:** `gh pr list --repo kmwtechnology/opensearch2026-agentic-search --state all`
- **View all issues:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state all`
