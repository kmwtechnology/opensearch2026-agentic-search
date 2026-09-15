# Authentication Patterns

Two authentication flows for different use cases.

**Parent:** [Integration Guide](README.md)

---

## Login is off by default

`REQUIRE_LOGIN` defaults to **`false`** (`core/config.py`). With it off, there is no
login screen, no session check on any route, and **`/api/admin/*` is reachable by
any same-origin caller with no credentials** — that's what lets the header's
Restart button call `POST /api/admin/demo-reset` straight from the browser.
`verify_same_origin` still runs on every route regardless of `REQUIRE_LOGIN`, so a
cross-site caller is still rejected; only the *same-origin, no-login* gap is what
`REQUIRE_LOGIN=false` opens up.

Everything below — Pattern A's login flow, Pattern B's admin token — still exists
and still works exactly as described; it's just optional. **Any deployment where an
unauthenticated same-origin caller reaching `/api/admin/*` is unacceptable must set
`REQUIRE_LOGIN=true`.** `setup.sh` generates a `LOGIN_PASSWORD` unconditionally
(so it's ready if you flip the flag), but does not set `REQUIRE_LOGIN=true` itself.

---

## Pattern A: Session Cookie (Browser / Interactive)

Use this when a **user is actively interacting** with the application (web UI, mobile app, etc.).

### Flow

```
1. User enters password → POST /api/auth/login
                ↓
2. Server validates password → generates signed cookie
                ↓
3. Client stores cookie → browsers do this automatically
                ↓
4. All subsequent requests include cookie automatically
                ↓
5. Cookie expires after 24 hours (configurable) → user logs in again
```

### Step 1: Login

**Request:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -H "Origin: http://localhost:8000" \
  -d '{
    "password": "abc123def456"
  }' \
  -c cookies.txt
```

**Response (200 OK):**
```
Set-Cookie: ahs_session=eyJhbGciOiJIUzI1NiIs...; Path=/; HttpOnly; SameSite=Lax; Max-Age=86400
```

The cookie is **HttpOnly** (not accessible to JavaScript, safe from XSS) and **SameSite=Lax** (CSRF protection).

**Important:** The password must match `LOGIN_PASSWORD` environment variable (shared password, not per-user).

### Step 2: Use the Cookie

**Browser (automatic):**
```javascript
fetch('http://localhost:8000/api/suggest?q=wireless', {
  credentials: 'include'  // Auto-includes cookies
})
```

**cURL (explicit):**
```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -b cookies.txt  # Include saved cookies
```

**Python (requests):**
```python
import requests

session = requests.Session()
session.post('http://localhost:8000/api/auth/login', json={'password': '...'})
# Subsequent requests auto-include the cookie
response = session.get('http://localhost:8000/api/suggest', params={'q': 'wireless'})
```

### Step 3: Session Expiry

By default, session cookies expire after **24 hours** (configurable via `SESSION_MAX_AGE_SECONDS`).

When the cookie expires:
- Browser requests get a `401 Unauthorized` response
- WebSocket connections close with code `4401`

**Response:**
```json
{
  "detail": "Invalid or missing session. Please login."
}
```

**Recovery:** User must re-authenticate via `POST /api/auth/login` and continue.

### Step 4: Logout

```bash
curl -X POST http://localhost:8000/api/auth/logout \
  -b cookies.txt
```

Server invalidates the session cookie server-side. Client also receives a `Set-Cookie` response instructing the browser to delete the cookie.

---

## Pattern B: Admin Token (Automation)

Use this for **unattended automation** (scheduled jobs, scripts, service-to-service) — this project has no CI to run it from, but the mechanism still applies to any local or scripted caller.

### Flow

```
1. Admin provides long-lived token
                ↓
2. Application stores token in environment variable (ADMIN_TOKEN)
                ↓
3. Each request includes token in X-Admin-Token header
                ↓
4. No session cookie needed; no login required
```

### Setup

```bash
# Generate a secure random token (32+ chars)
openssl rand -hex 32
# Set ADMIN_TOKEN=<value> in .env
```

### Usage

Every request includes the token:

```bash
curl http://localhost:8000/api/admin/health \
  -H "X-Admin-Token: abc123def456xyz..."
```

**Which endpoints accept admin token?**

- `GET /api/admin/health` — index-level health check
- `GET /api/admin/diagnose` — field-level metrics
- `POST /api/admin/enrich` — taxonomy enrichment (gated by `ENABLE_ENRICHMENT_TOOL`)

**Note:** `/api/auth/login` does NOT accept admin token — it's the login route itself. Session-authenticated (non-automation) users can also call the admin routes above after logging in.

### Token Security

- **Never commit tokens to git** — store in environment variables or secret managers only
- **Use constant-time comparison** — the server uses `hmac.compare_digest()` to prevent timing attacks
- **Rotate regularly** — if a token is compromised, generate a new one
- **Minimal scopes** — admin token only has access to `/api/admin/*` and health endpoints

---

## CORS & Origin Validation

Both auth patterns require the `Origin` header to match the **allow-list**.

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
  -H "Origin: http://localhost:8000" \
  -b cookies.txt
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

## Comparison

| Factor | Session Cookie | Admin Token |
|--------|-----------------|------------|
| **Use case** | Interactive (web UI, user) | Automation (CI, jobs) |
| **Login required** | Yes | No |
| **Expiry** | 24h default | None (long-lived) |
| **Where stored** | Browser cookie | Environment var / secret |
| **Scope** | Full API | `/api/admin/*` only |
| **Security** | HttpOnly, SameSite | Constant-time comparison |
| **Multi-user support** | Per-user session | Shared token (no tracking) |

---

## Troubleshooting

### 401 Unauthorized on Session Endpoint

**Cause:** Cookie is missing or expired.

**Check:**
```bash
curl -i http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000" \
  -b cookies.txt
```

Look for `Set-Cookie` in the response. If absent, the cookie is not being sent.

**Fix:** Re-authenticate:
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Origin: http://localhost:8000" \
  -d '{"password": "..."}' \
  -c cookies.txt
```

### 403 Forbidden (Origin)

**Cause:** The `Origin` header doesn't match the allow-list.

**Fix:** Provide the correct Origin:
```bash
curl http://localhost:8000/api/suggest?q=wireless \
  -H "Origin: http://localhost:8000" \
  -b cookies.txt
```

For Cloud Run, Origin must be `https://<service_name>-<region>.run.app`.

### 401 on WebSocket (Code 4401)

**Cause:** Session cookie is expired or invalid.

**Flow:**
1. WebSocket connection attempt
2. Server checks session cookie
3. If invalid/expired → close with code `4401`
4. Client must re-authenticate and reconnect

---

For detailed API examples, see [REST API](rest-api.md) and [WebSocket](websocket.md).
