#!/usr/bin/env bash
# smoke_local.sh — run e2e smoke tests against a local backend.
#
# Behavior:
#   - If backend is already running on :8000, reuse it.
#   - Otherwise, start uvicorn in the background, wait for /api/health,
#     run smoke tests, then clean up.
#
# Exit codes:
#   0  — smoke tests passed
#   1  — smoke tests failed (or backend never came up)
#   2  — Docker services unavailable (postgres/opensearch); user must start them
#
# Usage:
#   scripts/smoke_local.sh [pytest-args...]

set -euo pipefail

REPO_ROOT=$(git rev-parse --show-toplevel)
LANGCHAIN_DIR="$REPO_ROOT/langchain_agent"
VENV="$LANGCHAIN_DIR/.venv/bin"
HEALTH_URL="http://127.0.0.1:8000/api/health"
PORT=8000

cd "$LANGCHAIN_DIR"

# Verify Docker services
if ! curl -sf http://localhost:9200 >/dev/null 2>&1; then
  echo "❌ OpenSearch not reachable on :9200 — run 'docker compose up -d' from repo root" >&2
  exit 2
fi
if ! pg_isready -h localhost -p 5432 >/dev/null 2>&1 && ! curl -sf http://localhost:5432 >/dev/null 2>&1; then
  # pg_isready may not be installed; fall back to checking listen port via nc/lsof
  if ! lsof -nP -i :5432 >/dev/null 2>&1; then
    echo "❌ PostgreSQL not reachable on :5432 — run 'docker compose up -d' from repo root" >&2
    exit 2
  fi
fi

# Read LOGIN_PASSWORD from .env
if [ ! -f .env ]; then
  echo "❌ .env not found — run setup.sh first" >&2
  exit 1
fi
LOGIN_PASSWORD=$(grep '^LOGIN_PASSWORD=' .env | cut -d= -f2-)
if [ -z "$LOGIN_PASSWORD" ]; then
  echo "❌ LOGIN_PASSWORD not set in .env" >&2
  exit 1
fi
export LOGIN_PASSWORD

STARTED_BACKEND=0
BACKEND_PID=""

cleanup() {
  if [ "$STARTED_BACKEND" = "1" ] && [ -n "$BACKEND_PID" ]; then
    echo "Stopping backend (pid=$BACKEND_PID)..." >&2
    kill "$BACKEND_PID" 2>/dev/null || true
    wait "$BACKEND_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# Reuse running backend if available
if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
  echo "✓ Backend already running on :$PORT — reusing"
else
  echo "Starting backend on :$PORT..."
  PYTHONPATH=. "$VENV/uvicorn" api.main:app --host 127.0.0.1 --port "$PORT" \
    >/tmp/smoke_local_backend.log 2>&1 &
  BACKEND_PID=$!
  STARTED_BACKEND=1

  # Wait up to 60s for backend to become healthy
  for _ in $(seq 1 60); do
    if curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "❌ Backend died during startup. Last 50 lines of log:" >&2
      tail -50 /tmp/smoke_local_backend.log >&2 || true
      exit 1
    fi
    sleep 1
  done
  if ! curl -sf "$HEALTH_URL" >/dev/null 2>&1; then
    echo "❌ Backend did not become healthy within 60s. Last 50 lines of log:" >&2
    tail -50 /tmp/smoke_local_backend.log >&2 || true
    exit 1
  fi
  echo "✓ Backend healthy"
fi

echo "Running smoke tests against $HEALTH_URL ..."
CLOUD_RUN_URL=http://127.0.0.1:$PORT \
  PYTHONPATH=. "$VENV/pytest" \
    tests/e2e/test_deployment_smoke.py \
    -m "e2e and slow" \
    --timeout=240 \
    --asyncio-mode=auto \
    "$@"
