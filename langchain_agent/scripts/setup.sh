#!/bin/bash
# Agentic Hybrid Search Setup Script
# One-time setup: configure environment, start Docker services, ingest ESCI products
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

One-time setup for local development: configures environment, starts Docker services, and ingests ESCI products.

OPTIONS:
    -h, --help          Show this help message and exit
    --check-only        Check prerequisites only (no setup)

REQUIREMENTS:
    - Docker (for PostgreSQL + OpenSearch containers)
    - Python 3.13+ (creates .venv at project root if missing)
    - Node.js 24+ (for frontend; 24.21.0 or later)
    - Google API Key (for Gemini embeddings and LLM)
    - ~1.5 GB disk space (ESCI dataset + sample parquet + Docker volumes)
    - Internet access (to clone ESCI dataset repo from GitHub)

WHAT THIS SCRIPT DOES:
    1. Checks prerequisites (Docker, Python 3.13+, Node.js 24+)
    2. Clones ESCI dataset repo (if not present) → ../esci/
    3. Creates Python virtual environment at project root (if not present)
    4. Creates .env file and configures Google API key (if not present)
    5. Creates frontend .env configuration
    6. Installs Python dependencies in root .venv
    7. Installs Node.js frontend dependencies
    8. Starts PostgreSQL and OpenSearch containers
    9. Initializes database and OpenSearch index
    10. Runs Lucille ETL to ingest precomputed 10K ESCI products + judgments into OpenSearch
        (reads from data/esci_products_sample_10000.parquet — no API calls needed),
        including a mandatory color/material taxonomy discovery + reindex pass
        (a fresh cluster's taxonomy store is otherwise empty, so every
        color/material attribute_filter query would return zero results)

SERVICES STARTED:
    - PostgreSQL (checkpoint storage) → localhost:5432
    - OpenSearch (document search) → localhost:9200

REQUIREMENTS:
    GOOGLE_API_KEY must be set in .env file
    Get your key from: https://aistudio.google.com/apikey

NEXT STEPS after setup:
    1. Start backend: make dev-api (from langchain_agent/)
    2. Start frontend: make dev-web (from langchain_agent/)
    3. Visit http://localhost:5173

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

if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 not found"
    echo "   Please install Python 3.13+ from https://www.python.org/"
    exit 1
fi

# Check Python version (must be 3.13+)
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null)
PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 13 ]; }; then
    echo "❌ Python version too old: $PYTHON_VERSION"
    echo "   Required: Python 3.13+"
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

# Lucille ETL ingest (called by setup.py) runs via Docker by default
# (LUCILLE_USE_DOCKER, see lucille_ingest.sh) — Docker was already checked
# above, so Java/Maven aren't needed. Only enforce them when the native path
# is explicitly requested.
if [ "${LUCILLE_USE_DOCKER:-true}" = "false" ]; then
    if ! command -v java &> /dev/null; then
        echo "❌ Java not found"
        echo "   Java 21+ is required for the native Lucille ETL path (LUCILLE_USE_DOCKER=false)."
        echo "   Install with: brew install openjdk@21"
        exit 1
    fi
    JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
    if [ "${JAVA_VER:-0}" -lt 21 ]; then
        echo "❌ Java version too old: $JAVA_VER (need 21+)"
        echo "   Install with: brew install openjdk@21"
        exit 1
    fi
    echo "✓ Java $JAVA_VER found"

    if ! command -v mvn &> /dev/null; then
        echo "❌ Maven not found"
        echo "   Maven 3.8+ is required for the native Lucille ETL path (LUCILLE_USE_DOCKER=false)."
        echo "   Install with: brew install maven"
        exit 1
    fi
    echo "✓ Maven found"
else
    echo "✓ Lucille ETL will run via Docker (no local Java/Maven needed)"
fi

end_step

echo ""

# Exit early if --check-only was specified
if [ $CHECK_ONLY -eq 1 ]; then
    echo "✅ All prerequisites met!"
    exit 0
fi

# 2. Setup ESCI dataset repository
start_step "Setting up ESCI dataset repository"
log "Step 2: Setting up ESCI dataset repository..."
echo "📦 Setting up ESCI dataset..."

ESCI_REPO_DIR="$PARENT_DIR/esci"
ESCI_FILE="$ESCI_REPO_DIR/shopping_queries_dataset/shopping_queries_dataset_products.parquet"

if [ ! -d "$ESCI_REPO_DIR" ]; then
    log "   🌐 Cloning ESCI dataset from GitHub (~1.5 GB)... this is a one-time download (2-5 min)"
    echo "   🌐 Cloning ESCI dataset from GitHub (~1.5 GB)... this is a one-time download (2-5 min)"
    if git clone https://github.com/amazon-science/esci-data.git "$PARENT_DIR/esci"; then
        log "   ✓ ESCI dataset cloned successfully"
        echo "   ✓ ESCI dataset cloned successfully"
    else
        log "   ❌ Failed to clone ESCI dataset"
        echo "   ❌ Failed to clone ESCI dataset"
        echo "      GitHub: https://github.com/amazon-science/esci-data"
        echo "      Manual download: Extract shopping_queries_dataset/ to ../esci/"
        exit 1
    fi
else
    log "✓ ESCI dataset directory exists"
    echo "✓ ESCI dataset directory exists"
fi

if [ -f "$ESCI_FILE" ]; then
    FILE_SIZE=$(du -h "$ESCI_FILE" | cut -f1)
    log "✓ ESCI dataset file found ($FILE_SIZE)"
    echo "✓ ESCI dataset file found ($FILE_SIZE)"
else
    log "❌ ESCI dataset parquet file not found at: $ESCI_FILE"
    echo "❌ ESCI dataset parquet file not found at:"
    echo "   $ESCI_FILE"
    echo "   Ensure shopping_queries_dataset_products.parquet is in: $ESCI_REPO_DIR/shopping_queries_dataset/"
    exit 1
fi

end_step
echo ""

# 3. Generate API key if .env doesn't exist
start_step "Configuring environment"
echo "📝 Configuring environment..."

if [ ! -f "$PROJECT_DIR/.env" ]; then
    echo "   Creating .env file..."
    cp "$PROJECT_DIR/.env.example" "$PROJECT_DIR/.env"

    # Generate API key
    API_KEY=$(openssl rand -hex 32)

    # Use sed to replace the placeholders (works on both macOS and Linux).
    if [[ "$OSTYPE" == "darwin"* ]]; then
        sed -i '' "s/your-secure-api-key-here/$API_KEY/" "$PROJECT_DIR/.env"
    else
        sed -i "s/your-secure-api-key-here/$API_KEY/" "$PROJECT_DIR/.env"
    fi

    echo "   ✓ Generated API_KEY"
    echo ""
    echo "   ERROR: GOOGLE_API_KEY is required. Set it in .env before running."
    echo "   Get your key from: https://aistudio.google.com/apikey"
    exit 1
else
    # Extract existing API_KEY
    API_KEY=$(grep "^API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    echo "   ✓ Using existing API_KEY"

    # Check if GOOGLE_API_KEY is still the placeholder
    EXISTING_GOOGLE_KEY=$(grep "^GOOGLE_API_KEY=" "$PROJECT_DIR/.env" | cut -d'=' -f2)
    if [ "$EXISTING_GOOGLE_KEY" = "your-google-api-key-here" ] || [ -z "$EXISTING_GOOGLE_KEY" ]; then
        echo "   ERROR: GOOGLE_API_KEY is required. Set it in .env before running."
        echo "   Get your key from: https://aistudio.google.com/apikey"
        exit 1
    else
        echo "   ✓ Using existing GOOGLE_API_KEY"
    fi
fi

# 3. Create frontend .env (if missing)
if [ ! -f "$PROJECT_DIR/web/.env" ]; then
    echo "   Creating web/.env..."
    cat > "$PROJECT_DIR/web/.env" << EOF
# Vite proxy in vite.config.ts routes /api and /ws to localhost:8000
# No VITE_API_URL needed for local dev (empty = relative URLs through proxy)
EOF
    echo "   ✓ Frontend env configured"
else
    echo "   ✓ Frontend env exists"
fi

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

# 7. Initialize database, OpenSearch index, and ingest ESCI products
# setup.py handles everything: DB init, index creation, API validation, and product ingestion
start_step "Initializing database, OpenSearch, and ingesting products"
log "Step 7: Initializing database, OpenSearch, and ingesting products..."
echo "💾 Initializing database, OpenSearch, and ingesting products..."

# shellcheck source=/dev/null
source "$PROJECT_DIR/.venv/bin/activate"
cd "$PROJECT_DIR" || exit 1

mkdir -p logs
log "   Running: python setup.py"
PYTHONPATH=. python setup.py 2>&1 | tee -a logs/setup.log

if [ "${PIPESTATUS[0]}" -eq 0 ]; then
    echo ""
    SAMPLE_FILE="$PARENT_DIR/esci/shopping_queries_dataset/esci_products_sample_10000.parquet"
    if [ -f "$SAMPLE_FILE" ]; then
        SAMPLE_SIZE=$(du -h "$SAMPLE_FILE" | cut -f1)
        log "✓ 10K product sample: $SAMPLE_SIZE"
        echo "✓ 10K product sample: $SAMPLE_SIZE"
    fi
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
echo "  1. Start backend:  cd langchain_agent && make dev-api"
echo "  2. Start frontend: cd langchain_agent && make dev-web"
echo "  3. Visit http://localhost:5173"
echo ""
echo "Services running at:"
echo "  • Backend API: http://localhost:8000"
echo "  • Frontend: http://localhost:5173"
echo "  • OpenSearch: http://localhost:9200"
