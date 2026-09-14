# Contributing Guide

How to contribute code, tests, and documentation to Agentic Hybrid Search.

**Parent:** [Root README](../../README.md)

## Quick Links

| Guide | Purpose | For Whom |
|-------|---------|----------|
| [Local Dev Setup](dev-setup.md) | Prerequisites, setup.sh walkthrough, daily workflow | New contributors |
| [Code Patterns](code-patterns.md) | PYTHONPATH, state access, exceptions, event parity | Backend/Frontend devs |
| [Testing](testing.md) | Test pyramid (unit → integration → e2e → smoke), commands | Test developers |
| [PR Process](pr-process.md) | Branch naming, commit format, PR template, review checklist | All contributors |

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

1. **Create a feature branch:** `git checkout -b feat/issue-NNN-slug`
2. **Make changes** — edit code, add tests
3. **Run local tests:** `PYTHONPATH=. pytest tests/unit/` + `make smoke-local-quick`
4. **Commit with ticket prefix:** `git commit -m "TICKET-NNN: description"`
5. **Push:** `git push origin feat/issue-NNN-slug`
6. **Open PR:** GitHub Actions CI runs automatically
7. **Self-review:** Read the diff, check for stale comments, dead code
8. **Address feedback:** New commits (don't amend)
9. **Merge:** Squash to `main`

See [PR Process](pr-process.md) for detailed instructions.

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

1. ✅ All unit tests pass: `PYTHONPATH=. pytest tests/unit/`
2. ✅ Smoke tests pass: `make smoke-local-quick` (or full `make smoke-local`)
3. ✅ Linting clean: `make lint` (or `make format-fix`)
4. ✅ No dead code or stale comments
5. ✅ Event parity verified (if you touched events)

`.git/hooks/pre-commit` (installed by `scripts/setup.sh`) runs black/isort/flake8 on staged `.py` files at commit time, so #3 above is partly caught automatically. There is still no pre-push hook (`.git/hooks/pre-push` is Git LFS's own hook only) — #1, #2, #4, and #5 above are not automated, so run `make ci` and the smoke gates manually before pushing.

---

## Questions?

- **Architecture:** See [ARCHITECTURE.md](../../langchain_agent/ARCHITECTURE.md)
- **API endpoints:** See [docs/integration/](../integration/)
- **Operations:** See [docs/operations/](../operations/)
- **Project structure:** See [langchain_agent/README.md](../../langchain_agent/README.md)

---

For code patterns, see [Code Patterns](code-patterns.md). For testing, see [Testing](testing.md). For the PR process, see [PR Process](pr-process.md).
