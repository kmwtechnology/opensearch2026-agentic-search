# End-to-End Tests

> Related docs: [repo root README](../../../README.md) ·
> [langchain_agent/README.md](../../README.md) · [tests/README.md](../README.md)

E2E tests exercise a running backend end to end — health, auth, WebSocket
streaming, and pipeline correctness across all 6 intents. They target
`http://localhost:8000` by default (`CLOUD_RUN_URL` env var, despite the
name, just points at whatever backend URL you want to test — set it to a
remote URL if you ever need to point these at something other than local).

Four heavier suites (`test_real_world_scenarios.py`, `test_latency_profiling.py`,
`test_performance_load.py`, `test_stress.py` — user-journey scenarios, latency
profiling, and load/stress testing) were removed 2026-09-15: they arrived as
a bulk copy from a prior repo on this project's first commit, were never
wired into any Makefile target or gate, and don't fit a solo local demo.
Recoverable from git history if a future deployed use case needs them.

These are pytest + httpx + websockets tests (not browser automation).

## Prerequisites

```bash
# Local (default) — start the backend first via ./scripts/start.sh or make dev-api
PYTHONPATH=. pytest tests/e2e/ -v
```

There is no login gate. Same-origin checking (`api/middleware/origin_auth.py:verify_same_origin`)
is the backend's only auth layer, so no credential/env var is required to run
these tests — see `test_deployment_smoke.py`'s `TestAuthentication` for the
current origin-based auth tests. `ADMIN_TOKEN`/`verify_admin_token`
(`api/middleware/admin_auth.py`) is preserved as a standalone utility for
future automation but isn't wired into any route today, so it plays no part
in these tests either. Some older e2e/load-test files still reference a
legacy `API_KEY`/`X-API-Key` scheme that the backend no longer checks; treat
those as stale until updated.

All suites auto-skip individual tests when the target origin rejects the
request (via `_skip_if_origin_blocked`) — useful when CORS rules block
certain paths from your workstation but you still want the rest of the
suite to run.

## Test Files

### `test_deployment_smoke.py` — basic contract

`scripts/smoke_local.sh` (`make smoke` — the project's real local
pre-push smoke gate) narrows this file to one test by default
(`test_search_intent_returns_results`); the full file runs as part of the
broader manual regression run (`bash scripts/smoke_local.sh` with no args).

- `TestDeploymentHealth` — `/api/health` returns 200 + expected fields
- `TestAuthentication` — valid Origin → 200/400, disallowed Origin → 403,
  `/api/health` stays public with no auth at all
- `TestWebSocketConnectivity` — `/api/chat` upgrade, origin checks
- `TestSearchPipeline` — each of the 6 intents (`search`, `comparison`,
  `attribute_filter`, `refinement`, `follow_up`, `summary`) produces a
  valid response with expected event ordering
- `TestCitations` — citation URLs present when reranker score ≥ 0.10,
  Amazon search-by-title URL shape (`/s?k=...`)
- `TestResponseTiming` — end-to-end latency budget assertions

### `test_demo_queries_smoke.py` — DEMO_QUERIES.md regression guard

Drives the three DEMO_QUERIES.md scenarios (α-shift, refinement, query
rewrite) over a real WebSocket, asserting no `agent_error` event at any
point. Added after a crash surfaced in a live demo run (a `HumanMessage`
list-of-content-blocks shape that `main.py`'s extraction sites didn't
handle) — this is the regression guard for that class of bug. Included in
`scripts/smoke_local.sh`'s full (no-args) run alongside
`test_deployment_smoke.py`; not part of the narrowed `make smoke`
default since it isn't `-k`-selected by that target.

## Intent Coverage Matrix

Each intent is exercised by `test_deployment_smoke.py`:

| Intent | Smoke |
| --- | --- |
| `search` | `TestSearchPipeline::test_search_intent` |
| `comparison` | `TestSearchPipeline::test_comparison_intent` |
| `attribute_filter` | `TestSearchPipeline::test_attribute_filter_intent` |
| `refinement` | `TestSearchPipeline::test_refinement_intent` |
| `follow_up` | `TestSearchPipeline::test_follow_up_intent` |
| `summary` | `TestSearchPipeline::test_summary_intent` |

## Quality Gate Coverage

Dedicated assertions for the `< 0.5` retry behavior live in
[`../integration/test_quality_gate_retry.py`](../integration/test_quality_gate_retry.py).
The E2E suite confirms the gate's event shape (`QualityGateEvent` with
`decision`, `max_score`, `alpha_adjusted_value`) reaches the frontend
via WebSocket.

## Success Criteria

The suite guards against regressions in:

- **Correctness** — every intent routes to the right node set and produces a response
- **Latency** — response-time budgets hold (see Latency Targets below)
- **Data integrity** — ESCI index population, checkpoint durability
- **Streaming contract** — token events arrive in order,
  `AgentCompleteEvent` terminates the stream

## Running Selectively

```bash
# Just smoke
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py -v

# All intents
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py::TestSearchPipeline -v

# Skip slow scenarios
PYTHONPATH=. pytest tests/e2e/ -m "not slow" -v
```

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLOUD_RUN_URL` | `http://localhost:8000` | Backend URL under test (the name predates local-only mode; it's just the target URL) |
| `API_KEY` | `test-api-key` | Read by `test_deployment_smoke.py`, sent as `Authorization: Bearer`, which the backend no longer checks (the only auth layer is same-origin checking) |
| `ADMIN_TOKEN` | (unset) | Not currently used by these tests — `verify_admin_token` exists as a preserved-but-unused utility, not wired into any route |
| `TIMEOUT` | 30 | Pytest request timeout in seconds |
| `PYTHONPATH` | (unset) | Must be `.` for pytest module resolution |

## Latency Targets

- Health check: <100 ms
- Search intent: <5 s (excluding network)
- Generation: <10 s (excluding network)
- WebSocket connection: <1 s

## Troubleshooting

**Connection refused** — verify the backend is up (`curl $CLOUD_RUN_URL/api/health`,
default `http://localhost:8000`); start it via `./scripts/start.sh` or `make dev-api`.

**Tests timeout** — bump `TIMEOUT=60`; check `logs/backend.log` for errors.

**WebSocket fails** — confirm `CORS_ORIGINS`/same-origin config matches the
test origin (`api/middleware/origin_auth.py`).

**Data tests fail** — check document count
(`curl $CLOUD_RUN_URL/api/health | grep document_count`); re-ingest via
`scripts/lucille_ingest.sh` if empty, then verify via `GET /api/admin/health`.

## See Also

- [`../README.md`](../README.md) — overall test suite layout and frontend testing
- [`../../README.md`](../../README.md) — application overview
- [`../../../README.md`](../../../README.md) — repo root
