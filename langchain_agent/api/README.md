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
├── middleware/           # Auth, CORS, session handling
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
| `admin.py` | `GET /api/admin/health` · `GET /api/admin/diagnose` · `POST /api/admin/enrich` | Index health, field diagnostics, and the live attribute-taxonomy enrichment flywheel (session or `X-Admin-Token`) |
| `auth.py` | `POST /api/auth/login` · `POST /api/auth/logout` | Session login/logout |

## Middleware (`api/middleware/`)

| File | Purpose |
|------|---------|
| `auth.py` | Holds only `AuthConfigurationError`; no API key validation logic (removed) — do not wire new routes through it |
| `origin_auth.py` | Origin header allow-list enforcement (falls back to `Referer` for same-origin GETs); disallowed Origin always 403s, no further fallback |
| `session_auth.py` | Session cookie verification + admin token fallback for automation |

**Auth strategy:** Two-layer enforcement on protected routes:
1. **Same-origin** (always on) — Origin header whitelist (localhost dev ports + `*.run.app`)
2. **Session or admin token** (opt-in, `REQUIRE_LOGIN=false` by default) — HttpOnly signed session cookie (user login) OR `X-Admin-Token` header (automation). With `REQUIRE_LOGIN` off, the session check is skipped entirely and every same-origin caller is treated as authenticated.

Routes check session first; on `HTTPException`, fall back to token. Constant-time comparison via `hmac.compare_digest`.

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

Required env vars (set in `.env` or deployment secrets):

```bash
LOGIN_PASSWORD              # Shared login password (12+ hex chars)
SESSION_SECRET             # Cookie-signing secret (32+ chars)
SESSION_COOKIE_SECURE      # true (HTTPS) | false (local HTTP, default)
SESSION_MAX_AGE_SECONDS    # Default 86400 (24h)
ADMIN_TOKEN                # Automation token for X-Admin-Token header (32+ chars)
```

Optional:

```bash
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
PYTHONPATH=. pytest tests/unit/test_auth_routes.py -v         # Route auth contracts
PYTHONPATH=. pytest tests/unit/test_admin_routes_auth.py -v    # Admin auth
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
