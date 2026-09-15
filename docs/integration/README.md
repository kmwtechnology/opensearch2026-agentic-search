# Integration Guide

REST API and WebSocket examples for integrating Agentic Hybrid Search into your application.

**Parent:** [Root README](../../README.md)

## Quick Links

| Guide | Purpose | For Whom |
|-------|---------|----------|
| [REST API](rest-api.md) | Endpoints with cURL examples (auth, conversations, suggestions, admin/enrichment) | Backend integrators |
| [WebSocket](websocket.md) | Message contract, event stream, JS/Python examples | Real-time UI developers |
| [Auth Patterns](auth-patterns.md) | Same-origin checking (the only auth layer) and the preserved-but-unused admin token utility | All integrators |

---

## API Base URL

**Local (only supported target — issue #110/#113):**
```
http://localhost:8000
```

---

## Authentication Overview

There is no login gate. **Same-origin checking is the app's only auth layer** — every request must carry an `Origin` (or `Referer`) header that matches the allow-list; a disallowed one always gets `403 Forbidden`. See [Auth Patterns](auth-patterns.md) for full details.

A separate `X-Admin-Token` mechanism (`ADMIN_TOKEN` env var, `verify_admin_token`) exists in the codebase for future automation use, but it is **not currently wired into any route** — `/api/admin/*` routes today are protected by same-origin checking only, same as everything else.

**When to use same-origin:** it's automatic for any same-origin caller (Web UI, interactive scripts, browser-based clients) — just make sure your `Origin` header is on the allow-list.

---

## Common Headers

| Header | Purpose | Required |
|--------|---------|----------|
| `Origin` | CORS check; must match allow-list | Yes (for authenticated endpoints) |
| `Content-Type` | Request body format | Yes if POST/PUT body present |
| `X-Admin-Token` | Admin token utility (`verify_admin_token`) — preserved for future automation, not currently wired into any route | Not currently required anywhere |

**Allow-listed Origins:**
- localhost: `http://localhost:8000`, `http://127.0.0.1:8000` (dev ports 8000–9000)
- `https://*.run.app` — dormant Cloud Run pattern, kept in the allow-list but no deployment target exists today (issue #110/#113)
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

For detailed REST examples, see [REST API](rest-api.md). For WebSocket streaming, see [WebSocket](websocket.md). For auth details, see [Auth Patterns](auth-patterns.md).
