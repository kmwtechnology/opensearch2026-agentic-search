# opensearch2026-agentic-search — Test Suite

> Related docs: [repo root README](../../README.md) ·
> [langchain_agent/README.md](../README.md) ·
> [tests/e2e/README.md](e2e/README.md)

Pytest-based tests organized by scope. All commands assume you're in
`langchain_agent/` with `PYTHONPATH=.` (bare imports across the project
require it).

## Layout

```text
tests/
├── unit/                          # Fast, no external services
│   ├── intent/
│   │   └── test_intent_classifier.py
│   ├── evaluator/
│   │   └── test_query_evaluator.py
│   ├── quality_gate/
│   │   └── test_quality_gate.py
│   ├── test_config_validation.py
│   ├── test_llm_streaming_content_blocks.py
│   ├── test_model_compatibility.py
│   ├── test_pipeline_summary_event.py
│   └── test_relevancy_metrics.py
│
├── integration/                   # Multi-component; requires services
│   ├── test_admin_reindex.py
│   ├── test_agent_response.py
│   ├── test_conversations.py
│   ├── test_edge_cases.py
│   ├── test_pipeline_flow.py
│   ├── test_quality_gate_retry.py
│   ├── test_retriever_reranker.py
│   ├── test_suggest.py
│   └── test_websocket_integration.py
│
├── e2e/                           # Against a deployed Cloud Run instance
│   ├── test_cloud_run_deployment.py
│   ├── test_demo_queries_smoke.py
│   ├── test_deployment_data.py
│   ├── test_deployment_smoke.py
│   ├── test_latency_profiling.py
│   ├── test_performance_load.py
│   ├── test_real_world_scenarios.py
│   ├── test_stress.py
│   └── README.md
│
├── conftest.py                    # Shared fixtures + env defaults
├── load_test_phase3.js            # k6 load script
└── README.md                      # This file
```

## Running Tests

### Everything

```bash
PYTHONPATH=. pytest tests/ -v
```

### By scope

```bash
PYTHONPATH=. pytest tests/unit/ -v             # ~0.5 s, no deps
PYTHONPATH=. pytest tests/integration/ -v      # needs Postgres + OpenSearch + GOOGLE_API_KEY
PYTHONPATH=. pytest tests/e2e/ -v              # needs CLOUD_RUN_URL (and API_KEY)
```

### By file or pattern

```bash
PYTHONPATH=. pytest tests/unit/intent/test_intent_classifier.py -v
PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py -v
PYTHONPATH=. pytest tests/ -k "quality_gate"
```

### By marker (`pytest.ini`)

```bash
PYTHONPATH=. pytest tests/ -m unit
PYTHONPATH=. pytest tests/ -m "integration and not slow"
PYTHONPATH=. pytest tests/ -m performance
```

Available markers (kept in sync with `pytest.ini`'s `markers =` list; a
marker not declared there fails collection under `--strict-markers`):
`phase1`, `phase3`, `unit`, `integration`, `e2e`, `slow`, `websocket`,
`performance`, `load`, `stress`, `profile`, `asyncio`, `agent`,
`edge_cases`, `pipeline`, `quality_gate_retry`, `retriever_reranker`,
`requires_real_api`, `evaluator`, `intent`, `quality_gate`.

### Coverage

```bash
PYTHONPATH=. pytest tests/ --cov=. --cov-report=html
open htmlcov/index.html
```

## Test Categories

### Unit (`tests/unit/`)

**Purpose:** component isolation, validation, error paths. No external
services — everything is mocked through `conftest.py`.

| File | Focus |
| --- | --- |
| `intent/test_intent_classifier.py` | 6-intent classification via single LLM call (no keyword fast-path — see #26), confidence thresholds |
| `evaluator/test_query_evaluator.py` | Dynamic α selection, query expansion, fast-path vs LLM-path |
| `quality_gate/test_quality_gate.py` | Retry decision logic, α adjustment bounds, intent-specific thresholds |
| `test_auth_routes.py` | Login/logout/session route behavior |
| `test_admin_routes_auth.py` | Admin route auth contract: session or `X-Admin-Token` |
| `test_config_validation.py` | Required env vars, value ranges, type checks |
| `test_doc_replacer.py` | Replacement scoring, broken-link substitution, cleanup |
| `test_embedding_cache.py` | LRU eviction, TTL, disabled-cache no-op, thread safety |
| `test_exceptions.py` | Custom exception hierarchy, inheritance, error codes |
| `test_health.py` | `/api/health` response shape, degraded-mode reporting |
| `test_intent_classifier_node.py` | LangGraph node wrapper, state mutations |
| `test_link_verifier.py` | URL validation, TTL cache, timeout handling |
| `test_llm_streaming_content_blocks.py` | Streaming event emission, token assembly |
| `test_model_compatibility.py` | Gemini model ID handling, version compatibility |
| `test_origin_auth.py` | Origin/Referer allow-list, WebSocket auth checks, Host-fallback contract (disallowed Origin + `*.run.app` Host MUST 403 — Host fallback only fires when both Origin and Referer are absent) |
| `test_origin_auth_contract.py` | TestClient-based regression test wiring `verify_same_origin` into a FastAPI app; replays the exact production header combos from the 2026-04-29 smoke failure |
| `test_pipeline_nodes.py` | Node input/output contracts across the pipeline |
| `test_pipeline_summary_event.py` | `_build_pipeline_summary` accumulation, ground-truth vs. confidence-proxy fallback, latency table assembly |
| `test_relevancy_metrics.py` | NDCG@k / MRR / Recall@k / Precision@k, `compute_stage_metrics`, `confidence_from_scores`, `count_rank_changes`, `latency_cost_benefit` (43 tests, no NumPy) |
| `test_reranker.py` | `GeminiReranker` scoring, Pydantic validation, partial-JSON fallback |
| `test_retry_utils.py` | Retry decorators, transient-error detection, max-attempts behaviour |
| `test_routing_functions.py` | LangGraph edge routing logic |
| `test_search_optimizations.py` | BM25 synonym expansion, fuzzy, phrase-boost, phonetic config |
| `test_vector_store.py` | `OpenSearchVectorStore` hybrid search, RRF fusion, facets, collapse |
| `test_admin_reindex.py` | `/api/admin/reindex` background job, status polling, index health |
| `test_e2e_ws_url_routes.py` | Pre-flight guard: every `/ws/*` URL referenced in `tests/e2e/` must resolve to a registered FastAPI WebSocket route — catches path/query-style mismatches locally before they reach Cloud Run |
| `test_e2e_event_types.py` | Pre-flight guard: every `event["type"] == "..."` literal in `tests/e2e/` must be declared in `api/schemas/events.py`; flags use of `event["event_type"]` (wire field is `type`) |
| `test_e2e_payload_shapes.py` | Pre-flight guard: every `json.dumps({...})` WS payload in `tests/e2e/` must match the `chat_message` / `stop_execution` contract enforced by `api/routes/chat.py` (catches stale `{"query":, "session_id":}` shapes) |
| `test_frontend_backend_event_parity.py` | Pre-flight guard: every backend `type: Literal[...]` in `events.py` must appear in `web/src/types/events.ts`; per-event `node:` literals must match between backend and frontend; `AgentEvent` union cannot reference Python builtins |
| `test_smoke_test_budget.py` | Pre-flight guard: AST-walks each smoke / cloud-run / data e2e test, counts `chat_message` sends, computes a worst-case Cloud Run budget (`SETUP_OVERHEAD_S=5` + `PER_CHAT_MESSAGE_BUDGET_S=25` × sends), and asserts the workflow's `pytest --timeout=N` covers it. Also asserts inner `asyncio.wait_for(timeout=...)` ≤ workflow `--timeout` and `WEBSOCKET_TIMEOUT` ≥ per-message budget. Tighten constants only if you have new wall-clock data — they reflect production observation, not aspirational SLOs. |

**Run time:** ~0.9 s. ~612 unit tests total. **Best for:** TDD,
pre-commit, CI fast lane.

### Integration (`tests/integration/`)

**Purpose:** multi-component flows with real or near-real services. See [tests/integration/README.md](integration/README.md) for detailed guide.

| File | Focus |
| --- | --- |
| `test_pipeline_flow.py` | Full RAG pipeline: classifier → evaluator → retriever → reranker → quality gate → agent |
| `test_retriever_reranker.py` | Hybrid search + RRF fusion + reranker scoring |
| `test_quality_gate_retry.py` | Retry triggered when max reranker score < 0.5, α ±0.3 adjustment |
| `test_agent_response.py` | Response generation, citation formatting, Amazon URL construction |
| `test_conversations.py` | Conversation CRUD, checkpoint-backed state, session behavior |
| `test_websocket_integration.py` | WebSocket lifecycle, auth, event ordering |
| `test_suggest.py` | `/api/suggest` typeahead: prefix matches, spell correction (Levenshtein + ratio), fuzzy distance-1 fallback, corpus-token and prefix guards |
| `test_admin_reindex.py` | `/api/admin/reindex` background job, `/api/admin/reindex/status` polling, `/api/admin/health` index status |
| `test_edge_cases.py` | Empty retrievals, malformed input, low-confidence intents |

**Run time:** ~5–60 s. **Requires:** PostgreSQL + OpenSearch running
(`docker compose up -d` from repo root) and `GOOGLE_API_KEY` set.

**CI note:** `make ci` only runs `pytest --collect-only` on integration tests. Always run the actual
test suite locally after middleware/WebSocket changes before pushing.

### E2E (`tests/e2e/`)

**Purpose:** smoke and regression testing against a deployed Cloud Run
instance. See [`tests/e2e/README.md`](e2e/README.md) for scenarios and
required environment.

| File | Focus |
| --- | --- |
| `test_deployment_smoke.py` | Health check, auth, basic round-trip (18 tests) |
| `test_cloud_run_deployment.py` | Cold start, scaling, service metadata, rate-limit ordering (17 tests) |
| `test_deployment_data.py` | Product index population, sample queries, checkpoint persistence (10 tests) |
| `test_demo_queries_smoke.py` | Demo query regression checks against deployed data |
| `test_real_world_scenarios.py` | All 6 intents against live data with realistic queries |
| `test_latency_profiling.py` | Per-node latency breakdown |
| `test_performance_load.py` | Sustained load, throughput, p95/p99 |
| `test_stress.py` | Concurrent users, failure modes under pressure |

> **2026-04-29:** the smoke / cloud-run / data trio (45 tests) all
> execute on every push to `main` against the live Cloud Run deploy.
> Until 2026-04-29 the cloud-run + data files silently skipped 12
> tests because they used the legacy `websockets.client.connect`
> without an Origin header — both files now use
> `websockets.asyncio.client` + `additional_headers={"Origin":
> ORIGIN_HEADER}` to match the smoke pattern. **Always run e2e files
> against a real backend before pushing** — `make ci` only does
> `--collect-only` on `tests/e2e/`.

**Run time:** ~10 s – several minutes (load/stress). **Requires:** a
backend URL and an `API_KEY`. Two common configurations:

```bash
# Against the deployed Cloud Run service:
export CLOUD_RUN_URL="https://agentic-hybrid-search-375500751528.us-central1.run.app"
export API_KEY="$(gcloud secrets versions access latest \
  --secret=agentic-hybrid-search-api-key \
  --project=gen-lang-client-0250737934)"
PYTHONPATH=. pytest tests/e2e/ -v

# Against a local backend (faster iteration):
docker compose up -d                           # PostgreSQL + OpenSearch
make dev-api                                   # backend on :8000
export CLOUD_RUN_URL="http://localhost:8000"   # in dev allow-list
export API_KEY="$(grep '^API_KEY=' .env | cut -d= -f2)"
PYTHONPATH=. pytest tests/e2e/ -v
```

## Fixtures (`conftest.py`)

Shared setup injects sensible defaults for test runs:

```python
os.environ.setdefault("ENABLE_RERANKING", "true")
os.environ.setdefault("ENABLE_QUALITY_GATE", "true")
os.environ.setdefault("QUALITY_GATE_THRESHOLD", "0.50")
```

The repo root is added to `sys.path` so bare imports (`from config import ...`)
resolve inside tests without `PYTHONPATH=.` — but setting `PYTHONPATH=.` is
still recommended for consistency with the rest of the project.

## Setup

### Local

```bash
cd langchain_agent
pip install -r requirements-dev.txt
./scripts/setup.sh           # one-time: Docker + venv + DB + ingestion
./scripts/start.sh           # start services
PYTHONPATH=. pytest tests/ -v
```

### CI (GitHub Actions)

`.github/workflows/build-deploy.yml` runs on PRs and pushes — unit +
integration tests (ephemeral Postgres + OpenSearch), strict lint
(black/isort/flake8/mypy), Docker build, and (on `main`) push + Cloud Run
deploy + smoke test. Runners use Node.js 24.

`.github/workflows/reindex.yml` is a separate manual-dispatch workflow
that calls `GET /api/admin/reindex` against the deployed Cloud Run
service — not invoked by the regular test/deploy flow.

## Common Issues

### `ModuleNotFoundError: No module named 'config'` (or similar)

```bash
PYTHONPATH=. pytest tests/
```

### Tests hang or time out

Services may not be up. Verify:

```bash
docker compose ps
curl http://localhost:9200/_cluster/health
PGPASSWORD=postgres psql -h localhost -U postgres -d langchain_agent -c 'SELECT 1;'
```

Pytest has a 30-second default timeout (`pytest.ini`). Mark longer tests
with `@pytest.mark.slow` or raise the timeout via `--timeout=N`.

### Integration tests skipped

They assert against running services — start them via
`docker compose up -d` from the repo root plus `./scripts/start.sh` for
the backend if the test exercises the HTTP/WebSocket layer.

### E2E tests failing with 401

Check `API_KEY` matches what's stored in Secret Manager for the deployed
service, and that `CLOUD_RUN_URL` has the correct scheme + host.

## Performance Testing

The performance suite lives in `tests/e2e/` and is split across four files:

| File | Markers | Focus |
| --- | --- | --- |
| `test_performance_load.py` | `load`, `performance` | Concurrent users (1/5/10/20), p50/p95/p99 latency, throughput, regression detection |
| `test_real_world_scenarios.py` | `performance` | 9 user-journey scenarios (shopper, expert, content creator, support, mobile, power, accessibility, cold start, network jitter) |
| `test_stress.py` | `stress`, `slow` | Sustained 50-user/60s load, 100-req burst, connection pool, error recovery, leak detection |
| `test_latency_profiling.py` | `profile` | Per-stage latency (embedding, vector, rerank, full pipeline), α comparison, cache effectiveness |

```bash
PYTHONPATH=. pytest -m load -v
PYTHONPATH=. pytest -m stress -v
PYTHONPATH=. pytest -m profile -v
PYTHONPATH=. pytest tests/e2e/test_real_world_scenarios.py -v
```

Results land in `tests/performance_results/`, `tests/stress_results/`,
`tests/profiling_results/`. Baselines (`baseline.json`) are committed for
regression comparison; >10% latency regression fails CI.

Key thresholds: p50 <5s single-user, error rate <10% (1u) → <25% (20u),
sustained-50u success >70%, no detectable memory leak. Per-stage budgets:
embed <2s, vector <3s, rerank <5s, full pipeline <15s.

The k6 script (`load_test_phase3.js`) can be run against localhost or a
deployed instance for HTTP-level load testing outside pytest.

## Frontend Tests (Vitest)

Frontend tests live alongside the React source in
`langchain_agent/web/src/**/__tests__/` and run via Vitest:

```bash
cd langchain_agent/web
npm run test            # 101 tests
npm run test -- --watch
npm run test -- --coverage
```

Coverage spans Zustand stores (`chatStore`, `observabilityStore`),
WebSocket hooks (`useWebSocket`, `useRecentSearches`), and observability
components — `IntentClassifierDetails`, `IntentDisplay`,
`PipelineSummaryCard`, `SearchOptimizationDetails`,
`TypeaheadSuggestions`. Tests verify: intent badge colors (search/blue,
attribute_filter/purple, follow_up/cyan, summary/purple), confidence
visualization (green ≥0.7 / yellow <0.7), low-confidence clarification
warning, query expansion display for follow-up intents, boundary cases
(0.0 / 0.7 / 1.0 confidence), and event-type contracts matching
`api/schemas/events.py`.

## Writing New Tests

### Unit

```python
# tests/unit/my_module/test_my_thing.py
import pytest
from my_module import MyThing

class TestMyThing:
    def test_valid(self):
        assert MyThing(42).value == 42

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            MyThing(-1)
```

### Integration

```python
# tests/integration/test_my_flow.py
import pytest

@pytest.mark.asyncio
@pytest.mark.integration
class TestMyFlow:
    async def test_end_to_end(self, compiled_graph):
        result = await compiled_graph.ainvoke({"messages": [("user", "hi")]})
        assert result["messages"]
```

Mark tests with the appropriate marker(s) so scope-based runs pick them up.

## References

- [pytest docs](https://docs.pytest.org/)
- [pytest fixtures](https://docs.pytest.org/en/stable/how-to/fixtures.html)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [pytest markers](https://docs.pytest.org/en/stable/example/markers.html)
