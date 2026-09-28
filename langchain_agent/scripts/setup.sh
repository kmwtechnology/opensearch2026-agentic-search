#!/bin/bash
# Agentic Hybrid Search Setup Script
# One-time setup: configure environment, start Docker services, load the precomputed corpus
# shellcheck disable=SC2027,SC2086,SC2154,SC2289,SC1078,SC1079,SC1088,SC1036,SC2140

set -e  # Exit on error

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
PARENT_DIR="$(dirname "$PROJECT_DIR")"

# Setup logging
LOG_DIR="$PROJECT_DIR/logs"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/setup-$(date +%Y%m%d-%H%M%S).log"

# Function to log messages
log() {
    local msg="$1"
    local timestamp
    # shellcheck disable=SC2154
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo "[${timestamp}] $msg" | tee -a "$LOG_FILE"
}

# Step timing
STEP_START_TIME=""
CURRENT_STEP=""

# Function to start a step timer
start_step() {
    CURRENT_STEP="$1"
    STEP_START_TIME=$(date +%s)
}

# Function to end a step and report elapsed time
end_step() {
    if [ -z "$STEP_START_TIME" ]; then
        return
    fi
    local step_end_time
    step_end_time=$(date +%s)
    local elapsed=$((step_end_time - STEP_START_TIME))
    log "✓ $CURRENT_STEP — ${elapsed}s"
    echo "✓ $CURRENT_STEP — ${elapsed}s"
}

# Trap to show which step failed
# shellcheck disable=SC2064,SC2154
trap 'echo ""; log "❌ Setup failed at: $CURRENT_STEP"; echo "❌ Setup failed at: $CURRENT_STEP"; echo "   Check log: $LOG_FILE"; exit 1' ERR

log "🚀 Agentic Hybrid Search - Local Setup"
log "Log file: $LOG_FILE"
log ""

echo "🚀 Agentic Hybrid Search - Local Setup"
echo ""

# Handle help flag
if [[ "$1" == "-h" || "$1" == "--help" ]]; then
    cat << EOF
Usage: ./scripts/setup.sh [OPTIONS]

One-time setup for local development: configures environment, starts Docker services, and loads the precomputed corpus.

OPTIONS:
    -h, --help          Show this help message and exit
    --check-only        Check prerequisites only (no setup)

REQUIREMENTS:
    - Docker (for PostgreSQL + OpenSearch containers)
    - Python 3.14+ (creates .venv at project root if missing)
    - Node.js 24+ (for frontend; 24.21.0 or later)
    - Ollama, running natively (https://ollama.com) — every model is local;
      setup pulls qwen3.6:35b-a3b-q4_K_M (~23 GB) and nomic-embed-text if missing
    - ~26 GB disk space (models ~23 GB, precomputed corpus + Docker volumes)
    - Internet access (Git LFS pull for the committed corpus dump; Ollama model pulls)

WHAT THIS SCRIPT DOES:
    1. Checks prerequisites (Docker, Python 3.14+, Node.js 24+)
    2. Verifies the precomputed corpus dump in data/precomputed/ (committed via
       Git LFS; runs `git lfs pull` if the files are still LFS pointers)
    3. Creates Python virtual environment at project root (if not present)
    4. Creates .env file from .env.example (if not present)
    5. Installs Python dependencies in root .venv
    6. Installs Node.js frontend dependencies
    7. Starts PostgreSQL and OpenSearch containers
    8. Initializes database and OpenSearch index
    9. Loads ~158K ESCI products + judgments + color taxonomy into OpenSearch.
        Bulk-loads the permanent precomputed dump at data/precomputed/
        (~1-2 min; embeddings + attribute detection + seeded color taxonomy
        were already run once and committed via Git LFS — no Ollama call,
        no ingest pipeline runs locally any more). If data/precomputed/ is
        missing (Git LFS objects not pulled), setup fails with a clear
        `git lfs pull` message instead of falling back to anything. The
        "waterproof" type is deliberately NOT seeded — it starts empty and
        grows entirely from the live enrichment flywheel.

SERVICES STARTED:
    - PostgreSQL (checkpoint storage) → localhost:5432
    - OpenSearch (document search) → localhost:9200

REQUIREMENTS:
    Ollama running locally (no cloud API key is needed)

NEXT STEPS after setup:
    1. make dev (from langchain_agent/) — dev UI :5173 (backend :8080) + demo container :8000
    2. Visit http://localhost:5173 (dev) or http://localhost:8000 (demo)

For more information, see README.md

EOF
    exit 0
fi

# Parse flags
CHECK_ONLY=0
if [[ "$1" == "--check-only" ]]; then
    CHECK_ONLY=1
fi

# 1. Check prerequisites
start_step "Checking prerequisites"
log "📋 Checking prerequisites..."
echo "📋 Checking prerequisites..."

if ! command -v docker &> /dev/null; then
    log "❌ Docker not found"
    echo "❌ Docker not found"
    echo "   Please install Docker from https://www.docker.com/"
    exit 1
fi
log "✓ Docker found"
echo "✓ Docker found"

# `docker compose` (v2, the plugin) not `docker-compose` (v1) — every script
# in this repo uses the v2 subcommand form. An older Docker Desktop with only
# the v1 binary fails here with "docker: 'compose' is not a docker command"
# many steps later instead of a clear message now.
if ! docker compose version &> /dev/null; then
    log "❌ 'docker compose' (v2) not found"
    echo "❌ 'docker compose' (v2 plugin) not found — found only the legacy 'docker-compose'?"
    echo "   Update Docker Desktop to a version that bundles Compose v2."
    exit 1
fi
echo "✓ Docker Compose v2 found"

# git-lfs: without it, `git clone`/`git pull` silently leaves data/*.parquet
# as tiny ~130-byte pointer stubs instead of the real files — everything
# downstream (pyarrow) then fails with a confusing parse error instead of
# this clear one.
if ! command -v git-lfs &> /dev/null; then
    log "❌ git-lfs not found"
    echo "❌ git-lfs not found — required to pull the committed data/*.parquet files"
    echo "   Install with: brew install git-lfs && git lfs install"
    exit 1
fi
echo "✓ git-lfs found"

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    echo "   Please install Python 3.14+ from https://www.python.org/"
    exit 1
fi

# Check Python version (must be 3.14+)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 14 ]; }; then
    echo "❌ Python version too old: $PYTHON_VERSION"
    echo "   Required: Python 3.14+"
    exit 1
fi
echo "✓ Python $PYTHON_VERSION found"

if ! command -v node &> /dev/null; then
    echo "❌ Node.js not found"
    echo "   Please install Node.js 24+ from https://nodejs.org/"
    exit 1
fi

# Check Node version (must be 24+)
NODE_VERSION=$(node --version 2>&1 | sed 's/v//')
NODE_MAJOR=$(echo "$NODE_VERSION" | cut -d. -f1)
if [ "$NODE_MAJOR" -lt 24 ]; then
    echo "❌ Node version too old: $NODE_VERSION"
    echo "   Required: Node.js 24+ (24.21.0 or later — earlier 24.x had a broken npm)"
    exit 1
fi
echo "✓ Node.js $NODE_VERSION found"

# Ollama: every model runs locally (#148). Must be native on the host, not in
# Docker -- on macOS only a native install gets the Metal GPU.
if ! command -v ollama &> /dev/null; then
    echo "❌ Ollama not found"
    echo "   Install from https://ollama.com (native app), then re-run."
    exit 1
fi
if ! curl -sf "${OLLAMA_HOST:-http://localhost:11434}/api/tags" > /dev/null; then
    echo "❌ Ollama is installed but not running"
    echo "   Start the Ollama app (or: ollama serve), then re-run."
    exit 1
fi
echo "✓ Ollama running"

# Backend (8080) / frontend (5173) are started natively by `make dev`, not by
# Docker Compose — something already bound to either port (a stale process
# from a prior session, another project) fails later with a bare
# "Address already in use" / EADDRINUSE. Warn now, non-fatally, with the PID
# so it's a one-line fix instead of a mid-startup mystery. (:8000 belongs to
# the demo container and is Docker-managed.)
for port_check in "8080:backend" "5173:frontend"; do
    port="${port_check%%:*}"; label="${port_check#*:}"
    pid="$(lsof -tiTCP:"$port" -sTCP:LISTEN 2>/dev/null | head -1)"
    if [ -n "$pid" ]; then
        echo "⚠ Port $port ($label) is already in use by PID $pid ($(ps -p "$pid" -o comm= 2>/dev/null))"
        echo "   'make dev' will fail with 'Address already in use' unless this is freed first: kill $pid"
    fi
done

end_step

echo ""

# Exit early if --check-only was specified
if [ $CHECK_ONLY -eq 1 ]; then
    echo "✅ All prerequisites met!"
    exit 0
fi

# 2. Ensure the precomputed corpus dump is present. It is committed via Git LFS
# (data/precomputed/); the products index, judgments and color taxonomy are all
# bulk-loaded from it by setup.py. There is no rebuild path -- if it's missing
# the only fix is `git lfs pull`.
start_step "Checking for the precomputed corpus dump"
log "Step 2: Checking for the precomputed corpus dump..."
echo "📦 Checking for the precomputed corpus dump..."

DUMP_DIR="$PARENT_DIR/data/precomputed"
DUMP_FILE="$DUMP_DIR/products_dump.parquet"

# An un-smudged LFS file is a small text pointer ("version https://git-lfs...")
# rather than real parquet bytes -- treat that the same as "missing".
is_real_parquet() {
    [ -f "$1" ] && [ "$(head -c 7 "$1" 2>/dev/null)" != "version" ]
}

if ! is_real_parquet "$DUMP_FILE" || [ ! -f "$DUMP_DIR/dump_metadata.json" ]; then
    log "   data/precomputed/ missing or still LFS pointers — running 'git lfs pull'"
    echo "   data/precomputed/ missing or still LFS pointers — running 'git lfs pull'"
    (cd "$PARENT_DIR" && git lfs pull) || true
fi

if is_real_parquet "$DUMP_FILE" && [ -f "$DUMP_DIR/dump_metadata.json" ]; then
    FILE_SIZE=$(du -h "$DUMP_FILE" | cut -f1)
    log "✓ Precomputed corpus dump present ($FILE_SIZE)"
    echo "✓ Precomputed corpus dump present ($FILE_SIZE)"
else
    echo "❌ data/precomputed/ is still missing after 'git lfs pull'."
    echo "   The corpus is a permanent one-time export; there is no way to rebuild it locally."
    echo "   Check that git-lfs is installed and you have access to the repo's LFS objects."
    exit 1
fi

end_step
echo ""

# 3. Create .env from the example if missing
start_step "Configuring environment"
echo "📝 Configuring environment..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"
    echo "   ✓ Created .env from .env.example"
else
    echo "   ✓ Using existing .env"
fi

# Pull the local models if missing (idempotent; the chat model is ~23 GB, so
# the first run takes a while). Names come from .env, defaults from .env.example.
env_model() {
    local v
    v=$(grep -E "^$1=" "$PROJECT_DIR/.env" | head -1 | cut -d'=' -f2- | sed 's/#.*//; s/[[:space:]]*$//')
    echo "${v:-$2}"
}
for model in "$(env_model LLM_MODEL qwen3.6:35b-a3b-q4_K_M)" "$(env_model EMBEDDINGS_MODEL nomic-embed-text)"; do
    if ollama list | awk 'NR>1 {print $1}' | grep -qE "^${model}(:latest)?$"; then
        echo "   ✓ Ollama model present: $model"
    else
        echo "   Pulling Ollama model: $model ..."
        ollama pull "$model"
    fi
done

end_step
echo ""

# 4. Create and setup .venv
start_step "Creating Python virtual environment"
log "Step 4: Creating Python virtual environment..."
echo "📦 Python Virtual Environment..."

VENV_PATH="$PROJECT_DIR/.venv"
if [ ! -d "$VENV_PATH" ]; then
    log "   Creating venv at $VENV_PATH..."
    echo "   Creating virtual environment at $VENV_PATH..."
    if python3 -m venv "$VENV_PATH"; then
        log "   ✓ Virtual environment created"
        echo "   ✓ Virtual environment created"
    else
        log "   ❌ Failed to create virtual environment"
        echo "   ❌ Failed to create virtual environment"
        exit 1
    fi
else
    echo "   ✓ Virtual environment exists"
fi

log "   Activating venv and installing dependencies..."
echo "   Installing dependencies..."
# shellcheck source=/dev/null
source "$VENV_PATH/bin/activate"
pip install -q --upgrade pip setuptools wheel
pip install -q -r "$PROJECT_DIR/requirements.txt"
pip install -q -r "$PROJECT_DIR/requirements-dev.txt"
log "✓ Python dependencies installed (including dev tools: black, isort, flake8, pytest)"
echo "✓ Python dependencies installed (including dev tools: black, isort, flake8, pytest)"

# Install the pre-commit hook (scripts/pre-commit.sh) so black/isort/flake8
# actually run locally instead of only being caught by CI. Only ever
# installed here, on a fresh/updated venv — never overwrite a hook a
# developer wrote themselves that happens to share the filename.
GIT_HOOKS_DIR="$PARENT_DIR/.git/hooks"
PRE_COMMIT_HOOK="$GIT_HOOKS_DIR/pre-commit"
if [ -d "$GIT_HOOKS_DIR" ]; then
    if [ ! -e "$PRE_COMMIT_HOOK" ] || grep -q "Mirrors ci-format + lint steps in Makefile" "$PRE_COMMIT_HOOK" 2>/dev/null; then
        cp "$SCRIPT_DIR/pre-commit.sh" "$PRE_COMMIT_HOOK"
        chmod +x "$PRE_COMMIT_HOOK"
        log "✓ Installed pre-commit hook (black + isort + flake8 on staged .py files)"
        echo "✓ Installed pre-commit hook (black + isort + flake8 on staged .py files)"
    else
        log "   Existing .git/hooks/pre-commit is not ours — left untouched"
        echo "   ⚠ .git/hooks/pre-commit already exists and isn't ours — left untouched"
        echo "     (see scripts/pre-commit.sh if you want to install it manually)"
    fi
else
    log "   No .git/hooks directory found — skipping pre-commit hook install"
fi

end_step
echo ""

# 5. Install frontend dependencies
start_step "Installing frontend dependencies"
echo "📦 Installing frontend dependencies..."

cd "$PROJECT_DIR/web"
if [ ! -d "node_modules" ]; then
    npm install --quiet
    echo "✓ Frontend dependencies installed"
else
    echo "✓ Frontend dependencies already installed"
fi
cd "$PROJECT_DIR"

end_step
echo ""

# 6. Start Docker containers (PostgreSQL + OpenSearch)
start_step "Starting Docker containers"
log "Step 6: Starting Docker containers..."
echo "🐘 Starting Docker containers..."

cd "$PARENT_DIR"
if ! docker compose ps 2>/dev/null | grep -q "postgres.*Up"; then
    log "   Starting PostgreSQL..."
    echo "   Starting PostgreSQL..."
    docker compose up -d postgres > /dev/null 2>&1
    echo "   Waiting for PostgreSQL to be ready..."
    sleep 3
    log "✓ PostgreSQL started"
    echo "✓ PostgreSQL started"
else
    log "✓ PostgreSQL already running"
    echo "✓ PostgreSQL already running"
fi

if ! docker compose ps 2>/dev/null | grep -q "opensearch.*Up"; then
    log "   Starting OpenSearch..."
    echo "   Starting OpenSearch..."
    docker compose up -d opensearch > /dev/null 2>&1
    echo "   Waiting for OpenSearch to be ready..."
    for i in {1..30}; do
        if curl -s http://localhost:9200/_cluster/health 2>/dev/null | grep -q '"status"'; then
            log "✓ OpenSearch started"
            echo "✓ OpenSearch started"
            break
        fi
        if [ "$i" -eq 30 ]; then
            log "❌ OpenSearch failed to start within 30 seconds"
            echo "❌ OpenSearch failed to start within 30 seconds"
            echo "   Check: docker compose logs opensearch"
            exit 1
        fi
        sleep 2
    done
else
    log "✓ OpenSearch already running"
    echo "✓ OpenSearch already running"
fi

cd "$PROJECT_DIR"

end_step
echo ""

# 7. Initialize database and OpenSearch index, then bulk-load the precomputed corpus
start_step "Initializing database, OpenSearch, and loading the corpus"
log "Step 7: Initializing database, OpenSearch, and loading the corpus..."
echo "💾 Initializing database, OpenSearch, and loading the corpus..."

# shellcheck source=/dev/null
source "$PROJECT_DIR/.venv/bin/activate"
cd "$PROJECT_DIR" || exit 1

mkdir -p logs
log "   Running: python setup.py"
PYTHONPATH=. python setup.py 2>&1 | tee -a logs/setup.log

if [ "${PIPESTATUS[0]}" -eq 0 ]; then
    echo ""
    log "✓ Database initialization complete"
    echo "✓ Database initialization complete"
    end_step
else
    echo ""
    log "✗ Setup failed during database initialization"
    echo "✗ Setup failed during database initialization"
    echo "   Check log: $LOG_FILE"
    echo "   You can retry with: cd $PROJECT_DIR && PYTHONPATH=. python setup.py"
    exit 1
fi

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "  1. cd langchain_agent && make dev   (dev UI :5173 + backend :8080, demo container :8000)"
echo "  2. Visit http://localhost:5173 (dev) or http://localhost:8000 (demo)"
echo ""
echo "Services running at:"
echo "  • Dev UI: http://localhost:5173  (backend http://localhost:8080)"
echo "  • Demo:   http://localhost:8000"
echo "  • OpenSearch: http://localhost:9200"
