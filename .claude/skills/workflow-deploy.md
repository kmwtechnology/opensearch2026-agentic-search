# workflow-deploy — Opensearch2026 Project

Final steps: address review feedback, merge the PR, and verify in production. Runs steps 12–14 of the 14-step workflow.

## Step 12: Address Review Feedback ✓

A reviewer has left comments on your PR. Your job: reply to *every* comment (commit fixes or written explanations) before merging.

### Workflow

**1. Read all comments:**
```bash
gh pr view <PR-number> --json comments | jq '.comments[] | {author: .author.login, body: .body}'
```

**2. For each comment:**

- **"Fix this" (actionable)** → Commit the fix, push, reply `Fixed in <commit-sha>`
- **"Consider X" (optional feedback)** → Reply with your reasoning (e.g., "We're deferring that to #N" or "Done in <commit>")
- **"This won't work because..." (blocker)** → Fix, push, reply with what you changed

**3. After pushing fixes:**
```bash
gh pr checks <PR-number>                 # Wait for CI to re-run
```

Wait for CI to go green, then proceed.

**4. Re-request review:**
```bash
gh pr review --request-review <reviewer-handle>
```

Or if multiple reviewers:
```bash
gh pr view <PR-number> --json reviewRequests
gh pr review --request-review <handle1> <handle2>
```

### Commit Guidelines

- **Push fixes as new commits, not force-pushes or amends.** This lets reviewers see what changed without re-reading the whole PR.
- **Commit messages:** imperative mood, clear reason (e.g., `"Fix typo in reranker docs"` or `"Increase timeout from 10s to 30s per review feedback"`).

### Example Flow

```
[Reviewer leaves 3 comments]
→ gh pr view <PR> --json comments
→ Fix comment 1, commit, push
→ gh pr checks <PR>  # wait for CI
→ Reply to comment 1: "Fixed in abc1234"
→ Reply to comment 2: "That's addressed by the existing quality_gate logic; see line 88"
→ Reply to comment 3: "Deferring to PR #N as discussed"
→ gh pr review --request-review <reviewer>
[Wait for second review pass]
```

### Disagreements

If you disagree with feedback:

1. **Understand their concern first** (ask clarifying questions in the comment thread).
2. **Provide a reasoned reply** citing code, docs, or constraints (e.g., "The existing pattern uses lazy imports to avoid GCP cost overhead — see #18").
3. **Let the reviewer decide** (they can approve despite disagreement, request changes, or escalate).

## Step 13: Merge ✓

Once the PR has a green CI and approval, merge to `main` using **squash** strategy:

```bash
gh pr merge <PR-number> --squash --delete-branch
```

**Why squash?** Keeps `main`'s history clean; the PR description lives in GitHub for future reference.

**Verified repo settings (`gh repo view --json deleteBranchOnMerge,squashMergeAllowed`):** `squashMergeAllowed: true`, but **`deleteBranchOnMerge: false` at the repo level** — the repo will NOT auto-delete branches on merge unless you pass `--delete-branch` explicitly. This repo also has no branch protection configured (private repo, requires GitHub Pro), so there's no required-status-check gate enforcing green CI before merge — **you must confirm CI is green yourself** before merging; `gh pr merge` will let you merge on red CI unless you check first.

```bash
gh pr checks <PR-number>        # confirm green BEFORE merging — nothing else enforces this
gh pr merge <PR-number> --squash --delete-branch
```

**Note on `--auto`:** GitHub's auto-merge feature requires "Allow auto-merge" to be enabled on the repo, which hasn't been verified here — don't rely on `--auto` to gate the merge on CI. Merge manually once `gh pr checks` shows green.

### Interactive fallback

```bash
gh pr merge <PR-number>
```

### Post-merge cleanup (local)

```bash
git checkout main
git pull origin main
git branch -D <feature-branch>
```

## Step 14: Post-Deploy ✓

The PR is merged. Now verify it shipped and close the issue.

### 1. Watch CI/Deployment

There is **no separate manual deploy script** — `deploy.sh`/`gcp-init.sh` do not exist in this repo despite older docs mentioning them. Deployment is fully automated: pushing to `main` triggers `build-deploy.yml`, which runs `unit-tests`, `integration-tests`, `lint-backend`, `frontend-tests`, `shellcheck`, and `build-docker` in parallel, then `deploy-cloud-run` runs `gcloud run deploy` — but **only after all of those jobs succeed** (`needs: [build-docker, unit-tests, integration-tests, lint-backend, frontend-tests, shellcheck]`). One flaky test blocks the deploy.

```bash
gh run list --workflow build-deploy.yml --branch main --limit 1
gh run watch <run-id>          # or: gh run view <run-id> --log
```

**Real project constants** (from `build-deploy.yml` / `smoke-tests.yml`):
- `PROJECT_ID`: `gen-lang-client-0250737934`
- `REGION`: `us-central1`
- `SERVICE_NAME`: `agentic-hybrid-search`

**Check status:**
```bash
gh run list --workflow build-deploy.yml --branch main --limit 5
# All jobs green, including deploy-cloud-run specifically?
```

### 2. Verify in Production (GCP Cloud Run)

Once `deploy-cloud-run` is green, the image is live. Cloud Run URLs are hash-suffixed, not derivable from the project ID — fetch the real URL first:

```bash
gcloud run services describe agentic-hybrid-search \
  --region us-central1 --project gen-lang-client-0250737934 \
  --format 'value(status.url)'
```

**Quick manual checks** (substitute `$SERVICE_URL` from above):
```bash
curl -s $SERVICE_URL/health | jq .
curl -s -H "X-Admin-Token: $ADMIN_TOKEN" $SERVICE_URL/api/config | jq .
```

**Automated smoke suite (preferred):** the repo has a dedicated `smoke-tests.yml` workflow built exactly for this — a manual `workflow_dispatch` against a live service URL:

```bash
gh workflow run smoke-tests.yml -f service_url="$SERVICE_URL" -f timeout_minutes=15
gh run watch $(gh run list --workflow smoke-tests.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

Note: per `maintenance_audit_2026_09_01.md` in memory, the *old* post-deploy smoke gate had a bug where `tee`'s PID masked real failures — confirm you're looking at the actual job conclusion (`gh run view <id>`), not just "workflow completed."

**User-facing check:** Try a search in the live web UI and verify your fix works.

### 3. Close the Issue

Link the PR to the issue (you should have used `Closes #N` in the PR body):

```bash
gh issue view <N>
# Should show "Pull request #<PR> merged this issue"
```

If auto-close didn't work, close manually:

```bash
gh issue close <N> --comment "Fixed in PR #<PR-number>. Deployed to Cloud Run."
```

### 4. Update Memory

If the fix surfaced new findings (a pattern, a gotcha, a tool that works well), update memory:

```bash
# Example: if you discovered a testing pattern
cat > ~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/finding_<date>_<slug>.md <<'EOF'
---
name: <kebab-case-slug>
description: <one-line hook>
metadata:
  type: feedback
---

[Your finding]

**Why:** [The reason this matters]

**How to apply:** [When to use this]
EOF
```

Then update `memory/MEMORY.md` with a pointer.

### Common Issues & Recovery

| Issue | Recovery |
|-------|----------|
| Build failed in CI after merge | Diagnose via `gh run view <run-id> --log`; commit a fix, push to `main`; CI re-runs automatically. |
| `build-docker` succeeded but `deploy-cloud-run` didn't run/failed | Check whether `unit-tests`/`integration-tests`/`lint-backend`/`frontend-tests`/`shellcheck` all passed — `deploy-cloud-run` is gated on ALL of them, not just the build. If it ran but failed, check WIF auth — see `memory/reference_gcp_wif_iam_per_repo_binding.md`. |
| Production app is broken | Revert the commit (`git revert <commit-sha>`), push, CI redeploys. Then debug locally and re-open a new PR. |
| Issue didn't auto-close | Manually close with `gh issue close <N>` + a descriptive comment. |
| Deployment took >10 min | Likely Lucille Docker image rebuild (one-time cost if Lucille base image changed). Check `build-deploy.yml` logs. |

## Deployment Checklist

Before considering this step "done":

- [ ] CI on `main` is green
- [ ] Cloud Run shows the new image (`gcloud run services describe`)
- [ ] Live API responds to health checks
- [ ] Feature is working in production (user-facing or via API test)
- [ ] Issue is closed (auto or manual)
- [ ] Memory is updated if findings emerged
- [ ] No follow-up issues filed (if edge cases discovered, file them now as separate tickets)

## Notes

- **No Slack notifications** — this project doesn't post deploy updates to Slack. Rely on GitHub's issue tracking.
- **GitHub Issues, not Jira** — issue closure and status all happen in `gh issue`.
- **Squash-merge default** — keeping `main` clean and searchable by feature, not by micro-commits.
- **Revert is safe** — if production breaks, `git revert` is your friend. It's not a failure; it's a recovery.

## See Also

- Global `/workflow-deploy` (this skill builds on it)
- `memory/reference_gcp_wif_iam_per_repo_binding.md` — GCP auth setup
- `memory/reference_cicd_github_actions.md` — CI/CD workflow details
- Project `CLAUDE.md` for the full 14-step workflow
