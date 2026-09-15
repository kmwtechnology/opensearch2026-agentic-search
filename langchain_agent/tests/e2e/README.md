# End-to-End Tests

> Related docs: [repo root README](../../../README.md) ·
> [langchain_agent/README.md](../../README.md) · [tests/README.md](../README.md)

E2E tests exercise a running backend end to end — health, auth, WebSocket
streaming, pipeline correctness across all 6 intents, ESCI data presence,
latency profile, and behavior under load. They target `http://localhost:8000`
by default (`CLOUD_RUN_URL` env var, despite the name, just points at
whatever backend URL you want to test — set it to a remote URL if you ever
need to point these at something other than local).

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

This is the file `scripts/smoke_local.sh` runs (`make smoke-local` /
`smoke-local-quick`) — the project's real local pre-push smoke gate.

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

### `test_real_world_scenarios.py` — user journeys

Scenario classes covering realistic personas end-to-end:

- `TestEcommerceShopperScenario` — search → compare → refine → follow-up
- `TestProductExpertScenario` — deep attribute-filter queries, technical language
- `TestSupportAgentScenario` — summary intent, conversation history
- `TestMobileShopperScenario` — short queries, high follow-up rate
- `TestAccessibilityScenario` — screen-reader-friendly output, alt text in citations
- `TestPowerUserScenario` — rapid multi-turn conversations

Plus `TestColdStartPerformance` and `TestStreamingNetworkConditions` for
first-request latency and flaky-network behavior.

### `test_latency_profiling.py` — per-stage latency

- `TestStageLatencies` — budgets per node (classifier, evaluator,
  retriever, reranker, quality gate, agent)
- `TestAlphaComparison` — fast-path α vs LLM-path α latency delta
- `TestFullPipelineProfile` — end-to-end breakdown summed from observability events
- `TestMemoryProfileing` — RSS growth under repeated requests
- `TestCacheEffectiveness` — embedding cache hit rate after warm-up

### `test_performance_load.py` — throughput

- `TestLoadPerformance` — sustained RPS, p50/p95/p99
- `TestSearchLatencyProfiles` — per-intent latency distributions
- `TestRerankerPerformance` — reranker time as a function of candidate count
- `TestMemoryUsage` — heap growth under load
- `TestRegressionDetection` — compares against a checked-in baseline

Exports JSON (`performance_report.json`) for trend tracking.

### `test_stress.py` — failure modes under pressure

- `TestSustainedLoad` — long-duration sustained traffic
- `TestBurstLoad` — spike traffic handling
- `TestConnectionPooling` — WebSocket pool behavior
- `TestErrorRecovery` — recovery from transient upstream errors
  (OpenSearch, Gemini 429s)
- `TestResourceLeakDetection` — file descriptors, memory, connections over time

Exports `stress_report.json`.

## Intent Coverage Matrix

Each intent is exercised by at least one smoke test and one scenario test:

| Intent | Smoke | Scenario |
| --- | --- | --- |
| `search` | `TestSearchPipeline::test_search_intent` | `TestEcommerceShopperScenario` |
| `comparison` | `TestSearchPipeline::test_comparison_intent` | `TestProductExpertScenario` |
| `attribute_filter` | `TestSearchPipeline::test_attribute_filter_intent` | `TestEcommerceShopperScenario` |
| `refinement` | `TestSearchPipeline::test_refinement_intent` | `TestEcommerceShopperScenario` |
| `follow_up` | `TestSearchPipeline::test_follow_up_intent` | `TestMobileShopperScenario` |
| `summary` | `TestSearchPipeline::test_summary_intent` | `TestSupportAgentScenario` |

## Quality Gate Coverage

Dedicated assertions for the `< 0.5` retry behavior live in
[`../integration/test_quality_gate_retry.py`](../integration/test_quality_gate_retry.py).
The E2E suite confirms the gate's event shape (`QualityGateEvent` with
`decision`, `max_score`, `alpha_adjusted_value`) reaches the frontend
via WebSocket.

## Success Criteria

The suite guards against regressions in:

- **Correctness** — every intent routes to the right node set and produces a response
- **Latency** — per-node budgets hold against the checked-in baselines
- **Reliability** — ≥ 99% success rate at sustained target RPS
- **Data integrity** — ESCI index population, checkpoint durability
- **Streaming contract** — token events arrive in order,
  `AgentCompleteEvent` terminates the stream

## Running Selectively

```bash
# Just smoke
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py -v

# All intents, no load
PYTHONPATH=. pytest tests/e2e/test_deployment_smoke.py::TestSearchPipeline -v

# Load/stress only
PYTHONPATH=. pytest tests/e2e/ -m "load or stress" -v

# Skip slow scenarios
PYTHONPATH=. pytest tests/e2e/ -m "not slow" -v
```

## Reports

Load and stress runs emit JSON:

- `performance_report.json` — `test_performance_load.py`
- `stress_report.json` — `test_stress.py`

Commit baselines you care about next to the suite so
`TestRegressionDetection` can compare future runs against them.

## Bash Smoke Test (`scripts/smoke_test.sh`)

curl-based smoke test, no pytest required, works against any URL:

```bash
./scripts/smoke_test.sh http://localhost:8000
```

Validates connectivity, `/api/health`, PostgreSQL + OpenSearch status,
and response time. Color-coded output; non-zero exit on any failure. Note:
the script's `API_KEY`/`Authorization: Bearer` auth check is legacy — the
backend has no login gate at all and recognizes only same-origin checking
(`Origin`/`Referer`), so that particular check is currently a no-op.

## Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `CLOUD_RUN_URL` | `http://localhost:8000` | Backend URL under test (the name predates local-only mode; it's just the target URL) |
| `API_KEY` | `test-api-key` | Legacy `smoke_test.sh` var; sent as `Authorization: Bearer`, which the backend no longer checks (the only auth layer is same-origin checking) |
| `ADMIN_TOKEN` | (unset) | Not currently used by these tests — `verify_admin_token` exists as a preserved-but-unused utility, not wired into any route |
| `TIMEOUT` | 30 (pytest), 10 (curl) | Request timeout in seconds |
| `PYTHONPATH` | (unset) | Must be `.` for pytest module resolution |

## Latency Targets

- Health check: <100 ms
- Search intent: <5 s (excluding network)
- Generation: <10 s (excluding network)
- WebSocket connection: <1 s
- Concurrent: 5+ simultaneous; 20-request burst with >70% success

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

- [`../README.md`](../README.md) — overall test suite layout,
  performance + frontend testing
- [`../../README.md`](../../README.md) — application overview
- [`../../../README.md`](../../../README.md) — repo root
