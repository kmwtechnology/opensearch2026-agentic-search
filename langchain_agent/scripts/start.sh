#!/bin/bash
# Agentic Hybrid Search Start Script
# Starts everything: Postgres + OpenSearch (Docker), the native backend on
# :8080 with the Vite UI on :5173 (live-reloading dev), and the demo
# container on :8000 (backend + built UI, rebuilt from the current tree).
# Dev and demo share the data services and run side by side.

set -e  # Exit on error

BACKEND_PORT=8080


echo "🚀 Starting Agentic Hybrid Search..."
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# Start PostgreSQL + OpenSearch and wait for their healthchecks
echo "🐳 Ensuring Docker services are up..."
docker compose -f "$PARENT_DIR/docker-compose.yml" up -d --wait
echo "✓ PostgreSQL and OpenSearch are ready"
echo ""

# Check if virtual environment exists
if [ ! -d "$PROJECT_DIR/.venv" ]; then
    echo "❌ Virtual environment not found"
    echo "   Run: ./scripts/setup.sh"
    exit 1
fi

# Activate virtual environment
# shellcheck source=/dev/null
source "$PROJECT_DIR/.venv/bin/activate"

# Load environment variables from .env file
if [ -f "$PROJECT_DIR/.env" ]; then
    set -a
    # shellcheck source=/dev/null
    source "$PROJECT_DIR/.env"
    set +a
fi

# Create logs directory
mkdir -p "$PROJECT_DIR/logs"

# Start backend API
echo "🔧 Starting backend API..."

cd "$PROJECT_DIR"

# Kill any existing processes from previous runs
if [ -f "$PROJECT_DIR/.backend.pid" ]; then
    PID=$(cat "$PROJECT_DIR/.backend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PROJECT_DIR/.backend.pid"
fi

# Start backend with proper PYTHONPATH
export PYTHONPATH="$PROJECT_DIR:$PYTHONPATH"
uvicorn api.main:app --reload --port "$BACKEND_PORT" > "$PROJECT_DIR/logs/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PROJECT_DIR/.backend.pid"
echo "✓ Backend started (PID: $BACKEND_PID)"

# Wait for backend to be ready
echo "⏳ Waiting for backend to be ready..."
for i in {1..30}; do
    if curl -s "http://localhost:$BACKEND_PORT/api/health" > /dev/null 2>&1; then
        echo "✓ Backend is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "❌ Backend failed to start"
        echo "   Check logs: tail -f logs/backend.log"
        exit 1
    fi
    sleep 1
done

echo ""

# Start frontend dev server
echo "🎨 Starting frontend..."

if [ -f "$PROJECT_DIR/.frontend.pid" ]; then
    PID=$(cat "$PROJECT_DIR/.frontend.pid")
    if kill -0 "$PID" 2>/dev/null; then
        kill "$PID" 2>/dev/null || true
    fi
    rm -f "$PROJECT_DIR/.frontend.pid"
fi

cd "$PROJECT_DIR/web"
npm run dev > "$PROJECT_DIR/logs/frontend.log" 2>&1 &
FRONTEND_PID=$!
echo $FRONTEND_PID > "$PROJECT_DIR/.frontend.pid"
echo "✓ Frontend started (PID: $FRONTEND_PID)"

cd "$PROJECT_DIR"

echo ""

# Demo container: backend + built UI in one image, published on :8000. Built
# from the current tree, so it reflects the code as of this start — edits
# after this show up on :5173 only, until the next start rebuilds the image.
echo "📦 Building and starting the demo container (logs/demo-build.log)..."
if docker compose -f "$PARENT_DIR/docker-compose.yml" --profile app up -d --build app \
    > "$PROJECT_DIR/logs/demo-build.log" 2>&1; then
    echo "✓ Demo container started — ready once http://localhost:8000/api/health answers (seconds to ~1 min for model init)"
else
    echo "⚠ Demo container failed to build/start — dev stack is up regardless. Last lines:"
    tail -20 "$PROJECT_DIR/logs/demo-build.log" | sed 's/^/    /'
fi

echo ""
echo "✅ All services running!"
echo ""
echo "📍 Access Services:"
echo "  Dev UI (live reload):    http://localhost:5173   (proxies to the backend below)"
echo "  Dev backend:             http://localhost:$BACKEND_PORT   (Swagger: /swagger)"
echo "  Demo (Docker image):     http://localhost:8000   (rebuilt on each start)"
echo ""
echo "📊 Data Services:"
echo "  PostgreSQL:  localhost:5432"
echo "  OpenSearch:  localhost:9200"
echo ""
echo "📋 Logs:      tail -f logs/backend.log   (or logs/frontend.log, logs/demo-build.log)"
echo ""
echo "⚙️  Stop:      ./scripts/stop.sh"
echo ""
