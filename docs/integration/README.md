# Integration Guide

REST API and WebSocket examples for integrating Agentic Hybrid Search into your application.

**Parent:** [Root README](../../README.md)

## Quick Links

| Guide | Purpose | For Whom |
|-------|---------|----------|
| [REST API](rest-api.md) | Endpoints with cURL examples (health, suggestions, admin/enrichment) | Backend integrators |
| [WebSocket](websocket.md) | Message contract, event stream, JS/Python examples | Real-time UI developers |

---

## API Base URL

**Local (only supported target — issue #110/#113):**
```
http://localhost:8000
```

---

## Authentication Overview

There is no login gate and no admin token. **Same-origin checking is the app's only auth layer** — every request must carry an `Origin` (or `Referer`) header that matches the allow-list (`api/middleware/origin_auth.py`); a disallowed one always gets `403 Forbidden`, and `/api/admin/*` is checked the same way as everything else. The WebSocket handshake applies the same check (`verify_websocket_origin`, close code 4003 on a disallowed origin).

**When to use same-origin:** it's automatic for any same-origin caller (Web UI, interactive scripts, browser-based clients) — just make sure your `Origin` header is on the allow-list.

---

## Common Headers

| Header | Purpose | Required |
|--------|---------|----------|
| `Origin` | CORS check; must match allow-list | Yes (for authenticated endpoints) |
| `Content-Type` | Request body format | Yes if POST/PUT body present |

**Allow-listed Origins:**
- localhost/127.0.0.1 only, an explicit set of dev ports (5173, 5174, 3000, 8000, 8080) — see `api/middleware/origin_auth.py::get_allowed_origins()`
- Disallowed Origins always return `403 Forbidden`

---

## Status Codes

| Code | Meaning | Retry? |
|------|---------|--------|
| 200 | Success | — |
| 400 | Bad request (invalid JSON, missing fields) | No |
| 403 | Forbidden (disallowed Origin) | No |
| 500 | Server error | Yes (exponential backoff) |
| 503 | Service unavailable (health probe failed) | Yes |

---

For detailed REST examples, see [REST API](rest-api.md). For WebSocket streaming, see [WebSocket](websocket.md).
