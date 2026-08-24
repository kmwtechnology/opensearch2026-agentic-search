#!/bin/bash
# Agentic Hybrid Search Logs Script
# View logs from backend and frontend services


# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# Check if logs directory exists
if [ ! -d "$PROJECT_DIR/logs" ]; then
    mkdir -p "$PROJECT_DIR/logs"
fi

case "$1" in
    backend)
        if [ -f "$PROJECT_DIR/logs/backend.log" ]; then
            tail -f "$PROJECT_DIR/logs/backend.log"
        else
            echo "Backend log not found"
            echo "Start backend with: ./scripts/start.sh"
            exit 1
        fi
        ;;
    frontend)
        if [ -f "$PROJECT_DIR/logs/frontend.log" ]; then
            tail -f "$PROJECT_DIR/logs/frontend.log"
        else
            echo "Frontend log not found"
            echo "Start frontend with: ./scripts/start.sh"
            exit 1
        fi
        ;;
    all)
        if [ -f "$PROJECT_DIR/logs/backend.log" ] || [ -f "$PROJECT_DIR/logs/frontend.log" ]; then
            tail -f "$PROJECT_DIR/logs"/*.log
        else
            echo "No logs found"
            echo "Start services with: ./scripts/start.sh"
            exit 1
        fi
        ;;
    *)
        echo "View logs from backend and frontend services"
        echo ""
        echo "Usage: ./scripts/logs.sh [backend|frontend|all]"
        echo ""
        echo "Examples:"
        echo "  ./scripts/logs.sh backend   - Show backend logs"
        echo "  ./scripts/logs.sh frontend  - Show frontend logs"
        echo "  ./scripts/logs.sh all       - Show all logs"
        echo ""
        exit 1
        ;;
esac
