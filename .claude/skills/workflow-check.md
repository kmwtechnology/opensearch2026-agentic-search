# workflow-check — Opensearch2026 Project

Audit your work against the 14-step workflow. Run this when you have a PR number and believe the code is ready for review.

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

### 2. Get Your PR Number

You need a PR number to run this skill. Pass it with `--pr <N>`.

**If you already have the PR number:** Skip to Step 3.

**If you're on the feature branch and don't remember the PR number:**
```bash
gh pr view --repo kmwtechnology/opensearch2026-agentic-search --json number -q '.number'
```

**If you don't have a PR yet:** Run `/workflow-start <issue-number>` first. workflow-start always creates a draft PR.

After setup, the rest of this skill assumes auth is ready and you have a PR number.

## Quick PR Info Retrieval

If you have a PR number but lost context, retrieve it here:

```bash
# Get full PR details
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json number,title,body,state,draft,baseRefName,headRefName,commits,reviews,checks

# Get linked issue (extract "Closes #N" from body)
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json body -q '.body' | sed -n 's/.*Closes #\([0-9]*\).*/\1/p'

# Get the branch name
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName'
```

**Save these for reference:**
- PR number (`#<PR-number>`)
- Issue number (from "Closes #<N>" in body)
- Branch name (should be `feat/issue-<N>-*` or `fix/issue-<N>-*`)

## Audit Checklist — Steps 1–11

This skill walks through steps 1–11 of the 14-step workflow, adapted for this project.

### Step 1: Discuss ✓ (Context Review)

**Confirm:** You reviewed memory, CLAUDE.md, and prior work on this issue.

```bash
# Get issue number from PR body (extract "Closes #N")
ISSUE_NUM=$(gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json body -q '.body' | sed -n 's/.*Closes #\([0-9]*\).*/\1/p')

if [ -z "$ISSUE_NUM" ]; then
  echo "Error: Could not find 'Closes #N' in PR body"
  exit 1
fi

# View full issue
gh issue view $ISSUE_NUM \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json number,title,body,state,comments
```

**Ask:** Any surprises or scope changes since you started? Is the issue still OPEN (or should it be)?

### Step 2: Plan ✓ (Approach & Approval)

**Confirm:** You proposed an approach and got user approval before coding.

**Check:** Does your PR body explain the *why*, not just the *what*?

```bash
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json body -q '.body'
```

**Good PR body examples:**
- ✓ "Fixes timeout issue by increasing reranker batch size. Quality gate now retries on low scores (fixes #38)."
- ✓ "Add Langfuse tracing for cost visibility. Wrapped `langfuse.CallbackHandler` in config; zero prod overhead (fixes #18)."
- ✗ "Update reranker" ← too vague, no why
- ✗ "Change line 88" ← implementation detail, not rationale

### Step 3: Tasks ✓ (Multi-Step Work)

**Confirm:** For multi-step work, you tracked tasks and committed aligned with them.

```bash
# Get all commits in this PR
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json commits -q '.commits[] | "\(.oid | .[0:7]) \(.messageHeadline)"'

# OR: view commits in branch
BRANCH=$(gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName')
git log main..$BRANCH --oneline
```

**For quick fixes:** Skip this if straightforward (one commit).

**For multi-step work:** Confirm that commits align with tasks planned in `/workflow-start`.

### Step 4: Code ✓ (File Changes)

**Confirm:** You edited existing files first; only created new files when the task explicitly required it.

```bash
BRANCH=$(gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName')
git diff main..$BRANCH --name-status
```

**Look for:**
- Any new `.py` files created without explicit need? (Question them.)
- Any new test files? (Good, if testing the new code.)
- Lots of deletions? (Code removal is good; refactoring should be minimal and intentional.)

### Step 5: Test ✓ (Local Suite)

**Confirm:** You ran the local test suite before pushing. All tests pass.

**Checklist:**
- [ ] `cd langchain_agent && PYTHONPATH=. pytest tests/unit/ -v --tb=short` — all pass?
- [ ] `make ci` — black/isort/flake8/mypy/frontend tests all pass?
- [ ] `make smoke-local-quick` — ~13s search-intent smoke test pass?
- [ ] Frontend touched? `cd langchain_agent/web && npm run lint && npm run test` — all pass?

**If tests fail locally:**
- Commit fixes, push, then re-run this audit.
- Do NOT proceed to "ready for review" until tests pass locally.

### Step 6: Commit ✓ (Message Quality & Formatting)

**Confirm:** Commits are logical and messages are clear.

```bash
BRANCH=$(gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName')
git log main..$BRANCH --pretty=format:"%H %s"
```

**Each commit should:**
- Have a clear, imperative-mood message (e.g., "Add latency tracking to reranker node")
- Have been run through formatters:
  ```bash
  cd langchain_agent
  .venv/bin/black . && .venv/bin/isort . && .venv/bin/flake8 . && .venv/bin/mypy main.py config.py --ignore-missing-imports
  ```
- **Important:** There is NO local code-quality hook. `.git/hooks/pre-push` is Git LFS's own hook only. **You must run formatters by hand before pushing.** If CI catches formatting issues, fix them (`make format-fix`), commit, and push again.

**PR body should:**
- Reference the issue: `Closes #<N>` (auto-closes on merge)
- Explain *why* in 1–3 bullets
- Include test checklist (done ☑ before pushing)

### Step 7: Update Docs & Memory ⭐ (MOST CRITICAL)

**Confirm:** You updated CLAUDE.md and memory BEFORE pushing the PR. (This is the #1 skipped step and causes stale guidance.)

**Checklist:**

1. **Did architecture/design change?** → Update `CLAUDE.md`:
   - New env var? → Update `Key Patterns` section
   - New test pattern? → Update `Common Commands`
   - New auth flow? → Update `Auth` section
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

### Step 8: Push & Open PR ✓

**Confirm:** You pushed the feature branch and opened (or already opened) a PR.

**If PR already exists:** Skip to step 9.

**If creating a new PR:**
```bash
gh pr create \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --draft \
  --title "Fix issue title (under 70 chars)" \
  --body "$(cat <<'EOF'
## Summary
- What changed (1–3 bullets)

## Test Plan
- [x] PYTHONPATH=. pytest tests/unit/
- [x] make smoke-local-quick
- [x] make ci

## Closes
Closes #<issue-number>
EOF
)"
```

**Title:** Keep under 70 characters; explain *what* changed.

**Body:** Explain *why* in 1–3 bullets. **Must include "Closes #<N>"** for auto-close on merge.

### Step 9: CI Watch ✓

**Confirm:** CI passed (or you documented false positives with reasons).

```bash
gh pr checks <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search
```

**Expected checks (from `build-deploy.yml`):**
- `unit-tests` ✓
- `integration-tests` ✓
- `lint-backend` (black/isort/flake8/mypy) ✓
- `frontend-tests` ✓
- `shellcheck` ✓

**Note:** `build-docker` and `deploy-cloud-run` only run on `main`, not on PRs.

**If CI fails:**
- Diagnose the failure
- Commit fixes, push
- Wait for CI to re-run (it auto-updates the PR)
- Re-check `gh pr checks` once CI goes green

### Step 10: Self-Review ✓

**Confirm:** You read the full diff end-to-end before requesting review.

```bash
BRANCH=$(gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json headRefName -q '.headRefName')
git diff main..$BRANCH | less
# OR
gh pr diff <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search | less
```

**Look for:**
- ✓ Stale comments from earlier rounds → delete them
- ✓ Dead code or incomplete implementations → remove or finish
- ✓ Security issues (SQLi, XSS, auth bypass, credential leaks) → fix immediately
- ✓ Comments that say *what* instead of *why* → delete them
- ✓ Obvious simplifications → commit them now

**Ask the user:** Any regrets? Any last simplifications?

### Step 11: Flip Draft → Ready ✓

**Confirm:** CI is green, self-review is done. Mark the PR ready for review.

```bash
# Confirm CI is green one more time
gh pr checks <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search

# Mark ready (flip from draft to ready)
gh pr ready <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search
```

**Verify:**
```bash
gh pr view <PR-number> \
  --repo kmwtechnology/opensearch2026-agentic-search \
  --json draft
# Should return: {"draft": false}
```

✅ **You are now done with this skill.** Next: wait for review feedback, then run `/workflow-deploy <PR-number>`.

## Common Blockers & Recovery

| Blocker | Recovery |
|---------|----------|
| Tests fail locally but pass in CI | Run tests twice; check for flakiness. If CI is green, it's likely an env issue on your machine. |
| CI fails on formatting (black/isort) after push | Run `make format-fix`, commit, push. |
| Self-review finds a bug | Commit the fix (new commit, don't amend), push. CI re-runs. Re-check and re-request review. |
| Stale memory from prior session | Update `CLAUDE.md` and memory files NOW before continuing. Future-you will thank you. |
| PR title/body unclear | Use `gh pr edit <PR-number>` to clarify before requesting review. |
| CI won't go green | Check if your change touches only root-level files outside the monitored paths — if so, `build-deploy.yml` won't run CI at all (intentional but risky). Flag this to the user. |

## Breadcrumbs & Quick Reference

| What | Where |
|------|-------|
| **GH auth account** | `agileresearchservices` (switch with `gh auth switch -u agileresearchservices`) |
| **Repo** | `kmwtechnology/opensearch2026-agentic-search` |
| **Get issue from PR** | `gh pr view <PR> --json body \| sed -n 's/.*Closes #\([0-9]*\).*/\1/p'` |
| **Get PR CI status** | `gh pr checks <PR>` |
| **Mark PR ready** | `gh pr ready <PR>` |
| **View PR diff** | `gh pr diff <PR>` |
| **Test commands** | `PYTHONPATH=. pytest tests/unit/`, `make ci`, `make smoke-local-quick` |
| **Format fix** | `make format-fix` (or manually: `black .`, `isort .`, `flake8 .`, `mypy main.py ...`) |
| **Memory location** | `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md` |
| **Project config** | `CLAUDE.md` (source of truth) |

## Notes & Common Gotchas

- **Step 7 is CRITICAL** — many sessions skip memory updates and rot guidance. Do not cut this corner.
- **No local hook stops you** — only CI catches formatting issues. Run `make ci` locally before pushing.
- **GitHub Issues, not Jira** — all references use `#N`, not `TICKET-NNN`.
- **No Slack** — skip any "post to Slack" steps.
- **CI doesn't run on root files** — if your change touches only files outside `langchain_agent/`, `.github/workflows/`, `docker-compose.yml`, `.dockerignore`, CI won't trigger. This is intentional but risky — flag it.

## See Also

- **Previous step:** `/workflow-start <issue-number>` to create the branch
- **Next step:** `/workflow-deploy <PR-number>` once review is done (step 12–14)
- **Project `CLAUDE.md`** — source of truth for tech stack, patterns, commands
- **Home memory:** `~/.claude/projects/-Users-kevin-github-kmwtechnology-opensearch2026-agentic-search/memory/MEMORY.md`
- **View all PRs:** `gh pr list --repo kmwtechnology/opensearch2026-agentic-search`
- **View all issues:** `gh issue list --repo kmwtechnology/opensearch2026-agentic-search --state open`
