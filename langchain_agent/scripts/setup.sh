#!/bin/bash
# First-time setup (make setup): prerequisites, .env, Ollama models, .venv, frontend deps,
# Docker services, then setup.py creates the schema and bulk-loads the precomputed corpus.
# Takes no arguments. To start over: make teardown, then make setup.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

mkdir -p "$PROJECT_DIR/logs"
LOG_FILE="$PROJECT_DIR/logs/setup-$(date +%Y%m%d-%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

CURRENT_STEP=""
step() {
    CURRENT_STEP="$1"
    echo ""
    echo "▶ $CURRENT_STEP"
}
fail() {
    echo "❌ $1"
    shift
    for line in "$@"; do echo "   $line"; done
    exit 1
}
trap 'echo ""; echo "❌ Setup failed at: $CURRENT_STEP (log: $LOG_FILE)"' ERR

echo "🚀 Agentic Hybrid Search - Local Setup"

# 1. Prerequisites
step "Checking prerequisites"

command -v docker &> /dev/null || fail "Docker not found" "Install from https://www.docker.com/"
docker compose version &> /dev/null \
    || fail "'docker compose' (v2 plugin) not found" "Update Docker Desktop to a version that bundles Compose v2."
command -v git-lfs &> /dev/null \
    || fail "git-lfs not found — the corpus ships through Git LFS" "brew install git-lfs && git lfs install"
echo "✓ Docker, Compose v2, git-lfs"

command -v python3 &> /dev/null || fail "Python 3 not found" "Install Python 3.14+ from https://www.python.org/"
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 14) else 1)' \
    || fail "Python $PYTHON_VERSION is too old" "Required: Python 3.14+"
echo "✓ Python $PYTHON_VERSION"

command -v node &> /dev/null || fail "Node.js not found" "Install Node.js 24+ from https://nodejs.org/"
NODE_VERSION=$(node --version | sed 's/v//')
[ "${NODE_VERSION%%.*}" -ge 24 ] \
    || fail "Node $NODE_VERSION is too old" "Required: Node.js 24+ (24.21.0 or later — earlier 24.x had a broken npm)"
echo "✓ Node.js $NODE_VERSION"

# Ollama must be native: on macOS only a native install gets the Metal GPU.
command -v ollama &> /dev/null || fail "Ollama not found" "Install the native app from https://ollama.com, then re-run."
curl -sf "${OLLAMA_HOST:-http://localhost:11434}/api/tags" > /dev/null \
    || fail "Ollama is installed but not running" "Start the Ollama app (or: ollama serve), then re-run."
echo "✓ Ollama running"

# :8080 (backend) and :5173 (Vite) belong to `make dev`; warn now instead of a mid-startup EADDRINUSE.
# (:8000 is the demo container, Docker-managed.)
for port_check in "8080:backend" "5173:frontend"; do
    port="${port_check%%:*}"
    pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)"
    if [ -n "$pid" ]; then
        echo "⚠ Port $port (${port_check#*:}) is in use by PID $pid ($(ps -p "$pid" -o comm= 2>/dev/null)) — 'make dev' will fail until it is freed"
    fi
done

# 2. The precomputed corpus (Git LFS). There is no rebuild path: if it's missing, `git lfs pull` is the only fix.
step "Checking the precomputed corpus dump"
DUMP_DIR="$PARENT_DIR/data/precomputed"
DUMP_FILE="$DUMP_DIR/products_dump.parquet"

# An un-smudged LFS file is a small text pointer ("version https://git-lfs...") — treat it as missing.
is_real_parquet() {
    [ -f "$1" ] && [ "$(head -c 7 "$1" 2>/dev/null)" != "version" ]
}

if ! is_real_parquet "$DUMP_FILE" || [ ! -f "$DUMP_DIR/dump_metadata.json" ]; then
    echo "data/precomputed/ missing or still LFS pointers — running 'git lfs pull'"
    (cd "$PARENT_DIR" && git lfs pull) || true
fi
is_real_parquet "$DUMP_FILE" && [ -f "$DUMP_DIR/dump_metadata.json" ] \
    || fail "data/precomputed/ is still missing after 'git lfs pull'" \
        "The corpus is a permanent one-time export; it cannot be rebuilt locally." \
        "Check that git-lfs is installed and you have access to the repo's LFS objects."
echo "✓ Precomputed corpus dump present ($(du -h "$DUMP_FILE" | cut -f1))"

# 3. .env and Ollama models
step "Configuring environment"
if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "✓ Created .env from .env.example"
else
    echo "✓ Using existing .env"
fi

# Pull the local models if missing (the chat model is ~23 GB). Names come from .env.
env_model() {
    local v
    v=$(grep -E "^$1=" "$PROJECT_DIR/.env" | head -1 | cut -d'=' -f2- | sed 's/#.*//; s/[[:space:]]*$//')
    echo "${v:-$2}"
}
for model in "$(env_model LLM_MODEL qwen3.6:35b-a3b-q4_K_M)" "$(env_model EMBEDDINGS_MODEL nomic-embed-text)"; do
    if ollama list | awk 'NR>1 {print $1}' | grep -qE "^${model}(:latest)?$"; then
        echo "✓ Ollama model present: $model"
    else
        echo "Pulling Ollama model: $model ..."
        ollama pull "$model"
    fi
done

# 4. Python environment
step "Creating the Python virtual environment"
VENV_PATH="$PROJECT_DIR/.venv"
[ -d "$VENV_PATH" ] || python3 -m venv "$VENV_PATH"
# shellcheck source=/dev/null
source "$VENV_PATH/bin/activate"
pip install -q --upgrade pip setuptools wheel
pip install -q -r "$PROJECT_DIR/requirements.txt" -r "$PROJECT_DIR/requirements-dev.txt"
echo "✓ Python dependencies installed (including black, isort, flake8, pytest)"

# Install the pre-commit hook unless the developer already has their own.
GIT_HOOKS_DIR="$PARENT_DIR/.git/hooks"
PRE_COMMIT_HOOK="$GIT_HOOKS_DIR/pre-commit"
if [ -d "$GIT_HOOKS_DIR" ]; then
    if [ ! -e "$PRE_COMMIT_HOOK" ] || grep -q "Mirrors ci-format + lint steps in Makefile" "$PRE_COMMIT_HOOK" 2>/dev/null; then
        cp "$SCRIPT_DIR/pre-commit.sh" "$PRE_COMMIT_HOOK"
        chmod +x "$PRE_COMMIT_HOOK"
        echo "✓ Installed pre-commit hook (black + isort + flake8 on staged .py files)"
    else
        echo "⚠ .git/hooks/pre-commit already exists and isn't ours — left untouched (see scripts/pre-commit.sh)"
    fi
fi

# 5. Frontend
step "Installing frontend dependencies"
(cd "$PROJECT_DIR/web" && npm install --quiet)
echo "✓ Frontend dependencies installed"

# 6. PostgreSQL + OpenSearch
step "Starting Docker services (PostgreSQL + OpenSearch)"
(cd "$PARENT_DIR" && docker compose up -d --wait postgres opensearch)
echo "✓ PostgreSQL and OpenSearch healthy"

# 7. Schema + corpus load (setup.py creates the tables, index, and search pipeline, then runs the bulk loader)
step "Initializing the database and loading the corpus"
cd "$PROJECT_DIR"
PYTHONPATH=. python setup.py

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next: make dev   (dev UI http://localhost:5173, backend :8080, demo http://localhost:8000)"
