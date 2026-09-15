# Integration Guide

REST API and WebSocket examples for integrating Agentic Hybrid Search into your application.

**Parent:** [Root README](../../README.md)

## Quick Links

| Guide | Purpose | For Whom |
|-------|---------|----------|
| [REST API](rest-api.md) | Endpoints with cURL examples (auth, conversations, suggestions, admin/enrichment) | Backend integrators |
| [WebSocket](websocket.md) | Message contract, event stream, JS/Python examples | Real-time UI developers |
| [Auth Patterns](auth-patterns.md) | Session cookie flow (browser) and admin token flow (automation) | All integrators |

---

## API Base URL

**Local (only supported target — issue #110/#113):**
```
http://localhost:8000
```

---

## Authentication Overview

Two auth patterns:

### Pattern A: Session Cookie (Browser / Interactive)

User logs in via `POST /api/auth/login` and receives a signed HttpOnly cookie.

> **Note:** Authentication is optional by default. The backend's `REQUIRE_LOGIN` config defaults to `false`, meaning no login gate is enforced and this step can be skipped entirely. See [Auth Patterns](auth-patterns.md) for full details.

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"password": "your_login_password"}' \
  -c cookies.txt
```

The `ahs_session` cookie is automatically included in subsequent requests (must pass `-b cookies.txt`).

**When to use:** Web UI, interactive scripts, any browser-based client.

### Pattern B: Admin Token (Automation / CI)

Long-lived token in `X-Admin-Token` header for automation.

```bash
curl -X GET http://localhost:8000/api/admin/health \
  -H "X-Admin-Token: your_admin_token_here"
```

**When to use:** scheduled jobs, scripts, service-to-service calls (no user interaction).

---

## Common Headers

| Header | Purpose | Required |
|--------|---------|----------|
| `Origin` | CORS check; must match allow-list | Yes (for authenticated endpoints) |
| `Content-Type` | Request body format | Yes if POST/PUT body present |
| `X-Admin-Token` | Admin API token (automation) | For `/api/admin/*` only |

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
| 401 | Unauthorized (missing/invalid session cookie) | Yes (re-authenticate) |
| 403 | Forbidden (disallowed Origin, auth failed) | No |
| 500 | Server error | Yes (exponential backoff) |
| 503 | Service unavailable (health probe failed) | Yes |

---

For detailed REST examples, see [REST API](rest-api.md). For WebSocket streaming, see [WebSocket](websocket.md). For auth details, see [Auth Patterns](auth-patterns.md).
