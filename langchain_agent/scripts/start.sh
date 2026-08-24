#!/bin/bash
# Agentic Hybrid Search Start Script
# Starts backend API and frontend development server

set -e  # Exit on error


echo "🚀 Starting Agentic Hybrid Search..."
echo ""

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# Check prerequisites
echo "🔍 Checking prerequisites..."

# Check if PostgreSQL is running
if ! docker compose -f "$PARENT_DIR/docker-compose.yml" ps 2>/dev/null | grep -q "postgres.*Up"; then
    echo "   Starting PostgreSQL..."
    cd "$PARENT_DIR"
    docker compose up -d postgres > /dev/null 2>&1
    cd "$PROJECT_DIR"
    sleep 2
fi
echo "✓ PostgreSQL is ready"

# Check if OpenSearch is running
if ! docker compose -f "$PARENT_DIR/docker-compose.yml" ps 2>/dev/null | grep -q "opensearch.*Up"; then
    echo "   Starting OpenSearch..."
    cd "$PARENT_DIR"
    docker compose up -d opensearch > /dev/null 2>&1
    cd "$PROJECT_DIR"
    echo "   Waiting for OpenSearch to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:9200/_cluster/health 2>/dev/null | grep -q '"status"'; then
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "❌ OpenSearch failed to start"
            echo "   Check: docker compose -f $PARENT_DIR/docker-compose.yml logs opensearch"
            exit 1
        fi
        sleep 2
    done
fi
echo "✓ OpenSearch is ready"

# Check if OpenSearch Dashboards is running
if ! docker compose -f "$PARENT_DIR/docker-compose.yml" ps 2>/dev/null | grep -q "opensearch-dashboards.*Up"; then
    echo "   Starting OpenSearch Dashboards..."
    cd "$PARENT_DIR"
    docker compose up -d opensearch-dashboards > /dev/null 2>&1
    cd "$PROJECT_DIR"
    echo "   Waiting for OpenSearch Dashboards to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:5601/api/status 2>/dev/null | grep -q 'state'; then
            break
        fi
        if [ "$i" -eq 30 ]; then
            echo "⚠ OpenSearch Dashboards is starting (may take 10-15 seconds)"
            break
        fi
        sleep 2
    done
fi
echo "✓ OpenSearch Dashboards is ready"
echo ""

# Optional: Re-ingest product data
if [ "$1" == "--update-docs" ]; then
    echo "📚 Re-ingesting ESCI product data via Lucille ETL..."
    if bash "$SCRIPT_DIR/lucille_ingest.sh" > "$PROJECT_DIR/logs/docs-update.log" 2>&1; then
        echo "✓ Product data updated"
    else
        echo "⚠ Lucille ingest had issues — see logs/docs-update.log"
        echo "  Fallback (requires GOOGLE_API_KEY): PYTHONPATH=$PROJECT_DIR python $PROJECT_DIR/ingest_esci_products.py"
    fi
    echo ""
fi

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
uvicorn api.main:app --reload --port 8000 > "$PROJECT_DIR/logs/backend.log" 2>&1 &
BACKEND_PID=$!
echo $BACKEND_PID > "$PROJECT_DIR/.backend.pid"
echo "✓ Backend started (PID: $BACKEND_PID)"

# Wait for backend to be ready
echo "⏳ Waiting for backend to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8000/api/health > /dev/null 2>&1; then
        echo "✓ Backend is ready"
        break
    fi
    if [ "$i" -eq 30 ]; then
        echo "❌ Backend failed to start"
        echo "   Check logs: ./scripts/logs.sh backend"
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
echo "✅ All services running!"
echo ""
echo "📍 Access Services:"
echo "  Frontend:                http://localhost:5173"
echo "  Backend:                 http://localhost:8000"
echo "  API Docs (Swagger UI):   http://localhost:8000/swagger"
echo "  OpenSearch Dashboards:   http://localhost:5601"
echo ""
echo "📊 Data Services:"
echo "  PostgreSQL:  localhost:5432"
echo "  OpenSearch:  localhost:9200"
echo ""
echo "📋 Logs:"
echo "  Backend:   ./scripts/logs.sh backend"
echo "  Frontend:  ./scripts/logs.sh frontend"
echo "  All:       ./scripts/logs.sh all"
echo ""
echo "⚙️  Commands:"
echo "  Stop services:        ./scripts/stop.sh"
echo "  Re-ingest products:  ./scripts/start.sh --update-docs"
echo "  View all logs:        ./scripts/logs.sh all"
echo ""
