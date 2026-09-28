# API Reference

> **Parent**: [../README.md](../README.md) · Event schema: [schemas/events.py](schemas/events.py) mirrored by [../web/src/types/events.ts](../web/src/types/events.ts)

FastAPI app in `main.py`; routes under `routes/`, Pydantic models under
`schemas/`, the LangGraph streaming wrapper in `services/observable_agent.py`,
auth in `middleware/origin_auth.py`. Interactive docs: `/swagger` (the default
`/docs` is disabled).

Base URLs: `http://localhost:8080` (native `make dev` backend, always the
current tree) and `http://localhost:8000` (the demo container, frozen at the
last `make dev`). Examples below use :8080.

## Authentication

Same-origin checking is the only auth layer. There is no login, no session
cookie, no API key, no admin token.

| Route | Auth |
|---|---|
| `GET /api/health`, `GET /api/suggest`, `GET /api/config`, `/swagger` | Public |
| `POST /api/chat`, `WS /ws/chat`, `GET/POST /api/admin/*` | `Origin` (or `Referer`) must be on the allow-list |

The allow-list (`middleware/origin_auth.py::get_allowed_origins`) is
`localhost` / `127.0.0.1` on ports 5173, 5174, 3000, 8000, 8080. A disallowed
origin gets `403` on REST and close code `4003` on the WebSocket. Browser
clients on :5173 (Vite proxy) or :8000 (same origin) satisfy this
automatically; scripts must send the header:

```bash
curl -H 'Origin: http://localhost:8080' http://localhost:8080/api/admin/health
```

`POST /api/chat` and the WebSocket are rate limited at 20 requests/minute per
client IP (`slowapi`, `RATE_LIMIT_CHAT` in `core/config.py`); the limit answers
`429`.

## Routes

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Dependency probe: `status` is `ok` when PostgreSQL and Ollama are healthy, else `degraded` (always 200) |
| GET | `/api/suggest?q=&limit=` | Typeahead over product titles and brands with spell correction |
| GET | `/api/config` | `{"apiUrl": ...}` for the UI; empty means "same origin" |
| POST | `/api/chat` | Non-streaming chat; returns the final answer and citations |
| WS | `/ws/chat?thread_id=` | Streaming chat with the full pipeline event stream |
| GET | `/api/admin/health` | Product index existence and document count |
| GET | `/api/admin/diagnose?q=` | Field-level hit counts for a query; detects a stale mapping |
| POST | `/api/admin/enrich` | Add or correct a taxonomy mapping and run the scoped re-tag |
| POST | `/api/admin/demo-reset` | Re-arm both self-consuming demos (mutates the index) |

### `GET /api/health`

```json
{"status": "ok", "version": "1.0.0", "postgres": true, "llm": true,
 "vector_store": true, "document_count": 158637}
```

`llm` is true when Ollama answers and every configured model is pulled;
otherwise `llm_error` explains which. `vector_store` is true when the index
has documents.

### `GET /api/suggest`

`q` is 1–100 characters, `limit` 1–20 (default 8). Edge-ngram prefix matching
on `title_suggest` and `brand_suggest`; a fuzzy fallback catches distance-1
typos when the prefix query is empty; fails open (empty list, 200) if
OpenSearch is unreachable.

```bash
curl 'http://localhost:8080/api/suggest?q=nikey&limit=3'
```

```json
{"suggestions": [{"title": "Nike Air Zoom", "brand": "Nike", "score": 12.4,
                  "highlight": ["<em>Nike</em> Air Zoom"]}],
 "spell_correction": {"title": "nike", "brand": null, "score": null, "highlight": null}}
```

### `POST /api/chat`

Request: `{"message": "...", "thread_id": "conversation_ab12cd34"}` (`thread_id`
optional — one is generated; it must start with a letter). Response:
`thread_id`, `response`, `duration_ms`, and `citations`, each
`{label, url, asin?, image_url?}` where `url` is an Amazon search by title
(`https://www.amazon.com/s?k=...`). Use the WebSocket for anything
interactive — this endpoint has no streaming and no observability events.

### `POST /api/admin/enrich`

Requires `ENABLE_ENRICHMENT_TOOL=true` (else `403`). Body:
`{"attribute_type": "color" | "waterproof", "variant": "tan", "canonical": "brown"}`;
`canonical` is optional — omit it to let dictionary classification resolve
the term. This is the same mechanism the agent's `trigger_enrichment` tool
uses: write the mapping, re-tag only products whose text mentions the
variant. A term that can't be classified or is already mapped returns
`success: false` with a `reason`, still `200`.

```json
{"success": true, "attribute_type": "color", "variant": "tan", "canonical": "brown",
 "reason": null, "reindex_triggered": true, "reindex_success": true,
 "docs_processed": 679, "duration_seconds": 0.9, "reindex_mode": "scoped",
 "reindex_error": null}
```

### `POST /api/admin/demo-reset`

Restores the tan→yellow mis-tag for the correction demo and clears any learned
waterproof mappings for the schema-evolution demo. The UI's Restart button
calls it; so does `scripts/reset_demo_taxonomy.sh`.

## WebSocket protocol

Connect to `ws://localhost:8080/ws/chat?thread_id=<id>` with an allow-listed
`Origin`. The server replies with `connection_established` carrying the
`thread_id` (generated if you omitted it) and `existing_messages` for that
thread. Conversation state is checkpointed in PostgreSQL per `thread_id`;
reconnecting with the same id continues the conversation.

Inbound messages (`routes/chat.py`):

```json
{"type": "chat_message", "message": "Show me tan boots", "thread_id": "conversation_ab12cd34",
 "optimizations": {"hybrid": true, "reranking": true, "llm_judge": true}}
{"type": "stop_execution", "thread_id": "conversation_ab12cd34"}
```

`optimizations` is optional; unknown keys are dropped. The nine recognized
flags are `hybrid`, `fuzzy`, `synonyms`, `phrase_boost`, `field_boost`,
`typeahead`, `reranking`, `llm`, `llm_judge` — each a query-construction or
pipeline switch, and the UI's Optimizations panel toggles exactly these.

Outbound events, in the order a search turn emits them. Every event has
`type` and `timestamp`; pipeline events also carry `node`.

| `type` | `node` | Payload |
|---|---|---|
| `connection_established` | — | `thread_id`, `existing_messages` |
| `conversation_context` | — | prior-turn summary for the panel |
| `node_start` / `node_end` | any | stage timing; `node_end` carries `duration_ms` and a status line |
| `intent_classification` | intent_classifier | `intent`, `confidence`, reasoning |
| `query_evaluation` | query_evaluator | assigned `alpha`, strategy, reasoning |
| `query_expansion` | retriever | original vs rewritten query |
| `opensearch_query` | retriever | the full DSL `body`, `index`, `params`; `query_type` is `hybrid`, `bm25_baseline`, or `quality_gate_retry` |
| `hybrid_search_start` / `hybrid_search_result` | retriever | candidate count, then candidates with scores |
| `search_progress` | retriever | interim status text |
| `reranker_start` / `reranker_progress` / `reranker_result` | reranker | per-document scores in 0–1 |
| `quality_gate` | quality_gate | pass / retry, threshold used, alpha adjustment |
| `summary_generated` | summary | recap text for `summary` turns |
| `llm_reasoning_start` / `llm_reasoning_chunk` | agent | internal reasoning, not the answer |
| `llm_response_start` / `llm_response_chunk` | agent | answer tokens; the last chunk has `is_complete: true` |
| `tool_call` | agent | a tool the agent invoked |
| `enrichment_triggered` | agent | `attribute_type`, `variant`, `canonical`, `status` (`started`, then `complete` / `failed` / `declined`), `corrected_from`, re-tag counts |
| `llm_response_corrected` | llm_judge | the regenerated answer after a hallucination retry, with before/after faithfulness |
| `agent_complete` | — | `final_response`, `citations`, `total_duration_ms`, `documents_used`, generated `title` |
| `pipeline_summary` | — | per-stage NDCG@10 / MRR / Recall@20 / Precision@10 and latency when ground truth exists, else a confidence proxy |
| `metrics` | — | timing metrics |
| `agent_error` | — | error text; the client's escape hatch when a turn fails |

Citations arrive on `agent_complete`, one frame after the final
`llm_response_chunk` — the UI renders the answer once, on `agent_complete`,
for that reason. `schemas/events.py` and `web/src/types/events.ts` must
stay in sync; `tests/unit/test_frontend_backend_event_parity.py` enforces
it in both directions.

Close codes: `1000` normal; `4003` origin not allowed (fix the `Origin` header and reconnect).

## Errors

| Code | Meaning |
|---|---|
| 400 | Malformed request (e.g. invalid `thread_id`, empty message) |
| 403 | Origin not allowed, or `ENABLE_ENRICHMENT_TOOL` is off for `/api/admin/enrich` |
| 422 | Validation error (query params, request body) |
| 429 | Rate limit exceeded |
| 500 | Unhandled error; check `/api/health` for which dependency is down |
