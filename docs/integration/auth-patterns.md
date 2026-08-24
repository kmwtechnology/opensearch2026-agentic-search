# Authentication Patterns

Two authentication flows for different use cases.

**Parent:** [Integration Guide](README.md)

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
fetch('http://localhost:8000/api/conversations', {
  credentials: 'include'  // Auto-includes cookies
})
```

**cURL (explicit):**
```bash
curl http://localhost:8000/api/conversations \
  -b cookies.txt  # Include saved cookies
```

**Python (requests):**
```python
import requests

session = requests.Session()
session.post('http://localhost:8000/api/auth/login', json={'password': '...'})
# Subsequent requests auto-include the cookie
response = session.get('http://localhost:8000/api/conversations')
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

## Pattern B: Admin Token (Automation / CI)

Use this for **unattended automation** (GitHub Actions, scheduled jobs, service-to-service).

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

**Store the token in your secret manager:**

GitHub Actions (example):
```bash
# Generate a secure random token (32+ chars)
openssl rand -hex 32

# Store in GitHub Secrets
gh secret set ADMIN_TOKEN -b <TOKEN_VALUE>
```

Cloud Run (example):
```bash
# Store in Secret Manager
gcloud secrets create admin-token --data-file=- << EOF
<TOKEN_VALUE>
EOF

# Reference in build-deploy.yml as an environment variable
```

### Usage

Every request includes the token:

```bash
curl http://localhost:8000/api/admin/health \
  -H "X-Admin-Token: abc123def456xyz..."
```

**Which endpoints accept admin token?**

- `GET /api/admin/health` — health check
- `GET /api/admin/diagnose` — field-level metrics
- `POST /api/admin/login-admin` — internal only

**Note:** `/api/auth/login` and `/api/conversations` do NOT accept admin token. Use session cookie for those.

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

**Cloud Run (production):**
```
https://*.run.app  (all Cloud Run services in the project)
```

### Origin Header

Browsers automatically set the `Origin` header. Custom clients must include it explicitly.

**cURL example:**
```bash
curl http://localhost:8000/api/conversations \
  -H "Origin: http://localhost:8000" \
  -b cookies.txt
```

### Disallowed Origin

If `Origin` is not in the allow-list, the server responds with `403 Forbidden`:

```json
{
  "detail": "Origin header is not allowed"
}
```

**Fix:** Update `get_allowed_origins()` in `api/main.py` or provide the correct Origin header.

### Host Fallback Rule

If **both** `Origin` and `Referer` headers are absent (uncommon), the server falls back to the `Host` header. This handles edge cases where a proxy strips headers.

**Example (request with no Origin/Referer):**
```bash
curl http://localhost:8000/api/health
```

Falls back to Host: `localhost:8000` → allowed.

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
curl -i http://localhost:8000/api/conversations \
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
curl http://localhost:8000/api/conversations \
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
