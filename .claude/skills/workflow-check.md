# workflow-check — Opensearch2026 Project

Audit your work against the 14-step workflow BEFORE declaring done. Run this when you believe the PR is ready for review.

## Audit Checklist

This skill walks through steps 1–11 of the global 14-step workflow, adapted for this project's GitHub-based workflows.

### Step 1: Discuss ✓
**Confirm:** You reviewed memory, CLAUDE.md, and prior work on this issue.

```bash
gh issue view <N> --json title,body,comments
```

**Ask:** Any surprises or changes in scope since work started?

### Step 2: Plan ✓
**Confirm:** You proposed an approach and got user approval before coding.

**Check:** Does your commit message / PR body explain the *why*, not just the *what*?

### Step 3: Tasks ✓
**Confirm:** For multi-step work, you created tasks and marked them done as you went.

If this was a quick fix, skip; otherwise, check:
```bash
git log --oneline <feature-branch>..main | head -10
```

Do the commits align with the tasks you planned?

### Step 4: Code ✓
**Confirm:** You edited existing files first. Only create new files if the task explicitly requires it.

**Check file changes:**
```bash
git diff main..<feature-branch> --name-status | head -20
```

- Any new `.py` files created without good reason?
- Any dead code, incomplete implementations, or overly premature abstractions?

### Step 5: Test ✓
**Confirm:** You ran the local test suite and all tests pass.

**Run:**
```bash
cd langchain_agent
PYTHONPATH=. pytest tests/unit/ -v --tb=short
make ci
make smoke-local-quick
```

**Check frontend (if touched):**
```bash
cd langchain_agent/web
npm run lint && npm run test
```

**Artifact:** Failures? Commit any fixes and re-run before moving to step 6.

### Step 6: Commit ✓
**Confirm:** Commits are logical, messages are clear, and pre-commit hooks passed.

**Check:**
```bash
git log <feature-branch>..main --pretty=format:"%H %s" | head -10
```

**Each commit should:**
- Have a clear, imperative-mood message (e.g., "Add latency tracking to reranker node")
- Reference the issue in the PR body, not in individual commit messages (this project doesn't use `TICKET-NNN-` prefixes)
- Pass `black`, `isort`, `flake8`, `mypy` (verified by CI)

**Note:** Pre-commit hooks run on your machine; if they blocked, the commit didn't land. Fix and re-commit (don't amend unless you're fixing the *same* commit).

### Step 7: Update Docs & Memory ⭐ **MOST CRITICAL**
**Confirm:** You updated memory and project docs BEFORE pushing the PR.

**Check & update:**

1. **Project `CLAUDE.md`** — If design or architecture changed, rewrite the relevant memory sections (don't append). Examples:
   - New env var → update `Environment Variables & Scripts` section
   - New test pattern → update `Common Commands` section
   - Architecture change → update `Key Patterns` section

2. **Memory files** — Stale information misleads the next session. Update or create:
   - `memory/project_status_recent_fixes.md` — what's shipping now
   - `memory/reference_*.md` files — if reference docs changed
   - New memory files for non-obvious findings (e.g., a gotcha discovered, a design tradeoff documented)

3. **Index** — Add/update pointers in `memory/MEMORY.md` if you created new memory files.

**Ask:** What changed that future-you should know? If nothing, say so explicitly — that's valid.

### Step 8: Push & Open PR ✓
**Confirm:** You pushed the feature branch and opened a PR.

**Check:**
```bash
git push -u origin <feature-branch>
gh pr create --draft \
  --title "<short title>" \
  --body "$(cat <<'EOF'
## Summary
- <1–3 bullet points on what changed>

## Test Plan
- [ ] Ran PYTHONPATH=. pytest tests/unit/
- [ ] Ran make smoke-local-quick
- [ ] [ ] Ran make ci if touching frontend

## Closes
Closes #<issue-number>
EOF
)"
```

**PR title:** Keep under 70 characters; explain *what* changed.

**PR body:** Explain *why* in 1–3 bullets. Include "Closes #N" to auto-close on squash-merge.

### Step 9: CI Watch ✓
**Confirm:** CI passed (or you dismissed false positives with a reason).

**Check:**
```bash
gh pr checks <PR-number>
```

**Expected workflows:**
- `build-deploy.yml` — backend/frontend linting, tests, type checking
- (No `reindex.yml` unless you touched Lucille stages)

**If CI fails:** Diagnose, fix on the branch, push — the PR auto-updates.

### Step 10: Self-Review ✓
**Confirm:** You read the full diff end-to-end before asking for review.

**Do:**
```bash
git diff main..<feature-branch> | less
# OR
gh pr diff <PR-number> | less
```

**Look for:**
- Stale comments from earlier rounds (delete them)
- Dead code or incomplete implementations (remove or finish)
- Security issues (SQLi, XSS, auth bypass, credential leaks) — fix immediately
- "This looks fine" comments that explain *what* instead of *why* — delete them

**Ask:** Any regrets? Any simplifications you could make? If yes, commit them now.

### Step 11: Flip Draft → Ready ✓
**Confirm:** Once CI is green and self-review is done, mark the PR ready for review.

```bash
gh pr ready <PR-number>
```

**You are now done with this skill.** Next: wait for review feedback (handled by `/workflow-deploy`).

## Common Blockers & Recovery

| Blocker | Recovery |
|---------|----------|
| Tests fail locally but pass in CI | Run tests twice; check for flakiness. If CI green, it's likely an env issue on your machine. |
| Pre-commit hook rejects formatting | Re-run `black` and `isort` manually on changed files, then re-commit. |
| Self-review finds a bug | Commit the fix (new commit, don't amend), push, let CI re-run. |
| Stale memory from prior session | Update `CLAUDE.md` and memory files *now*, before merging. |
| PR title/body unclear | Edit the PR with `gh pr edit` and clarify before requesting review. |

## Notes

- **This is a GATE.** Many sessions skip step 7 (memory update) and pay for it in the next session. Do not cut this corner.
- **GitHub Issues, not Jira** — all issue references use `#N`, not `TICKET-NNN`.
- **No Slack** — skip any "post to Slack" steps. All tracking is in GitHub.
- **Local test suite is authoritative** — CI mirrors it, but if your local tests fail and CI passes, something is wrong with your environment.

## See Also

- Global `/workflow-check` (this skill builds on it)
- Project `CLAUDE.md` for the full 14-step workflow
- `memory/MEMORY.md` for what to update
