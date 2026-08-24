# REST API Guide

Complete REST endpoint documentation with cURL examples.

**Parent:** [Integration Guide](README.md)

---

## Authentication

First, log in to get a session cookie:

```bash
# Login
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your_password"}' \
  -c cookies.txt

# Expected response (200 OK):
# Set-Cookie: ahs_session=...
```

Store the cookie with `-c cookies.txt`, then include it in all subsequent requests with `-b cookies.txt`.

### Health Check (No Auth Required)

```bash
curl http://localhost:8000/api/health
```

Response (200 OK):
```json
{
  "status": "healthy",
  "postgres": "ok",
  "opensearch": "ok",
  "google_api": "ok",
  "document_count": 9618,
  "timestamp": "2026-06-04T16:30:45Z"
}
```

If any probe is not "ok", the service is degraded. Check [Troubleshooting](../operations/troubleshooting.md).

---

## Conversations

### Create a Conversation

```bash
curl -X POST http://localhost:8000/api/conversations \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "title": "My Shopping Session"
  }'
```

Response (201 Created):
```json
{
  "id": "conv_abc123def456",
  "title": "My Shopping Session",
  "created_at": "2026-06-04T16:30:45Z",
  "updated_at": "2026-06-04T16:30:45Z",
  "message_count": 0
}
```

### List All Conversations

```bash
curl http://localhost:8000/api/conversations \
  -b cookies.txt
```

Response (200 OK):
```json
{
  "conversations": [
    {
      "id": "conv_abc123def456",
      "title": "My Shopping Session",
      "created_at": "2026-06-04T16:30:45Z",
      "updated_at": "2026-06-04T16:30:45Z",
      "message_count": 3
    }
  ],
  "total": 1
}
```

---

## Messages (REST Polling)

### Send a Message (Non-Streaming)

For simple polling (not real-time), use REST:

```bash
curl -X POST http://localhost:8000/api/conversations/conv_abc123def456/messages \
  -H "Content-Type: application/json" \
  -b cookies.txt \
  -d '{
    "message": "Find me wireless headphones under $100"
  }'
```

Response (202 Accepted — async processing):
```json
{
  "thread_id": "conv_abc123def456",
  "status": "processing"
}
```

**Note:** For real-time streaming, use [WebSocket](websocket.md) instead. REST polling is slower (~20-30s latency).

---

## Suggestions (Typeahead)

### Autocomplete Suggestions

```bash
curl 'http://localhost:8000/api/suggest?q=wireless' \
  -b cookies.txt
```

Query parameters:
- `q` (required): search prefix (e.g., "wireless", "blue")
- `limit` (optional, default=10): max suggestions to return

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

### Admin Health Check

Requires `X-Admin-Token` header (for automation):

```bash
curl http://localhost:8000/api/admin/health \
  -H "X-Admin-Token: your_admin_token_here"
```

Response (200 OK):
```json
{
  "status": "healthy",
  "postgres": "ok",
  "opensearch": "ok",
  "google_api": "ok",
  "document_count": 9618,
  "index_age_seconds": 3600
}
```

Same format as public `/api/health`, but available only to admins.

### Diagnose (Field-Level Metrics)

```bash
curl http://localhost:8000/api/admin/diagnose \
  -H "X-Admin-Token: your_admin_token_here"
```

Response includes hit counts per field (product_title, product_brand, product_color, etc.):
```json
{
  "status": "healthy",
  "field_stats": {
    "product_title": {"indexed": true, "hit_count": 9618},
    "product_brand": {"indexed": true, "hit_count": 9500},
    "product_color": {"indexed": true, "hit_count": 8200}
  }
}
```

---

## Logout

```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -b cookies.txt
```

Response (200 OK):
```json
{
  "status": "logged_out"
}
```

The session cookie is invalidated server-side. The `Set-Cookie` response header instructs the client to delete the cookie.

---

## Error Responses

### 400 Bad Request

```json
{
  "detail": "Invalid JSON or missing required field 'message'"
}
```

### 401 Unauthorized

```json
{
  "detail": "Invalid or missing session. Please login."
}
```

**Fix:** Re-authenticate via `POST /api/auth/login`.

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

**Currently:** No rate limiting enforced. Requests are processed sequentially by design (concurrency=1 per Cloud Run instance for stateful WebSocket sessions).

If you spam requests, you'll simply queue them; they'll be processed in order.

---

For WebSocket real-time examples, see [WebSocket](websocket.md). For auth details, see [Auth Patterns](auth-patterns.md).
