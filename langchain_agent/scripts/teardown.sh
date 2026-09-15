#!/bin/bash
# Agentic Hybrid Search Teardown Script
# ⚠️  DESTRUCTIVE — removes ALL data (PostgreSQL, OpenSearch, .venv, node_modules)

echo "🚨 DESTRUCTIVE TEARDOWN — Data Will Be Deleted"
echo ""
echo "This will PERMANENTLY remove:"
echo "  ✗ PostgreSQL database (checkpoints, conversation history)"
echo "  ✗ OpenSearch index (all product documents, search indexes)"
echo "  ✗ Docker containers and volumes"
echo "  ✗ Python virtual environment (.venv)"
echo "  ✗ Node modules (web/node_modules)"
echo "  ✗ Log files and PID files"
echo ""
echo "Use this ONLY if you want a clean slate. Your data CANNOT be recovered."
echo ""
echo "→ To pause development (keep data), use: ./scripts/stop.sh"
echo "→ To resume later, use: ./scripts/start.sh"
echo ""
echo "Proceeding non-interactively (no confirmation prompt)."
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# 1. Stop running services (using reliable port-based killing)
echo "Stopping services..."

# Stop backend - kill by port first (most reliable)
if lsof -i :8000 >/dev/null 2>&1; then
    lsof -ti :8000 | xargs kill -TERM 2>/dev/null || true
    sleep 1
    if lsof -i :8000 >/dev/null 2>&1; then
        lsof -ti :8000 | xargs kill -9 2>/dev/null || true
    fi
fi
rm -f "$PROJECT_DIR/.backend.pid"
pkill -f "uvicorn api.main" 2>/dev/null || true

# Stop frontend - kill by port first (most reliable)
if lsof -i :5173 >/dev/null 2>&1; then
    lsof -ti :5173 | xargs kill -TERM 2>/dev/null || true
    sleep 1
    if lsof -i :5173 >/dev/null 2>&1; then
        lsof -ti :5173 | xargs kill -9 2>/dev/null || true
    fi
fi
rm -f "$PROJECT_DIR/.frontend.pid"
pkill -f "vite" 2>/dev/null || true

echo "✓ Services stopped"

# 2. Remove Docker containers and volumes (PostgreSQL + OpenSearch).
echo "Removing Docker containers and volumes (PostgreSQL + OpenSearch)..."
cd "$PARENT_DIR" || exit 1
docker compose down -v 2>/dev/null || true
echo "✓ Docker containers and volumes removed"

# 3. Remove Python virtual environment
echo "Removing Python virtual environment..."
if [ -d "$PROJECT_DIR/.venv" ]; then
    rm -rf "$PROJECT_DIR/.venv"
    echo "✓ Virtual environment removed"
else
    echo "  No virtual environment found"
fi

# 4. Remove node_modules
echo "Removing node_modules..."
if [ -d "$PROJECT_DIR/web/node_modules" ]; then
    rm -rf "$PROJECT_DIR/web/node_modules"
    echo "✓ node_modules removed"
else
    echo "  No node_modules found"
fi

# 5. Remove logs directory
echo "Removing logs..."
if [ -d "$PROJECT_DIR/logs" ]; then
    rm -rf "$PROJECT_DIR/logs"
    echo "✓ Logs removed"
else
    echo "  No logs found"
fi

echo ""
echo "✅ Teardown complete"
echo ""
echo "To set up again, run:"
echo "  ./scripts/setup.sh"
