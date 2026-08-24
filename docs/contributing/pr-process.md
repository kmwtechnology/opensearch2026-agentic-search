# PR Process

Branch naming, commit conventions, PR template, and review checklist.

**Parent:** [Contributing Guide](README.md)

---

## Branch Naming

**Format:** `<type>/<issue-number>-<slug>`

| Type | When | Example |
|------|------|---------|
| `feat/` | New feature | `feat/issue-42-refinement-intent` |
| `fix/` | Bug fix | `fix/issue-28-swagger-localhost` |
| `docs/` | Documentation | `docs/contributing-guide` |
| `refactor/` | Code cleanup (no behavior change) | `refactor/simplify-auth` |
| `chore/` | Maintenance (deps, CI, config) | `chore/upgrade-langchain` |

**Rules:**
- Use issue number if one exists (e.g., issue #42)
- Use kebab-case for slug
- Keep it short (<50 chars total)

---

## Commit Message Format

**Format:** `<TYPE>: <description> (optional footer)`

Prefix with type (matching branch type):
- `feat:` — new feature
- `fix:` — bug fix
- `docs:` — documentation
- `refactor:` — code cleanup
- `chore:` — maintenance

**Example:**
```
feat: add refinement intent support

- Detects "refinement" queries that narrow prior results
- Validates category overlap; requests clarification if <0.3
- Adds 18 unit tests

Closes #42.
```

**Guidelines:**
1. **First line:** 50 chars max, imperative mood ("add" not "added")
2. **Blank line:** Separate from body
3. **Body:** Explain **why**, not **what**. The diff shows what changed.
4. **Footer:** Reference issue with `Closes #NNN.` or `See #NNN.`

---

## Before Opening a PR

- [ ] Create feature branch: `git checkout -b feat/issue-NNN-slug`
- [ ] Make changes and test locally
- [ ] Run `PYTHONPATH=. pytest tests/unit/` — all pass
- [ ] Run `make smoke-local-quick` — all pass (or `make smoke-local` for confidence)
- [ ] Run `make lint` — no violations (or `make format-fix` to auto-fix)
- [ ] Read your own diff — spot any dead code, stale comments
- [ ] Commit and push

---

## Opening a PR

**Use GitHub UI** to create a PR. Fill out the template:

```markdown
## Summary
- Implement refinement intent detection
- Validate category overlap; request clarification on low continuity
- Add 18 unit tests

## Testing
- [ ] Unit tests pass (make sure to run locally)
- [ ] Smoke tests pass
- [ ] No integration/e2e needed (no middleware changes)

## Deployment
- [ ] Ready to merge
- [ ] Requires post-deploy validation (manual smoke test on Cloud Run)

## Related
Closes #42.
```

**Don't** force-push or amend after opening. Add new commits; the maintainer will squash on merge.

---

## Code Review Checklist

Self-review before asking for review:

- [ ] **No dead code** — remove unused variables, functions, imports
- [ ] **No stale comments** — comments should explain why, not what
- [ ] **Event parity** — if backend events changed, frontend types match
- [ ] **Auth pattern** — new routes use `verify_same_origin` + `verify_session`, not `verify_api_key`
- [ ] **PYTHONPATH** — all test commands include `PYTHONPATH=.`
- [ ] **Exception handling** — no bare `except Exception`, use subclasses
- [ ] **State access** — use `.get()` on `CustomAgentState`, not `[]`
- [ ] **Env vars** — if new config added, it's in `.env.example` AND `build-deploy.yml --set-secrets`
- [ ] **Tests** — new code has unit tests; integration tests if multi-component

---

## Addressing Feedback

**Maintainer's feedback comes as comments on the diff.**

1. **Read the comment carefully.** Understand why, not just what to change.
2. **Reply to each comment:** Either "Done" (if you made the change) or explain why you disagree.
3. **Make changes and push new commits.** Do NOT amend.

Example:
```
💬 Maintainer: "This exception should be more specific than Exception."

✓ You: "Done — changed to catch SearchTimeoutError specifically."
```

**After addressing all feedback:**
1. Re-run `make smoke-local-quick` locally
2. Push the new commit
3. **Re-request review** (GitHub button at the top of the PR)

---

## Merge

**Maintainer will squash to main** after CI passes and review is approved.

All your commits become one:
```
feat: add refinement intent support

- Detects "refinement" queries that narrow prior results
- Validates category overlap; requests clarification if <0.3
- Adds 18 unit tests

Closes #42.
```

**Your branch is then deleted.** Nothing to do on your end.

---

## PR Template

Use the template above. Customize for your change:

```markdown
## Summary
Brief 1-3 bullet points of what changed.

## Test plan
- [ ] Unit tests pass
- [ ] Smoke tests pass
- [ ] Manual testing (if needed)

## Deployment notes
- Any breaking changes?
- Any new env vars?
- Any post-deploy validation needed?

## Related
Closes #NNN.
```

**Keep it concise.** The diff is the source of truth; the PR body explains why.

---

## Common Mistakes

### Force-pushing
**Don't.** If the maintainer has reviewed your PR and you add new commits with `git push --force`, their review context is lost.

**Right:** `git push` (normal push)
**Wrong:** `git push --force` (after opening PR)

### Amending after PR
**Don't.** Use new commits instead.

**Right:**
```bash
git commit -m "fix: address review feedback"
git push
```

**Wrong:**
```bash
git commit --amend -m "feat: refactored"
git push --force
```

### Bare Exception catches
**Don't.** Use specific subclasses.

**Right:**
```python
try:
    query_result = evaluate_query(query)
except SearchTimeoutError as e:
    logger.warning("Timeout", exc_info=True)
```

**Wrong:**
```python
try:
    query_result = evaluate_query(query)
except Exception:
    pass
```

### Missing event parity
**Don't.** If you add a field to a backend event, add it to the frontend type too.

**Right:**
```python
# backend
class SearchProgressEvent(BaseEvent):
    type: Literal["search_progress"]
    intent: str
    confidence: float

# frontend
type SearchProgressEvent = BaseEvent & {
  type: "search_progress";
  intent: string;
  confidence: number;
};
```

**Wrong:** Only update backend; frontend types don't match → test fails.

---

For code patterns, see [Code Patterns](code-patterns.md). For testing, see [Testing](testing.md).
