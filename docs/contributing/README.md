# Contributing Guide

How to contribute code, tests, and documentation to Agentic Hybrid Search.

**Parent:** [Root README](../../README.md)

## Quick Links

| Guide | Purpose | For Whom |
|-------|---------|----------|
| [Local Dev Setup](dev-setup.md) | Prerequisites, setup.sh walkthrough, daily workflow | New contributors |
| [Code Patterns](code-patterns.md) | PYTHONPATH, state access, exceptions, event parity | Backend/Frontend devs |
| [Testing](testing.md) | Test pyramid (unit → integration → e2e → smoke), commands | Test developers |
| [PR Process](pr-process.md) | Branch naming, commit format, PR template, review checklist — for the **optional** branch+PR path | Contributors who want pre-merge review |

---

## Development Setup

**One-time setup:**
```bash
cd langchain_agent
cp .env.example .env
# Set GOOGLE_API_KEY in .env
./scripts/setup.sh    # ~10-20 min
```

**Start development servers:**
```bash
./scripts/start.sh    # Backend :8000 + Frontend :5173
```

**Stop servers:**
```bash
./scripts/stop.sh
```

**Verify setup is healthy:**
```bash
make doctor    # Check prerequisites
```

---

## Contribution Flow

This repo runs in **"cowboy mode"** (as of 2026-09-15): the default flow commits directly to `main`, no feature branch or PR required. `main` has no branch protection (private repo, no GitHub Pro), there is no CI (GitHub Actions were removed entirely, issue #113), and there is no deploy step (issue #110). `make check` run locally, before you push, is the only gate that exists for anything in this repo.

1. **Get issue context (optional):** use the `workflow-start` skill, or just read the issue yourself
2. **Make changes — directly on `main`:** edit code, add tests
3. **Run local tests:** `make check` (the full gate) or `make ci` alone for fast iteration
4. **Commit:** `git commit -m "feat: description"` — include `Closes #N` to auto-close the issue on push
5. **Self-review:** use the `workflow-check` skill, or read your own diff — check for stale comments, dead code
6. **Push:** `git push origin main`
7. **Verify and close out:** use the `workflow-deploy` skill, or run `make dev` locally to confirm the change works

**Want pre-merge review instead?** Branching and opening a PR is still supported — it's opt-in, not the default. See [PR Process](pr-process.md) for that path. Never force-push `main`; fix a bad push with `git revert`.

---

## Code Quality Standards

- **Backend:** Python 3.14+, typed with `mypy`, linted with `flake8`
- **Frontend:** TypeScript + React 19, linted with ESLint, tested with Vitest
- **Tests:** Unit tests mandatory; integration tests for multi-component changes; e2e for flow changes

See [Testing](testing.md) for the test pyramid and how to run each tier.

---

## Key Patterns

### PYTHONPATH

All Python invocations from `langchain_agent/` need `PYTHONPATH=.`:

```bash
PYTHONPATH=. pytest tests/unit/
PYTHONPATH=. python main.py
PYTHONPATH=. black .
```

Omitting it causes `ModuleNotFoundError: No module named 'config'`.

### State Access

`CustomAgentState` is `total=False`. Only `messages` is guaranteed. Always use `.get()`:

```python
intent = state.get("intent")
confidence = state.get("confidence", 0.5)
```

### Exception Hierarchy

All custom exceptions inherit from `AgenticHybridSearchError`. No bare `Exception` catches:

```python
try:
    result = expensive_operation()
except SearchTimeoutError as e:
    logger.warning("Search timed out", exc_info=True)
except AgenticHybridSearchError as e:
    if e.recoverable:
        # Retry
    else:
        raise
```

### Event Parity

Backend events in `api/schemas/events.py` must match frontend types in `web/src/types/events.ts`. Verified by `test_frontend_backend_event_parity.py`.

See [Code Patterns](code-patterns.md) for full details.

---

## Before You Push

1. ✅ `make check` passes — runs unit tests, linting, frontend checks, and the smoke test in one command
2. ✅ No dead code or stale comments
3. ✅ Event parity verified (if you touched events)

`.git/hooks/pre-commit` (installed by `scripts/setup.sh`) runs black/isort/flake8 on staged `.py` files at commit time, so formatting is partly caught automatically. There is still no pre-push hook (`.git/hooks/pre-push` is Git LFS's own hook only) — run `make check` manually before pushing.

---

## Questions?

- **Architecture:** See [ARCHITECTURE.md](../../langchain_agent/ARCHITECTURE.md)
- **API endpoints:** See [docs/integration/](../integration/)
- **Project structure:** See [langchain_agent/README.md](../../langchain_agent/README.md)

---

For code patterns, see [Code Patterns](code-patterns.md). For testing, see [Testing](testing.md). For the PR process, see [PR Process](pr-process.md).
