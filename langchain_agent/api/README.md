# Agentic Hybrid Search — FastAPI Backend

> **Parent**: [langchain_agent/README.md](../README.md)

The FastAPI backend serves WebSocket and REST endpoints for the LangGraph RAG agent.
Entry point: `api/main.py` (lifespan, middleware registration, OpenAPI metadata).

## Architecture

Four layers: **routes** → **middleware** → **schemas** → **services**.

```text
api/
├── main.py               # FastAPI app, lifespan, middleware stack
├── routes/               # HTTP/WebSocket endpoints
├── middleware/           # Origin auth, admin token, CORS, client IP
├── schemas/              # Pydantic event models
└── services/             # Observable agent wrapper
```

## Routes (`api/routes/`)

| File | Endpoints | Purpose |
|------|-----------|---------|
| `chat.py` | `POST /api/chat` (WebSocket) | LangGraph agent stream; emits typed Pydantic events |
| `conversations.py` | `GET /api/conversations`, `GET/DELETE /api/conversations/{thread_id}`, `GET /api/conversations/{thread_id}/observability` | Checkpoint-backed conversation listing/detail/delete + observability snapshot (no REST create/send — that's WebSocket-only) |
| `suggest.py` | `GET /api/suggest?q=...` | Typeahead autocomplete (edge-ngram + spell correction) |
| `health.py` | `GET /api/health` | Index health + document count |
| `admin.py` | `GET /api/admin/health` · `GET /api/admin/diagnose` · `POST /api/admin/enrich` | Index health, field diagnostics, and the live attribute-taxonomy enrichment flywheel (same-origin only) |

## Middleware (`api/middleware/`)

| File | Purpose |
|------|---------|
| `origin_auth.py` | Origin header allow-list enforcement (falls back to `Referer` for same-origin GETs); disallowed Origin always 403s, no further fallback |
| `admin_auth.py` | `verify_admin_token` — X-Admin-Token header check for unattended automation. Not wired into any route today; preserved as a utility. |

**Auth strategy:** Same-origin only — Origin header whitelist (localhost dev ports + `*.run.app`). There is no login gate; do not wire new routes through anything but `verify_same_origin` (plus `verify_admin_token` if you specifically want token-based automation access to that route).

## Schemas (`api/schemas/`)

| File | Purpose |
|------|---------|
| `events.py` | Pydantic event models: `SearchProgressEvent`, `RerankerProgressEvent`, `QualityGateEvent`, `QueryExpansionEvent`, `OpenSearchQueryEvent`, `LLMResponseChunkEvent`, `LLMResponseCorrectedEvent` (emitted by `llm_judge` when auto-correction fires; replaces streamed chat message on the frontend), `EnrichmentTriggeredEvent` (agent called `trigger_enrichment`; carries `attribute_type`/`variant`/`canonical`), `PipelineSummaryEvent`, etc. |
| `admin.py` | `EnrichmentRequest`/`EnrichmentResponse` — request/response contract for `POST /api/admin/enrich` |

**CRITICAL:** `events.py` must stay in sync with `web/src/types/events.ts`. Each event's `type` literal and `node` field must match. Use the pre-flight unit test `test_frontend_backend_event_parity.py` to catch divergence.

## Services (`api/services/`)

| File | Purpose |
|------|---------|
| `observable_agent.py` | Wraps the LangGraph agent and accumulates typed events from the stream; emits `LLMResponseCorrectedEvent` when judge auto-correction fires (before `PipelineSummaryEvent`), then `PipelineSummaryEvent` with per-stage metrics (NDCG/MRR/Recall/Precision or confidence proxy) |

## Configuration

No auth-related env vars are required — the app has no login gate. Optional:

```bash
ADMIN_TOKEN                # Automation token for X-Admin-Token header (32+ chars) -- not wired into any route today
CORS_ORIGINS               # Comma-separated allow-list; empty for local dev
ENABLE_ENRICHMENT_TOOL     # Default false. Gates the agent's trigger_enrichment
                            # tool AND POST /api/admin/enrich (403 when unset).
                            # Both trigger a real Lucille reindex — see
                            # ARCHITECTURE.md's "Enrichment Flywheel" section.
```

## Development

```bash
cd langchain_agent
source .venv/bin/activate
PYTHONPATH=. python -m uvicorn api.main:app --reload
```

Starts on `:8000` with auto-reload on file changes.

## Testing

```bash
PYTHONPATH=. pytest tests/unit/test_admin_routes_auth.py -v    # Admin/origin auth
PYTHONPATH=. pytest tests/integration/test_websocket_integration.py -v  # WS lifecycle
PYTHONPATH=. pytest tests/unit/test_frontend_backend_event_parity.py -v # Event sync
```

## Key Patterns

- **Event parity** — Backend `type: Literal[...]` must match frontend `types/events.ts`
- **State access** — `CustomAgentState` is `total=False`; use `state.get(..., default)`
- **Thread safety** — All shared state protected by `threading.Lock`
- **Timing attacks** — `hmac.compare_digest` for all password/token checks

## References

- [FastAPI docs](https://fastapi.tiangolo.com/)
- [Pydantic v2 docs](https://docs.pydantic.dev/)
- [Session middleware](https://www.starlette.io/middleware/#sessionmiddleware)
- [Origin auth contract test](../../tests/unit/test_origin_auth_contract.py)
