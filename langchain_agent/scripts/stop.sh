#!/bin/bash
# Agentic Hybrid Search Stop Script
# Stops backend API and frontend development server
#
# Strategy: Kill by port (most reliable) → fallback to PID file → fallback to process name
# This ensures even stale .pid files don't prevent proper shutdown.

echo "🛑 Stopping Agentic Hybrid Search..."
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# Stop backend
echo "Stopping backend..."

# Primary: Kill by port (most reliable - always works if process is using the port)
if lsof -i :8000 >/dev/null 2>&1; then
    lsof -ti :8000 | xargs kill -TERM 2>/dev/null || true
    sleep 1
    # If still running after SIGTERM, use SIGKILL
    if lsof -i :8000 >/dev/null 2>&1; then
        lsof -ti :8000 | xargs kill -9 2>/dev/null || true
    fi
fi

# Secondary: Clean up .pid file if it exists
rm -f "$PROJECT_DIR/.backend.pid"

# Tertiary: Fallback process name kill (in case port-based method missed it)
pkill -f "uvicorn api.main" 2>/dev/null || true

echo "✓ Backend stopped"

# Stop frontend
echo "Stopping frontend..."

# Primary: Kill by port (most reliable - always works if process is using the port)
if lsof -i :5173 >/dev/null 2>&1; then
    lsof -ti :5173 | xargs kill -TERM 2>/dev/null || true
    sleep 1
    # If still running after SIGTERM, use SIGKILL
    if lsof -i :5173 >/dev/null 2>&1; then
        lsof -ti :5173 | xargs kill -9 2>/dev/null || true
    fi
fi

# Secondary: Clean up .pid file if it exists
rm -f "$PROJECT_DIR/.frontend.pid"

# Tertiary: Fallback process name kill (in case port-based method missed it)
pkill -f "vite" 2>/dev/null || true

echo "✓ Frontend stopped"

echo ""

# Stop Docker containers (PostgreSQL + OpenSearch)
echo "Stopping Docker containers (PostgreSQL + OpenSearch)..."
cd "$PARENT_DIR" || exit 1
docker compose down > /dev/null 2>&1
echo "✓ Docker containers stopped"

echo ""
echo "✅ Services stopped"
