---
name: workflow-deploy
description: "Verify a push to main and close out the issue for opensearch2026-agentic-search. Cowboy mode — no PR to merge, no production deploy to verify (issue #110, local-only demo)."
---

# workflow-deploy — Opensearch2026 Project (Cowboy Mode)

Final steps after pushing straight to `main`: verify locally and close out the issue. There's no PR to merge — `main` has no branch protection, so `/workflow-check` already served as the review gate before the push.

**No production deploy to verify either.** As of issue #110 (2026-09-15) this project has no Cloud Run deploy — it runs local-only for the conference demo. As of issue #113 (2026-09-15), GitHub Actions CI is gone too (`.github/workflows/build-deploy.yml` deleted outright) — `make ci` run locally (in `/workflow-check`) was the only gate. Once pushed, there is nothing to watch or verify remotely — everything below is local.

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

### 2. Confirm the Push Landed

```bash
git fetch origin main
git log origin/main -1 --oneline
```

## Step 1: Verify Locally

```bash
cd langchain_agent
make dev            # Docker + backend + frontend
```

Try the feature in the live local web UI (`http://localhost:5173`) and confirm it works end-to-end — this is now the only "production" this project has.

## Step 2: Close the Issue

If your commit message included `Closes #N`, GitHub auto-closes it once that commit lands on `main` (closing keywords work on direct pushes to the default branch, not just PR merges):

```bash
gh issue view <N> \
  --repo kmwtechnology/opensearch2026-agentic-search
# Should show: state CLOSED
```

**If auto-close didn't work (e.g. you forgot the keyword), close manually:**

```bash
gh issue close <N> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --comment "Fixed in <commit-sha>."
```

## Step 3: Update Memory (If Findings Emerged)

If the work surfaced non-obvious findings not already captured in `/workflow-check` Step 6:

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

## Post-Push Checklist

Before calling this step "done":

- [ ] `make ci` was green pre-push (done in `/workflow-check`)
- [ ] Feature verified locally (`make dev`, tried in the browser)
- [ ] Issue is closed (auto-closed or manually)
- [ ] Memory updated if findings emerged
- [ ] No follow-up issues filed (if edge cases discovered, file them as new tickets)

## Common Issues & Recovery

| Issue | Recovery |
|-------|----------|
| Local app is broken after push | **Revert:** `git revert <commit-sha>`, push to `main`. Then debug locally and file a new issue. |
| Issue didn't auto-close | Manually close: `gh issue close <N> --comment "Fixed in <commit-sha>."` |
| Pushed something you wish you hadn't (still recent, no one's pulled it) | `git revert` is always the safe option — never force-push over `main`'s history without explicit user confirmation, even in cowboy mode. |

## Breadcrumbs & Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Verify locally** | `make dev` (Docker + backend + frontend) |
| **Close issue** | `gh issue close <N> --comment "..."` |
| **Memory location** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Project config** | `CLAUDE.md` (source of truth) |

## Notes & Common Gotchas

- **No PR, no merge step** — the push in `/workflow-check` already landed the change on `main`.
- **No branch protection, no CI at all** — nothing automatically gated the push except `/workflow-check`'s local `make ci`.
- **No deploy at all, local-only (issue #110, tooling removed #113)** — there is no `deploy.sh`/`gcp-init.sh` anymore; nothing to run.
- **No Slack** — skip any "post to Slack" steps.
- **GitHub Issues, not Jira** — use `gh issue` for all issue operations.
- **Never force-push `main`** — even in cowboy mode, a bad push gets fixed with `git revert`, not history rewriting, unless the user explicitly asks for that.

## See Also

- **Previous step:** `/workflow-check` for the pre-push checklist
- **GCP deploy removal:** issue #110 (deploy path) and issue #113 (GitHub Actions CI + remaining GCP tooling) for what changed and why
- **Project `CLAUDE.md`** — source of truth for tech stack, patterns, commands
- **Home memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **View all issues:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state all`
