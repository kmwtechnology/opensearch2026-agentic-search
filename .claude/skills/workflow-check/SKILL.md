---
name: workflow-check
description: "Pre-push checklist for opensearch2026-agentic-search: tests, formatting, self-review, docs/memory update, before pushing straight to main. Cowboy mode — no PR to audit."
---

# workflow-check — Opensearch2026 Project (Cowboy Mode)

Run this pre-push checklist before pushing your commits straight to `main`. There's no PR here to audit — `main` has no branch protection (private repo, no GitHub Pro; `gh api .../branches/main` returns `"protected": false`) — so this skill is your review gate instead of a reviewer's.

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

### 2. Confirm You Have Unpushed Commits

```bash
git fetch origin main
git log origin/main..HEAD --oneline
```

If this is empty, there's nothing to check — you've already pushed.

## Pre-Push Checklist

### Step 1: Verify Context (No Scope Changes)

**Confirm:** Nothing changed that would invalidate the approved plan. If work references an issue, is it still OPEN?

```bash
gh issue view <N> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json state -q '.state'
```

### Step 2: Tasks (Multi-Step Work)

**Confirm:** For multi-step work, commits align with the tasks planned in `/workflow-start`.

```bash
git log origin/main..HEAD --oneline
```

**For quick fixes:** Skip this if straightforward (one commit).

### Step 3: Code (File Changes)

**Confirm:** You edited existing files first; only created new files when the task explicitly required it.

```bash
git diff origin/main..HEAD --name-status
```

**Look for:**
- Any new `.py` files created without explicit need? (Question them.)
- Any new test files? (Good, if testing the new code.)
- Lots of deletions? (Code removal is good; refactoring should be minimal and intentional.)

### Step 4: Test (Local Suite)

**Confirm:** All tests pass locally.

**Checklist:**
- [ ] `cd langchain_agent && make check` — the one command: black/isort/flake8/mypy/unit tests/frontend tests+lint+build, plus a real smoke round-trip against a running backend (needs Docker up). Passes clean?
- [ ] (Optional, faster while iterating) `make ci` alone — same checks minus the live-backend smoke test, no Docker required.

**If tests fail:**
- Commit fixes, re-run this checklist.
- Do NOT push until tests pass locally — there's no CI or reviewer to catch it after.

### Step 5: Commit (Message Quality & Formatting)

**Confirm:** Commits are logical and messages are clear.

```bash
git log origin/main..HEAD --pretty=format:"%H %s"
```

**Each commit should:**
- Have a clear, imperative-mood message (e.g., "Add latency tracking to reranker node")
- Have been run through formatters: `cd langchain_agent && make format-fix`
- **Important:** `.git/hooks/pre-commit` (installed by `scripts/setup.sh`, issue #99) runs black/isort/flake8 on staged `.py` files automatically at commit time. There is still NO pre-push hook — `.git/hooks/pre-push` is Git LFS's own hook only. **You must run tests/smoke gates by hand before pushing.**

**If referencing an issue:** `Closes #<N>` in a commit message auto-closes it on push to `main` (GitHub closes issues on merge to the default branch, not just via PR merge).

### Step 6: Update Docs & Memory ⭐ (MOST CRITICAL)

**Confirm:** You updated CLAUDE.md and memory BEFORE pushing. (This is the #1 skipped step and causes stale guidance.)

**Checklist:**

1. **Did architecture/design change?** → Update `CLAUDE.md`:
   - New env var? → Update the relevant `CLAUDE.md` section
   - New test pattern? → Update `Commands`
   - New auth flow? → Update `Auth model`
   - If in doubt, rewrite the affected section (don't append)

2. **Create or update memory if you discovered something non-obvious:**
   ```bash
   cat > ~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/finding_<date>_<slug>.md <<'EOF'
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

3. **Update memory index:**
   ```bash
   # Add a line to the index
   echo "- [Finding Title](finding_<date>_<slug>.md) — one-line summary" >> ~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md
   ```

**Ask the user:** What changed that future-you should know? If nothing, say so explicitly — that's valid.

### Step 7: CI Reality Check (No GitHub Actions)

There is no GitHub Actions CI to wait for (issue #113 removed `.github/workflows/build-deploy.yml` entirely — it had never provided working CI anyway, since runners were unavailable on this repo). `make check` run locally is the only gate that exists, and you've already run it in Step 4.

### Step 8: Self-Review

**Confirm:** You read the full diff end-to-end before pushing.

```bash
git diff origin/main..HEAD | less
```

**Look for:**
- ✓ Stale comments from earlier rounds → delete them
- ✓ Dead code or incomplete implementations → remove or finish
- ✓ Security issues (SQLi, XSS, auth bypass, credential leaks) → fix immediately
- ✓ Comments that say *what* instead of *why* → delete them
- ✓ Obvious simplifications → commit them now

**Ask the user:** Any regrets? Any last simplifications?

### Step 9: Push

```bash
git push origin main
```

✅ **You are now done with this skill.** Next: `/workflow-deploy` to verify locally and close the issue.

## Common Blockers & Recovery

| Blocker | Recovery |
|---------|----------|
| `make check` fails intermittently | Run it twice; check for flakiness (test ordering, stray state from a prior run). |
| `make check` fails on formatting (black/isort) | Run `make format-fix`, commit. |
| Self-review finds a bug | Commit the fix (new commit) before pushing. Re-run `make check`. |
| `make check` fails at the smoke step with exit code 2 | Docker services aren't up — `docker compose up -d` from repo root, then re-run. |
| Stale memory from prior session | Update `CLAUDE.md` and memory files NOW before continuing. Future-you will thank you. |
| Push rejected (`main` moved) | `git pull --rebase origin main`, resolve conflicts, re-run this checklist, push again. |

## Breadcrumbs & Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Unpushed commits** | `git log origin/main..HEAD --oneline` |
| **CI gate** | `make check` locally — no GitHub Actions CI exists (issue #113) |
| **Push** | `git push origin main` |
| **View diff** | `git diff origin/main..HEAD` |
| **Test commands** | `make check` (full gate), `make ci` (fast, no live services), `PYTHONPATH=. pytest tests/unit/` (unit only) |
| **Format fix** | `make format-fix` (or manually: `black .`, `isort .`, `flake8 .`, `mypy main.py`) |
| **Memory location** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Project config** | `CLAUDE.md` (source of truth) |

## Notes & Common Gotchas

- **Step 6 is CRITICAL** — many sessions skip memory updates and rot guidance. Do not cut this corner.
- **The pre-commit hook only catches formatting/lint** — no local hook runs tests or the smoke gate. Run `make check` locally before pushing.
- **GitHub Issues, not Jira** — all references use `#N`, not `TICKET-NNN`.
- **No Slack** — skip any "post to Slack" steps.
- **No PR, no reviewer, no CI** — this checklist is the only gate. Take it seriously.

## See Also

- **Previous step:** `/workflow-start` to plan and start coding
- **Next step:** `/workflow-deploy` once pushed, to verify locally and close the issue
- **Project `CLAUDE.md`** — source of truth for tech stack, patterns, commands
- **Home memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **View all issues:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state open`
