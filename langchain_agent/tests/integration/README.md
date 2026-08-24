# Agentic Hybrid Search — Integration Tests

> **Parent**: [tests/README.md](../README.md)

Multi-component tests requiring live PostgreSQL, OpenSearch, and `GOOGLE_API_KEY`.

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
   make dev-api            # starts on :8000
   ```

3. **Environment:**
   ```bash
   export GOOGLE_API_KEY=<your-key>
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
| `test_conversations.py` | Conversation CRUD, checkpoint-backed state, session behavior | `integration`, `database` |
| `test_websocket_integration.py` | WebSocket lifecycle, auth, event ordering | `integration`, `websocket` |
| `test_suggest.py` | `/api/suggest` typeahead: prefix matches, spell correction, fuzzy fallback | `integration`, `search` |
| `test_admin_reindex.py` | `/api/admin/reindex` background job, status polling, index health | `integration` |
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
- Session/authentication state

### API Contracts

- WebSocket handshake and auth
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

Backend not running or credentials wrong:
```bash
curl http://localhost:8000/api/health
grep LOGIN_PASSWORD .env
```

### `ModuleNotFoundError`

Missing `PYTHONPATH`:
```bash
export PYTHONPATH=.
PYTHONPATH=. pytest tests/integration/test_pipeline_flow.py -v
```

### Google API key error

```bash
echo $GOOGLE_API_KEY
# If empty, re-set it in .env and source it:
set -a && source .env && set +a
```

## Timing

Typical run time: 5–60 seconds depending on which tests are selected.

Long-running tests (marked `@pytest.mark.slow`):
- `test_performance_load.py` — concurrent user load
- `test_stress.py` — 60-second sustained load

For rapid iteration, skip slow tests:
```bash
PYTHONPATH=. pytest tests/integration/ -m "integration and not slow" -v
```

## CI Behavior

The GitHub Actions workflow `.github/workflows/build-deploy.yml` runs integration tests
on every push:
- Ephemeral PostgreSQL + OpenSearch containers (docker compose in CI)
- `GOOGLE_API_KEY` from GitHub secrets
- Pytest timeout: 120 seconds (covers ~2 chat messages)

Note: **`make ci` only runs `pytest --collect-only` on integration tests** to catch import
errors and signature changes. The actual test suite runs live in GitHub Actions. Before pushing,
verify integration tests pass locally:

```bash
docker compose up -d
make dev-api &
PYTHONPATH=. pytest tests/integration/ -v
```

## Difference from Unit Tests

| Aspect | Unit | Integration |
|--------|------|-------------|
| **Services** | Mocked | Real (Postgres + OpenSearch) |
| **API** | Direct function calls | HTTP/WebSocket clients |
| **Speed** | ~1 s total | ~30–60 s depending on tests |
| **Setup** | Automatic | Requires `docker compose up -d` + `make dev-api` |
| **CI** | Collected and run | Collected only; run live in GitHub Actions |

## Difference from E2E Tests

| Aspect | Integration | E2E |
|--------|-------------|-----|
| **Target** | Local backend `:8000` | Deployed Cloud Run |
| **Auth** | Session cookie (UI login) or `X-API-Key` | Session cookie or `X-Admin-Token` |
| **Markers** | `integration` | `e2e` |
| **When** | Locally before push; live on every PR/push | Post-deploy validation + regression |

## References

- [Pytest docs](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Fixtures and conftest.py](../conftest.py)
