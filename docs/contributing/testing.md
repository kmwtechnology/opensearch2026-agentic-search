# Testing Guide

Test pyramid and local testing commands.

**Parent:** [Contributing Guide](README.md)

---

## Test Pyramid

```
         /\
        /  \  Smoke Tests (Cloud Run)
       /    \   ~2 min, 20 tests
      /______\
      /      \
     /  E2E   \  End-to-End Tests
    / Tests    \   ~3 min, 17 tests
   /____________\
   /            \
  / Integration  \  Integration Tests
 /   Tests       \   ~2 min, live PostgreSQL + OpenSearch
/________________\
/                  \
 Unit Tests         ~3 sec, 716 tests, mocked deps
/____________________\
```

**Rule:** More tests at the bottom (fast, deterministic), fewer at the top (slow, flaky).

---

## Unit Tests

**When:** Always. Every code change must have unit tests.

**What:** Pure functions, no I/O (mock PostgreSQL, OpenSearch, Gemini).

**How:** Run locally before pushing.

```bash
cd langchain_agent
PYTHONPATH=. pytest tests/unit/
```

Expected: ~716 tests in ~3 seconds, 0 failures.

### Markers

Run by marker:
```bash
PYTHONPATH=. pytest tests/unit/ -m phase1    # Fast subset
PYTHONPATH=. pytest tests/unit/ -m unit      # All unit tests
```

### Coverage

Check coverage:
```bash
PYTHONPATH=. pytest tests/unit/ --cov=. --cov-report=html
# Open htmlcov/index.html
```

Aim for >80% coverage on critical paths (intent_classifier, retriever, agent).

---

## Integration Tests

**When:** After middleware, WebSocket, or multi-component changes.

**What:** Tests with real PostgreSQL + OpenSearch (from `docker compose`).

**How:** Requires Docker services running.

```bash
# Terminal 1: Start services
cd repo_root
docker compose up -d

# Terminal 2: Run integration tests
cd langchain_agent
PYTHONPATH=. pytest tests/integration/ -m 'not slow'
```

Expected: ~30–120 seconds, 0 failures.

**Critical:** Don't skip integration tests for middleware changes. The pre-push hook runs `make smoke-local` which catches these, but local verification is faster.

---

## End-to-End Tests

**When:** After adding a new flow (e.g., refinement intent, quality gate retry).

**What:** Tests against a deployed Cloud Run service (or local backend running on :8000).

**How:** Requires Docker services + local backend running.

```bash
# Terminal 1: Backend
cd langchain_agent
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# Terminal 2: Run e2e tests
cd langchain_agent
LOGIN_PASSWORD=$(grep '^LOGIN_PASSWORD=' .env | cut -d= -f2) \
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py -v -m "e2e and slow" --timeout=120 --asyncio-mode=auto
```

Expected: ~3 minutes, 17 tests, 0 failures.

**Against Cloud Run:**
```bash
LOGIN_PASSWORD=... \
CLOUD_RUN_URL=https://agentic-hybrid-search-XXXX.run.app \
PYTHONPATH=. pytest tests/e2e/ -v -m "e2e and slow" --timeout=120
```

---

## Smoke Tests (Pre-Push)

**When:** Automatically before pushing (pre-push hook). Or manually before a pull request.

**What:** 20 regression tests covering the full pipeline (auth, search, refinement, citations, latency).

**How:**
```bash
# Quick (search intent only, ~13s)
make smoke-local-quick

# Full suite (~90s)
make smoke-local
```

Expected: All 20 tests pass.

**What it catches:**
- WebSocket connection failures
- Agent not emitting events
- Event fields missing
- Auth gate broken
- Latency SLO exceeded

This is the most valuable gate before pushing. It catches regressions that unit tests can't see.

---

## CI Pipeline

**GitHub Actions (`make ci`)** runs:

1. **Backend lint** (black, isort, flake8, mypy) — ~5s
2. **Unit tests** (pytest tests/unit/) — ~3s
3. **Integration collect-only** (no execution; checks imports) — ~2s
4. **E2E collect-only** (no execution; checks imports) — ~2s
5. **Frontend tests** (vitest) — ~3s
6. **Frontend lint** (eslint) — ~2s
7. **Frontend type check** (tsc) — ~1s
8. **Frontend build** (vite) — ~1s

**Total:** ~20s locally, ~3 min on GitHub (parallel jobs).

If any step fails, the PR is blocked.

---

## Local Testing Before Push

Follow this checklist before `git push`:

```bash
# 1. Unit tests
cd langchain_agent
PYTHONPATH=. pytest tests/unit/

# 2. Lint
make format-fix    # Auto-fix formatting
make lint          # Check lint (should pass after format-fix)

# 3. Smoke tests (catches WebSocket, event, latency issues)
make smoke-local-quick    # Fast: 13s (search intent only)
# OR
make smoke-local          # Full: 90s (all 20 tests)

# 4. Git
git push    # Pre-push hook runs `make ci` again
```

If `make smoke-local-quick` fails, the pre-push hook will also fail. Fix it before pushing.

---

## Integration Test Setup

Integration tests use `docker compose` services. Ensure they're running:

```bash
cd repo_root
docker compose up -d

# Verify
docker compose ps    # Should show postgres, opensearch, opensearch-dashboards
```

Tests use environment variables from `.env`:
- `POSTGRES_HOST=localhost`
- `OPENSEARCH_HOST=localhost`

If you change database credentials in `.env`, update the test conftest too.

---

## E2E Test Requirements

**Local (backend on localhost):**
- Backend running on `:8000`
- `LOGIN_PASSWORD` set in `.env`
- `docker compose up -d` running

**Cloud Run:**
- Service deployed and healthy
- `CLOUD_RUN_URL` env var set
- `LOGIN_PASSWORD` available (retrieve from Secret Manager)

**Important:** E2E tests in `tests/e2e/` are only executed in CI against Cloud Run (GHA workflow `test.yml`). Local execution is optional; the pre-push hook doesn't trigger them.

---

## Debugging Failed Tests

### Print debugging
```python
def test_something():
    result = some_function()
    print(f"Debug: result={result}")  # Visible with -s flag
    assert result == expected
```

Run with output:
```bash
PYTHONPATH=. pytest tests/unit/test_something.py::test_something -v -s
```

### Drop to debugger
```python
import pdb

def test_something():
    result = some_function()
    pdb.set_trace()  # Debugger breaks here
    assert result == expected
```

Run:
```bash
PYTHONPATH=. pytest tests/unit/test_something.py::test_something -v -s --pdb
```

### Check logs
```bash
# Unit tests emit logs to stderr
PYTHONPATH=. pytest tests/unit/ -v --log-cli-level=DEBUG
```

---

## Adding New Tests

### Structure
```
tests/
├── unit/              # No external deps (fast)
│   └── test_intent_classifier.py
├── integration/       # PostgreSQL + OpenSearch (medium)
│   └── test_retriever_with_live_index.py
└── e2e/              # Full system (slow)
    └── test_chat_flow.py
```

### Markers
Use pytest markers to categorize:
```python
@pytest.mark.unit
def test_intent_classification():
    ...

@pytest.mark.integration
def test_retriever():
    ...

@pytest.mark.e2e
@pytest.mark.slow
def test_full_chat_flow():
    ...
```

Then run by marker:
```bash
PYTHONPATH=. pytest tests/unit/ -m unit
PYTHONPATH=. pytest tests/ -m integration
PYTHONPATH=. pytest tests/ -m e2e
```

### Example Unit Test
```python
import pytest
from intent_classifier import classify_intent

@pytest.mark.unit
def test_intent_classifier_search():
    result = classify_intent("Find wireless headphones")
    assert result["intent"] == "search"
    assert result["confidence"] > 0.8

@pytest.mark.unit
def test_intent_classifier_comparison():
    result = classify_intent("Compare Bose and Sony")
    assert result["intent"] == "comparison"
```

---

For code patterns, see [Code Patterns](code-patterns.md). For the PR process, see [PR Process](pr-process.md).
