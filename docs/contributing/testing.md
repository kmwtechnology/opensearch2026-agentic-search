# Testing Guide

Test pyramid and local testing commands.

**Parent:** [Contributing Guide](README.md)

---

## Test Pyramid

```
       /\
      /  \  E2E / Smoke (tests/e2e/, 21 tests, 2 files)
     /    \   make smoke: 1 test, ~13-20s, real backend
    /______\   full run: bash scripts/smoke_local.sh, ~90s
    /      \
   / Integ. \  Integration Tests (tests/integration/, ~207 tests)
  /  Tests   \   ~30-120s, live PostgreSQL + OpenSearch + GOOGLE_API_KEY
 /____________\
 /              \
  Unit Tests      863 tests, ~7s, mocked deps
 /________________\
```

**Rule:** More tests at the bottom (fast, deterministic), fewer at the top (slow, flaky). `make check` runs unit tests for real, integration/e2e as `--collect-only` (import/signature check), plus one real smoke test — see "Local Gate" below.

---

## Unit Tests

**When:** Always. Every code change must have unit tests.

**What:** Pure functions, no I/O (mock PostgreSQL, OpenSearch, Gemini).

**How:** Run locally before pushing.

```bash
cd langchain_agent
PYTHONPATH=. pytest tests/unit/
```

Expected: 863 tests in ~7 seconds, 0 failures.

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

**Critical:** Don't skip integration tests for middleware changes. There is no pre-push hook that runs the smoke gate — run `make check` manually; local verification is faster than finding out later.

---

## End-to-End Tests

**When:** After adding a new flow (e.g., refinement intent, quality gate retry).

**What:** Tests against a running local backend on :8000 by default (or a remote URL via `CLOUD_RUN_URL`).

**How:** Requires Docker services + local backend running.

```bash
# Terminal 1: Backend
cd langchain_agent
PYTHONPATH=. uvicorn api.main:app --reload --port 8000

# Terminal 2: Run e2e tests
cd langchain_agent
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py -v -m "e2e and slow" --timeout=120 --asyncio-mode=auto
```

Expected: 18 tests, well under a minute, 0 failures.

**Against a remote backend** (if you ever need to point these somewhere other than local):
```bash
CLOUD_RUN_URL=https://your-remote-backend.example.com \
PYTHONPATH=. pytest tests/e2e/ -v -m "e2e and slow" --timeout=120
```

---

## Smoke Test (Pre-Push)

**When:** Manually before pushing — there is no pre-push hook in this repo, so run this by hand before pushing or merging.

**What:** A focused search-intent regression test against a running local backend (part of the broader 20+-test suite in `tests/e2e/`).

**How:**
```bash
make smoke    # ~13-20s, search intent only, needs Docker + backend
```

There's no dedicated Make target for the full regression suite — run it directly when you want the deeper check (e.g. after a WebSocket/service-wiring change):
```bash
bash scripts/smoke_local.sh   # ~90s, all e2e+slow scenarios (21 tests)
```

**What it catches:**
- WebSocket connection failures
- Agent not emitting events
- Event fields missing
- Same-origin checking broken
- Latency SLO exceeded

This is the most valuable gate before pushing. It catches regressions that unit tests can't see.

---

## Local Gate

There is no GitHub Actions CI (issue #113) — **`make check`** run locally is
the only gate. It's two layers:

`make ci` (fast, no live services needed, ~40-45s — most of that is `ci-tools`' pip install and the frontend's `npm install`/build):
1. **Backend lint** (black, isort, flake8, mypy) — ~5s
2. **Unit tests** (pytest tests/unit/) — ~3s
3. **Integration collect-only** (no execution; checks imports) — ~2s
4. **E2E collect-only** (no execution; checks imports) — ~2s
5. **Frontend tests** (vitest) — ~3s
6. **Frontend lint** (eslint) — ~2s
7. **Frontend type check** (tsc) — ~1s
8. **Frontend build** (vite) — ~1s

`make check` adds one more step on top of `ci`:

9. **Smoke test** (`make smoke`, real round-trip against a running backend, needs Docker up) — ~13-20s

If any step fails, `make check` exits non-zero and points at the failing step.

---

## Local Testing Before Push

Follow this checklist before `git push`:

```bash
cd langchain_agent
make check    # the one command: format check, lint, unit tests, frontend, smoke test
```

Use `make format-fix` first if `make check` fails on formatting. For fast
iterative feedback while coding (no live services needed), run `make ci`
alone instead of the full `check`.

A `.git/hooks/pre-commit` hook (installed by `scripts/setup.sh`) catches black/isort/flake8 violations at commit time. There is still no local pre-push hook (`.git/hooks/pre-push` is Git LFS's own hook only); run `make check` manually before pushing. Nothing stops a push with failing tests except this local gate.

---

## Integration Test Setup

Integration tests use `docker compose` services. Ensure they're running:

```bash
cd repo_root
docker compose up -d

# Verify
docker compose ps    # Should show postgres, opensearch
```

Tests use environment variables from `.env`:
- `POSTGRES_HOST=localhost`
- `OPENSEARCH_HOST=localhost`

If you change database credentials in `.env`, update the test conftest too.

---

## E2E Test Requirements

**Local (backend on localhost):**
- Backend running on `:8000`
- `docker compose up -d` running
- No login step required — there is no login gate; same-origin checking is the only auth layer

**Important:** E2E tests in `tests/e2e/` are not run automatically — there is
no GitHub Actions CI (issue #113) and no pre-push hook either. Run them
manually against a local backend as documented above.

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
from pipeline.pipeline_nodes import PipelineNodesMixin

@pytest.mark.unit
def test_intent_classifier_search(pipeline_nodes_instance):
    state = {"messages": [("user", "Find wireless headphones")]}
    result = pipeline_nodes_instance.intent_classifier_node(state)
    assert result["intent"] == "search"
    assert result["confidence"] > 0.8

@pytest.mark.unit
def test_intent_classifier_comparison(pipeline_nodes_instance):
    state = {"messages": [("user", "Compare Bose and Sony")]}
    result = pipeline_nodes_instance.intent_classifier_node(state)
    assert result["intent"] == "comparison"
```

`intent_classifier_node` is a method on `PipelineNodesMixin` (`pipeline/pipeline_nodes.py`), not a standalone function — real unit tests mock the LLM call and instantiate the mixin (or the full agent) rather than importing a free function. See `tests/unit/*/test_intent_classifier.py` for the actual test patterns used in this repo.

---

For code patterns, see [Code Patterns](code-patterns.md). For the PR process, see [PR Process](pr-process.md).
