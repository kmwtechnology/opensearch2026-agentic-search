# Agentic Hybrid Search — Integration Tests

> **Parent**: [tests/README.md](../README.md)

Multi-component tests requiring live PostgreSQL, OpenSearch, and a local Ollama with the configured models pulled.

## Running

### All integration tests

```bash
PYTHONPATH=. pytest tests/integration/ -v
```

### Specific file

```bash
PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py -v
```

### By pattern

```bash
PYTHONPATH=. pytest tests/integration/ -k "websocket" -v
```

### By marker

```bash
PYTHONPATH=. pytest tests/integration/ -m "integration and not slow" -v
```

## Prerequisites

1. **Services running:**
   ```bash
   docker compose up -d    # from repo root
   ```

2. **Backend running (for WebSocket tests):**
   ```bash
   make dev                # backend on :8000 (backgrounded; logs/backend.log)
   ```

3. **Ollama:**
   ```bash
   ollama pull qwen3.6:35b-a3b-q4_K_M && ollama pull nomic-embed-text
   ```

4. **PYTHONPATH:**
   ```bash
   export PYTHONPATH=.
   ```

## Test Files

| File | Focus | Markers |
|------|-------|---------|
| `test_pipeline_flow.py` | Full RAG pipeline: classifier → evaluator → retriever → reranker → quality gate → agent | `integration`, `search` |
| `test_retriever_reranker.py` | Hybrid search + RRF fusion + reranker scoring | `integration`, `search`, `rerank` |
| `test_quality_gate_retry.py` | Retry triggered when max reranker score < 0.5, α ±0.3 adjustment | `integration`, `search`, `rerank` |
| `test_agent_response.py` | Response generation, citation formatting, Amazon URL construction | `integration`, `search` |
| `test_conversations.py` | Conversation CRUD, checkpoint-backed state, same-origin-only auth (no session/login gate) | `integration`, `database` |
| `test_websocket_integration.py` | WebSocket lifecycle, same-origin auth, event ordering | `integration`, `websocket` |
| `test_suggest.py` | `/api/suggest` typeahead: prefix matches, spell correction, fuzzy fallback | `integration`, `search` |
| `test_admin_enrich_route.py` | `POST /api/admin/enrich` request/response contract, `ENABLE_ENRICHMENT_TOOL` gating | `integration` |
| `test_edge_cases.py` | Empty retrievals, malformed input, low-confidence intents | `integration` |

## What's Tested

### Pipeline Flow

- Intent classification (all 6 intents)
- Query expansion (pronoun/comparative resolution)
- Dynamic α selection (fast-path vs LLM-path)
- Retriever (hybrid search, RRF fusion)
- Reranker (scoring, top-K selection)
- Quality gate (retry on low score, α adjustment)
- Agent response (generation, citations)
- LLM Judge (faithfulness scoring, hallucination detection)

### State Management

- Conversation CRUD (create, read, update)
- LangGraph checkpoint persistence
- Same-origin auth state (no session/login gate exists)

### API Contracts

- WebSocket handshake and same-origin auth
- Event emission ordering
- Typeahead ranking and spell correction
- Admin reindex status polling

### Edge Cases

- Empty retrieval (no matching products)
- Malformed queries
- Low-confidence intent classification
- Long conversation history

## Common Issues

### Test hangs

Services not running:
```bash
docker compose ps
curl http://localhost:9200/_cluster/health
PGPASSWORD=postgres psql -h localhost -U postgres -d langchain_agent -c 'SELECT 1;'
```

### WebSocket tests fail with auth error

Backend not running, or the request's `Origin` header doesn't match the allow-list
(there is no login gate — same-origin checking is the only auth layer):
```bash
curl http://localhost:8000/api/health
grep -A5 "def get_allowed_origins" ../../api/middleware/origin_auth.py
```

### `ModuleNotFoundError`

Missing `PYTHONPATH`:
```bash
export PYTHONPATH=.
PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py -v
```

### Ollama not reachable / model not pulled

```bash
curl -s http://localhost:11434/api/tags
# If Ollama isn't running, start it (or the Ollama app), then:
ollama pull qwen3.6:35b-a3b-q4_K_M && ollama pull nomic-embed-text
```

## Timing

Typical run time: 5–60 seconds depending on which tests are selected.

Long-running tests (marked `@pytest.mark.slow`):
- `test_enrichment_service.py::TestRealReindexEndToEnd` — triggers a real
  scoped re-tag (`pipeline/scoped_retag.py`) against the live product index

For rapid iteration, skip slow tests:
```bash
PYTHONPATH=. pytest tests/integration/ -m "integration and not slow" -v
```

## CI Behavior

There is no GitHub Actions CI (issue #113) — **`make ci` only runs
`pytest --collect-only` on integration tests**, to catch import errors and
signature changes without needing live services. The actual test suite
must be run locally before pushing:

```bash
docker compose up -d
make dev
PYTHONPATH=. pytest tests/integration/ -v
```

Tests needing seeded taxonomy data point the mapping store at a throwaway index
via `monkeypatch.setattr(store_module, "INDEX_NAME", ...)` and seed it themselves,
so they run without touching the real corpus. See `test_attribute_mapping_store.py`.

## Difference from Unit Tests

| Aspect | Unit | Integration |
|--------|------|-------------|
| **Services** | Mocked | Real (Postgres + OpenSearch) |
| **API** | Direct function calls | HTTP/WebSocket clients |
| **Speed** | ~1 s total | ~30–60 s depending on tests |
| **Setup** | Automatic | Requires `make dev` |
| **CI** | Collected and run | Collected only; run live locally before push |

## Difference from E2E Tests

| Aspect | Integration | E2E |
|--------|-------------|-----|
| **Target** | Local backend `:8000` | Local backend `:8000` by default (or a remote URL via `DEPLOYMENT_URL`) |
| **Auth** | Same-origin checking only (no login gate) | Same-origin checking only (no login gate) |
| **Markers** | `integration` | `e2e` |
| **When** | Locally before push | Locally before push (smoke/regression coverage) |

## References

- [Pytest docs](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Fixtures and conftest.py](../conftest.py)
