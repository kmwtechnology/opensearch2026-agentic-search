# REST API Guide

Complete REST endpoint documentation with cURL examples.

**Parent:** [Integration Guide](README.md)

---

## Authentication

> **Note:** There is no login gate. Same-origin checking (`Origin`/`Referer` header against an allow-list) is the app's only auth layer — see [Auth Patterns](auth-patterns.md) for full details. Just make sure requests carry an allow-listed `Origin` header (see below); no login step is required.

### Health Check (No Auth Required)

```bash
curl http://localhost:8000/api/health
```

Response (200 OK):
```json
{
  "status": "ok",
  "version": "1.1.0",
  "postgres": true,
  "google_ai": true,
  "vector_store": true,
  "document_count": 9618
}
```

`status` is `"ok"` when postgres and google_ai are both healthy, otherwise `"degraded"` (always returns 200, even when degraded — fail-open for monitoring).

---

## Chat (WebSocket Only)

There is no REST polling endpoint for conversations or messages — all chat happens over WebSocket. See [WebSocket](websocket.md) for connecting, sending messages, and receiving streamed pipeline events. Conversation state (thread history) is keyed by `thread_id` and persisted via PostgreSQL checkpoints, not a separate conversations resource.

---

## Suggestions (Typeahead)

### Autocomplete Suggestions

```bash
curl 'http://localhost:8000/api/suggest?q=wireless' \
  -H "Origin: http://localhost:8000"
```

Query parameters:
- `q` (required): search prefix, 1–100 chars (e.g., "wireless", "blue")
- `limit` (optional, default=8, range 1–20): max suggestions to return

Response (200 OK):
```json
{
  "suggestions": [
    {
      "text": "wireless headphones",
      "source": "products",
      "score": 0.95
    },
    {
      "text": "wireless speaker",
      "source": "products",
      "score": 0.88
    }
  ]
}
```

**Suggestions are context-free** (no conversation history). Prefix must match product titles or brands. Single-character typos are corrected; longer queries fall back to exact prefix match.

---

## Admin Endpoints

> **Note:** `/api/admin/*` routes are protected by same-origin checking only, same as everything else — there's no separate admin-token requirement in front of them today. (`ADMIN_TOKEN`/`verify_admin_token` exists in the codebase as a preserved-but-currently-unused utility for future automation; see [Auth Patterns](auth-patterns.md).)

### Admin Health Check

```bash
curl http://localhost:8000/api/admin/health \
  -H "Origin: http://localhost:8000"
```

Response (200 OK):
```json
{
  "status": "healthy",
  "opensearch": {
    "connected": true,
    "index": "esci-products",
    "documents": 9618
  }
}
```

This is an index-level probe (does the product index exist and how many documents does it have), distinct from the public `/api/health` (Postgres + Google AI + vector store reachability). `status` is `"healthy"` (index exists and is queryable), `"degraded"` (OpenSearch reachable but index missing), or `"unhealthy"` (OpenSearch unreachable, with an `error` field).

### Diagnose (Field-Level Metrics)

```bash
curl http://localhost:8000/api/admin/diagnose?q=sony \
  -H "Origin: http://localhost:8000"
```

Diagnostic-only: probes the live index for a query (`q`, default `"sony"`) across the suggest fields (`title_suggest`/`brand_suggest`) versus the primary lexical fields (`title`/`product_brand`), and reports whether the mapping includes the suggest fields at all — used to detect a stale mapping that predates the suggest feature.

### Enrich Attribute Taxonomy

Grows the live color/waterproof taxonomy with a new variant term and triggers a
real full Lucille reindex of the catalog (~15-20s) — the same mechanism the
agent's own `trigger_enrichment` tool uses when it recognizes a taxonomy gap
during a chat turn (see `ARCHITECTURE.md`'s "Enrichment Flywheel" section).
Disabled by default; requires `ENABLE_ENRICHMENT_TOOL=true` on the backend.

```bash
curl -X POST http://localhost:8000/api/admin/enrich \
  -H "Origin: http://localhost:8000" \
  -H "Content-Type: application/json" \
  -d '{"attribute_type": "waterproof", "variant": "weatherproof", "canonical": "waterproof"}'
```

`canonical` is optional — omit it to let dictionary-only classification
resolve the term (fails with `success: false` if it can't); pass it directly
to skip classification, the same way the live agent tool supplies its own
LLM-classified canonical for terms the dictionary can't match.

Response (200 OK):
```json
{
  "success": true,
  "attribute_type": "waterproof",
  "variant": "weatherproof",
  "canonical": "waterproof",
  "reason": null,
  "reindex_triggered": true,
  "reindex_success": true,
  "docs_processed": 9618,
  "duration_seconds": 21.16
}
```

`success: false` (still HTTP 200 — this is a normal outcome, not an error)
when the term can't be classified, is already mapped, or `attribute_type`
isn't `color`/`waterproof`:
```json
{
  "success": false,
  "attribute_type": "waterproof",
  "variant": "unobtainium",
  "canonical": null,
  "reason": "could not classify to a known waterproof bucket",
  "reindex_triggered": false,
  "reindex_success": false,
  "docs_processed": 0,
  "duration_seconds": 0.0
}
```

Returns 403 when `ENABLE_ENRICHMENT_TOOL` is unset/false, 422 on a missing
`attribute_type`/`variant` or an empty `variant`.

---

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Invalid JSON or missing required field 'message'"
}
```

### 403 Forbidden

```json
{
  "detail": "Origin header is not allowed"
}
```

**Fix:** Check your Origin header matches the allow-list. See [Auth Patterns](auth-patterns.md).

### 500 Internal Server Error

```json
{
  "detail": "An error occurred. Check logs for details."
}
```

**Fix:** Check `/api/health` to see which probe failed (PostgreSQL, OpenSearch, or Google API).

---

## Rate Limiting

**Currently:** No rate limiting enforced. Requests are processed sequentially by design (stateful WebSocket sessions).

If you spam requests, you'll simply queue them; they'll be processed in order.

---

For WebSocket real-time examples, see [WebSocket](websocket.md). For auth details, see [Auth Patterns](auth-patterns.md).
