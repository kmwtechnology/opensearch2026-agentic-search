# Contributing

**Parent:** [Root README](../../README.md)

## Flow

This repo runs in "cowboy mode": commit directly to `main`. There is no branch
protection, no CI service, and no deploy step, so the gate is the one you run
yourself.

1. Make the change on `main` (edit code, add or adjust tests).
2. Iterate with `PYTHONPATH=. .venv/bin/pytest tests/unit/` (no services).
3. Run `make ci` from `langchain_agent/` and get it green.
4. Update the docs that describe what you changed (see the doc map in the
   root README) and, for Claude Code sessions, `CLAUDE.md`.
5. Commit and `git push origin main`. `Closes #N` in the message auto-closes
   the GitHub issue. Never force-push `main`; fix a bad push with `git revert`.

A branch and PR are still fine when you want a review first; they are opt-in.

## The gate: `make ci`

One command, in this order; it stops at the first failure:

1. `black --check`, `isort --check-only`, `flake8`, `mypy main.py`
2. `pytest tests/unit/` (~30s, no services)
3. `pytest --collect-only tests/e2e/` (import and signature check)
4. Frontend: vitest, eslint, `tsc --noEmit`, production build
5. `docker compose up -d --wait` (Docker Desktop must be running)
6. `pytest tests/integration/` against live Postgres and OpenSearch (the
   tests use throwaway index names)
7. One search-intent WebSocket round-trip against the native backend on
   :8080 (`scripts/smoke_local.sh`; it reuses a healthy `make dev` backend or
   starts and stops its own — never the demo container on :8000)

The full e2e suite has no target on purpose: `bash scripts/smoke_local.sh`
(~90s) runs it against the dev backend when you have touched service wiring or
the WebSocket contract.

`.git/hooks/pre-commit` (installed by `scripts/setup.sh` from
`scripts/pre-commit.sh`) runs black/isort/flake8 on staged `.py` files. If it
blocks a commit: `.venv/bin/black . && .venv/bin/isort .`, re-stage, retry.
Nothing runs on push.

## Tests

`langchain_agent/tests/` — see its [README](../../langchain_agent/tests/README.md).

- `unit/` — pure functions and node logic with mocked I/O; the `bare_agent`
  fixture in `tests/conftest.py` builds an `EcommerceSearchAgent` with every
  connection stubbed. Every code change gets a unit test.
- `integration/` — the admin enrich route, the attribute-mapping store, and
  the enrichment service against live OpenSearch/Postgres.
- `e2e/` — health, origin checks, and the scripted demos over a real
  WebSocket.

A test that asserts on values the test itself wrote, or re-implements
production logic inline, is not coverage; write it against the real function
or not at all.

## Patterns that break things when ignored

- **`PYTHONPATH=.`** for every Python invocation from `langchain_agent/`
  (imports are bare, `from core.config import ...`). The Makefile sets it.
- **State access** — `CustomAgentState` (`core/agent_state.py`) is
  `total=False`; only `messages` is guaranteed. Always `state.get("field",
  default)`. A new node must declare its output fields there or LangGraph
  silently drops them before `astream_events`.
- **`quality_gate_status`** must be set to `"pass"` or `"retry"` on every
  return path of `quality_gate_node`, or a prior turn's `"retry"` leaks
  forward through the Postgres checkpoint. Likewise `hallucination_retry_used`
  is reset at the top of every user turn in `intent_classifier_node`.
- **Every return path of `agent_node` includes `"citations"`** (an empty list
  if none); `observable_agent` relies on the shape.
- **Event parity** — `api/schemas/events.py` and `web/src/types/events.ts`
  change together; `tests/unit/test_frontend_backend_event_parity.py` enforces
  it. Each event's `node` field pins it to a pipeline stage.
- **Sync and async agent node** — `main.py` registers
  `RunnableCallable(self.agent_node, self.aagent_node)`; `agent_node` is the
  body (unit tests call it directly), `aagent_node` runs it in a worker thread
  so a taxonomy re-tag cannot block the WebSocket loop.
- **One render per answer** — citations arrive on `agent_complete`, one frame
  after the last `llm_response_chunk`; `chatStore.completeTurn()` writes text
  and citations in a single `set`. Do not finalize on the chunk handler.
- **Exceptions** — subclass `AgenticHybridSearchError` (`core/exceptions.py`)
  and catch that type, not bare `Exception`.
- **`WATERPROOF_CANONICALS` has zero variants on purpose** — the schema
  evolution demo depends on the gap being real. Do not seed it.
- **Structured logging** — `core/logging_config.py` (structlog); log events,
  not sentences: `logger.info("reranker_done", docs=len(docs))`.

## Style

Python 3.14, black + isort (line length per `pyproject.toml`), flake8, mypy on
`main.py`. TypeScript with ESLint at `--max-warnings 0`. Comments explain why,
never what; no commented-out code, no compatibility shims, no
"kept for later" code — delete it.
