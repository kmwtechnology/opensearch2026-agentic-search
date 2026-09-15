# Authentication Patterns

How auth works in this app, and what's preserved for future automation use.

**Parent:** [Integration Guide](README.md)

---

## Same-origin checking is the only auth layer

There is no login gate — the shared-password session system (`REQUIRE_LOGIN`,
`LOGIN_PASSWORD`, `/api/auth/*`, the `ahs_session` cookie, WebSocket close code
`4401`) was removed from the codebase entirely (issue #135). It was already
optional and off by default, so nothing observable changed for users — but
this doc used to describe it in detail, and that content is gone now that the
code is gone.

**`verify_same_origin`** (`api/middleware/origin_auth.py`) runs on every route:
the request's `Origin` (or, for a plain browser GET with no `Origin` header,
its `Referer`) must match an allow-list. A disallowed caller always gets
`403 Forbidden` (WebSocket connections close with code `4003`). This is what
lets the header's Restart button call `POST /api/admin/demo-reset` straight
from the browser with no credentials — same-origin is deliberately the only
barrier, this is a local demo box, not a multi-tenant deployment.

---

## Making requests

### REST

```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000"
```

**Browser (automatic):**
```javascript
fetch('http://localhost:8000/api/suggest?q=wireless')
// Browsers set Origin automatically; no credentials/cookie needed.
```

### WebSocket

```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/chat?thread_id=${threadId}`);
// Browsers set the Origin header on the handshake automatically.
```

Custom (non-browser) clients must set `Origin` explicitly on the handshake,
since nothing sets it for them:

```python
import websockets

async with websockets.connect(
    "ws://localhost:8000/ws/chat?thread_id=conv_abc123",
    additional_headers={"Origin": "http://localhost:8000"},
) as ws:
    ...
```

---

## CORS & Origin Validation

### Allow-List Rules

**Localhost (development):**
```
http://localhost:8000
http://localhost:8001
http://127.0.0.1:8000
http://127.0.0.1:5173  (Vite frontend)
```

**Cloud Run allow-list (dormant — no deployment target today, issue #110/#113):**
```
https://*.run.app  (kept in the allow-list pattern for if a hosted deployment is ever revisited)
```

### Origin Header

Browsers automatically set the `Origin` header. Custom clients must include it explicitly.

**cURL example:**
```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000"
```

Same-origin GET requests without an `Origin` header (e.g. plain browser navigation) are checked against the `Referer` header instead. If neither `Origin` nor an allow-listed `Referer` is present, the request is rejected — there is no further fallback.

### Disallowed Origin

If `Origin` (and `Referer`) is not in the allow-list, the server responds with `403 Forbidden`:

```json
{
  "detail": "Origin header is not allowed"
}
```

**Fix:** Update `get_allowed_origins()` in `api/middleware/origin_auth.py` or provide the correct Origin header.

---

## Admin token (`verify_admin_token`) — preserved but currently unused

`api/middleware/admin_auth.py` still holds `verify_admin_token`: it checks an
`X-Admin-Token` header against the `ADMIN_TOKEN` environment variable using
`hmac.compare_digest` (constant-time comparison, to avoid timing attacks).
This was relocated from the now-deleted `session_auth.py` and kept as a
standalone utility, with its own unit tests, for possible future automation
use (e.g. a CI job hitting admin routes directly without a browser).

**It is not currently wired into any route.** `/api/admin/*` (health,
diagnose, enrich) is protected by `verify_same_origin` only, same as every
other route — supplying an `X-Admin-Token` header today does nothing, because
nothing checks it. Don't document or rely on it as protecting admin routes;
treat it as available-if-needed, not active.

```bash
# Generate a token, in case a future route wires this in:
openssl rand -hex 32
# Set ADMIN_TOKEN=<value> in .env
```

### Token Security (if/when it's wired in)

- **Never commit tokens to git** — store in environment variables or secret managers only
- **Use constant-time comparison** — `verify_admin_token` already uses `hmac.compare_digest()` to prevent timing attacks
- **Rotate regularly** — if a token is compromised, generate a new one

---

## Troubleshooting

### 403 Forbidden (Origin)

**Cause:** The `Origin` header doesn't match the allow-list.

**Fix:** Provide the correct Origin:
```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000"
```

For Cloud Run, Origin must be `https://<service_name>-<region>.run.app`.

### WebSocket closes with code 4003

**Cause:** The connecting `Origin` header didn't match the allow-list.

**Flow:**
1. WebSocket connection attempt
2. Server checks the handshake's `Origin` (`verify_websocket_origin`)
3. If not allow-listed → close with code `4003`
4. Client must reconnect with a valid `Origin` header

There is no session/login step to retry here — fixing the `Origin` header and
reconnecting is the whole fix.

---

For detailed API examples, see [REST API](rest-api.md) and [WebSocket](websocket.md).
