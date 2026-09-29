# Tests

> **Parent**: [../README.md](../README.md)

Run from `langchain_agent/` with `PYTHONPATH=.` (bare imports). The suites
exercise production code only — a test that asserts on a literal it wrote
itself is cruft, not coverage.

| Suite | Needs | Run by `make ci`? |
|---|---|---|
| `tests/unit/` | nothing (mocks, `bare_agent`) | yes |
| `tests/integration/` | live PostgreSQL + OpenSearch (`docker compose up -d`); Ollama for the enrichment classifier | yes — `make ci` brings Docker up first. They create and drop their own throwaway indices |
| `tests/e2e/` | a running backend on :8080 (`make dev`, or `smoke_local.sh` starts one) | one test — the search-intent smoke round-trip. `bash scripts/smoke_local.sh` runs the rest |
| `web/src/**/__tests__/` | Node | yes (`vitest`) |

```bash
PYTHONPATH=. .venv/bin/pytest tests/unit/ -q                 # while coding
PYTHONPATH=. .venv/bin/pytest tests/unit/test_foo.py::test_bar -v
PYTHONPATH=. .venv/bin/pytest tests/integration/ -q          # Docker up
bash scripts/smoke_local.sh                                 # full e2e
bash scripts/smoke_local.sh -k test_search_intent_returns_results
```

Markers (`pytest.ini`, `--strict-markers`): `unit`, `integration`, `e2e`,
`slow`, `phase1`. Only `e2e` and `slow` drive selection (`smoke_local.sh`
runs `-m "e2e and slow"`); the others are labels. `timeout = 30` per test.

E2E tests read `DEPLOYMENT_URL` (default `http://localhost:8080`, the native
backend — the working tree). Don't point them at :8000: that is the demo image,
frozen at the last `make dev`. They send `Origin: <DEPLOYMENT_URL>`, which is
all the auth there is.

## Fixtures

`tests/conftest.py::bare_agent` builds an `EcommerceSearchAgent` via
`__new__` with every I/O attribute set to `None` or a `MagicMock`, so node and
helper methods can be unit-tested without PostgreSQL, OpenSearch, or Ollama —
override the attribute a test needs (`agent.alpha_estimator_llm = MagicMock(...)`).
`tests/e2e/conftest.py` provides `auth_ws_headers()` / `auth_rest_headers()`
(the `Origin` header).

## What guards what

| Invariant | Test |
|---|---|
| Graph routing (`_route_after_intent`, quality-gate route, summary route); `hallucination_retry_used` reset every turn | `unit/test_routing_functions.py` |
| Quality gate pass / retry / accept-after-retry, ±0.3 alpha, per-intent thresholds, no stale `"retry"` leaking through checkpoints | `unit/test_pipeline_nodes.py` |
| Intent classifier extraction and the refinement → search downgrade | `unit/test_intent_classifier_node.py` |
| Event contract: `api/schemas/events.py` ↔ `web/src/types/events.ts`, both directions, per-class `node` literals | `unit/test_frontend_backend_event_parity.py` (and `web/src/hooks/__tests__/useWebSocket.test.ts` on the client side) |
| Same-origin auth: allow-list, Referer fallback, Host can't override a bad Origin, WebSocket close 4003 | `unit/test_origin_auth.py`, `unit/test_origin_auth_contract.py`; live in `e2e/test_deployment_smoke.py::TestAuthentication` |
| Scoped re-tag detects exactly what the original tagger did (longest phrase, secondary slot, ASCII `\b`) and touches only candidate products | `unit/test_scoped_retag.py`; end to end in `integration/test_enrichment_service.py` |
| `WATERPROOF_CANONICALS["waterproof"]` stays empty (the schema-evolution demo depends on it) | `unit/test_attribute_discovery.py` |
| `_coerce` rejects booleans from the LLM (a literal `False` used to become a truthy hard filter) | `unit/test_extract_attributes_waterproof.py` |
| Enrichment lifecycle: `started` before the re-tag, one terminal event, value-judge gate, judge skips enrichment turns | `unit/test_enrichment_lifecycle_events.py`, `unit/test_try_enrichment_tool.py`, `unit/test_judge_skips_enrichment_turn.py`; route contract in `integration/test_admin_enrich_route.py` |
| Citations: Amazon search-by-title URL construction; `agent_complete.citations` shape `{label, url, asin, image_url}` | `unit/test_agent_link_handling.py`; live in `e2e/test_deployment_smoke.py::TestCitations` |
| Reranker rescale ceiling stays below the quality-gate thresholds | `unit/test_reranker.py` |
| Hybrid search DSL, RRF routing, query-term truncation | `unit/test_vector_store.py`, `unit/test_issue_85_maxclausecount.py` |
| Judge categories and retry eligibility | `unit/test_judge_categories.py` |
| Pipeline summary and the confidence proxy | `unit/test_pipeline_summary_event.py`, `unit/test_confidence_proxy.py` |
| Attribute-mapping store read-after-write, case-insensitivity, cache invalidation | `integration/test_attribute_mapping_store.py` |
| The three scripted demos in `web/src/demos/registry.ts` run end to end without `agent_error` | `e2e/test_demo_queries_smoke.py::TestScriptedDemos` |
| Every runtime package has a `COPY` line in the Dockerfile | `unit/test_dockerfile_package_copy.py` |

## Writing a test

Put it next to the code it guards, import the production symbol, and assert
on its behavior. Unit tests take `bare_agent` and mock the one collaborator
they need; integration tests monkeypatch `INDEX_NAME` to a throwaway index
and clean up in the fixture; e2e tests use a fresh `thread_id` per test.
