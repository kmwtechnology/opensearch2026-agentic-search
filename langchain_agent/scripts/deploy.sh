#!/bin/bash
# Agentic Hybrid Search — Google Cloud Run Deployment Script
# Deploys the application to Cloud Run with Cloud SQL (PostgreSQL for checkpoints)
# and hosted OpenSearch (document search).
#
# Prerequisites:
#   - Google Cloud CLI (gcloud) installed and authenticated
#   - Docker installed (for local builds, optional with Cloud Build)
#   - A GCP project with billing enabled
#   - OpenSearch instance accessible (hosted at 34.138.97.13:9200)
#
# Usage:
#   ./scripts/deploy.sh                    # Interactive deploy (prompts for project)
#   ./scripts/deploy.sh --project my-proj  # Deploy to specific project
#   ./scripts/deploy.sh --dry-run          # Show what would be done

set -euo pipefail

# ============================================================================
# CONFIGURATION — Edit these for your deployment
# ============================================================================

REGION="us-central1"
SERVICE_NAME="agentic-hybrid-search"
CLOUD_SQL_INSTANCE="agentic-hybrid-search-db"
DB_NAME="langchain_agent"
DB_USER="postgres"
ARTIFACT_REPO="agentic-hybrid-search"
MEMORY="2048Mi"
CPU="2"
MIN_INSTANCES="0"
MAX_INSTANCES="2"
CONCURRENCY="80"

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

PROJECT_ID=""
DRY_RUN=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            cat << 'EOF'
Usage: ./scripts/deploy.sh [OPTIONS]

Deploy Agentic Hybrid Search to Google Cloud Run.

Cloud SQL (PostgreSQL) is used for LangGraph checkpoints only.
Document search uses hosted OpenSearch (configured via env vars).

OPTIONS:
    --project PROJECT_ID   GCP project ID (otherwise uses gcloud default)
    --dry-run              Show commands without executing
    -h, --help             Show this help message

WHAT THIS SCRIPT DOES:
    1. Validates gcloud CLI and project configuration
    2. Enables required GCP APIs
    3. Creates Artifact Registry repository
    4. Creates Cloud SQL PostgreSQL instance (for checkpoints)
    5. Stores secrets in Secret Manager
    6. Builds and pushes Docker image to Artifact Registry
    7. Deploys to Cloud Run with Cloud SQL + OpenSearch connection
    8. Prints the service URL

ESTIMATED MONTHLY COST (idle / light dev use):
    Cloud SQL db-f1-micro:  ~$7-10/mo
    Cloud Run (scale to 0):  ~$0-5/mo
    Artifact Registry:       ~$0.10/mo
    Secret Manager:          ~$0.06/mo
    Total:                   ~$8-16/mo

FIRST-TIME SETUP:
    After deploy, run gcp-init.sh to initialize Cloud SQL tables
    and ingest ESCI product data into OpenSearch.

EOF
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

# ============================================================================
# HELPERS
# ============================================================================

log() { echo "==> $*"; }
warn() { echo "WARNING: $*" >&2; }
err() { echo "ERROR: $*" >&2; exit 1; }

run() {
    if $DRY_RUN; then
        echo "[DRY RUN] $*"
    else
        "$@"
    fi
}

# ============================================================================
# STEP 0: VALIDATE PREREQUISITES
# ============================================================================

log "Checking prerequisites..."

if ! command -v gcloud &> /dev/null; then
    err "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
fi

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
    if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
        err "No GCP project set. Use --project PROJECT_ID or run: gcloud config set project PROJECT_ID"
    fi
fi

log "Using project: $PROJECT_ID"
log "Using region:  $REGION"

# Get project number for IAM bindings
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)" 2>/dev/null) || \
    err "Cannot access project $PROJECT_ID. Check permissions and billing."

COMPUTE_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
IMAGE_URI="${REGION}-docker.pkg.dev/${PROJECT_ID}/${ARTIFACT_REPO}/${SERVICE_NAME}:latest"
CLOUD_SQL_CONNECTION="${PROJECT_ID}:${REGION}:${CLOUD_SQL_INSTANCE}"

echo ""
log "Configuration:"
echo "    Service:          $SERVICE_NAME"
echo "    Cloud SQL:        $CLOUD_SQL_INSTANCE"
echo "    Image:            $IMAGE_URI"
echo "    SQL Connection:   $CLOUD_SQL_CONNECTION"
echo ""

# ============================================================================
# STEP 1: ENABLE REQUIRED APIS
# ============================================================================

log "Enabling required GCP APIs..."

APIS=(
    "run.googleapis.com"
    "cloudbuild.googleapis.com"
    "artifactregistry.googleapis.com"
    "sqladmin.googleapis.com"
    "secretmanager.googleapis.com"
    "sql-component.googleapis.com"
)

for api in "${APIS[@]}"; do
    run gcloud services enable "$api" --project="$PROJECT_ID" --quiet
done

log "APIs enabled."

# ============================================================================
# STEP 2: CREATE ARTIFACT REGISTRY REPOSITORY
# ============================================================================

log "Setting up Artifact Registry..."

if ! gcloud artifacts repositories describe "$ARTIFACT_REPO" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    run gcloud artifacts repositories create "$ARTIFACT_REPO" \
        --repository-format=docker \
        --location="$REGION" \
        --project="$PROJECT_ID" \
        --description="Agentic Hybrid Search container images"
    log "Artifact Registry repository created."
else
    log "Artifact Registry repository already exists."
fi

# ============================================================================
# STEP 3: CREATE CLOUD SQL INSTANCE
# ============================================================================

log "Setting up Cloud SQL PostgreSQL instance (checkpoints only)..."

if $DRY_RUN; then
    run gcloud sql instances create "$CLOUD_SQL_INSTANCE" \
        --project="$PROJECT_ID" --region="$REGION" --database-version=POSTGRES_16 \
        --edition=enterprise --tier=db-f1-micro --storage-size=10GB --storage-auto-increase \
        --availability-type=zonal --no-backup \
        --database-flags=max_connections=100
    run gcloud sql users set-password "$DB_USER" \
        --instance="$CLOUD_SQL_INSTANCE" --project="$PROJECT_ID" --password=GENERATED
    run gcloud secrets create agentic-hybrid-search-db-password --data-file=- --project="$PROJECT_ID"
    run gcloud sql databases create "$DB_NAME" \
        --instance="$CLOUD_SQL_INSTANCE" --project="$PROJECT_ID"
elif ! gcloud sql instances describe "$CLOUD_SQL_INSTANCE" \
    --project="$PROJECT_ID" &>/dev/null; then

    log "Creating Cloud SQL instance (this takes 3-5 minutes)..."
    gcloud sql instances create "$CLOUD_SQL_INSTANCE" \
        --project="$PROJECT_ID" \
        --region="$REGION" \
        --database-version=POSTGRES_16 \
        --edition=enterprise \
        --tier=db-f1-micro \
        --storage-size=10GB \
        --storage-auto-increase \
        --availability-type=zonal \
        --no-backup \
        --database-flags=max_connections=100

    log "Cloud SQL instance created."

    # Set postgres user password
    DB_PASSWORD=$(openssl rand -base64 24 | tr -dc 'a-zA-Z0-9' | head -c 24)
    gcloud sql users set-password "$DB_USER" \
        --instance="$CLOUD_SQL_INSTANCE" \
        --project="$PROJECT_ID" \
        --password="$DB_PASSWORD"

    log "Database password set. Storing in Secret Manager..."

    # Store DB password in Secret Manager
    if ! gcloud secrets describe agentic-hybrid-search-db-password \
        --project="$PROJECT_ID" &>/dev/null; then
        echo -n "$DB_PASSWORD" | gcloud secrets create agentic-hybrid-search-db-password \
            --data-file=- \
            --project="$PROJECT_ID"
    else
        echo -n "$DB_PASSWORD" | gcloud secrets versions add agentic-hybrid-search-db-password \
            --data-file=- \
            --project="$PROJECT_ID"
    fi
else
    log "Cloud SQL instance already exists."
    # Retrieve existing password from Secret Manager
    DB_PASSWORD=$(gcloud secrets versions access latest \
        --secret=agentic-hybrid-search-db-password \
        --project="$PROJECT_ID" 2>/dev/null) || \
        warn "Could not retrieve DB password from Secret Manager. You may need to set it manually."
fi

# ============================================================================
# STEP 4: CREATE DATABASE
# ============================================================================

if ! $DRY_RUN; then
    log "Creating database..."

    # Check if database exists
    if ! gcloud sql databases describe "$DB_NAME" \
        --instance="$CLOUD_SQL_INSTANCE" \
        --project="$PROJECT_ID" &>/dev/null; then
        gcloud sql databases create "$DB_NAME" \
            --instance="$CLOUD_SQL_INSTANCE" \
            --project="$PROJECT_ID"
        log "Database '$DB_NAME' created."
    else
        log "Database '$DB_NAME' already exists."
    fi
fi

# ============================================================================
# STEP 5: STORE SECRETS IN SECRET MANAGER
# ============================================================================

log "Configuring Secret Manager..."

store_secret() {
    local name="$1"
    local prompt="$2"

    if $DRY_RUN; then
        echo "[DRY RUN] gcloud secrets create $name --data-file=- --project=$PROJECT_ID"
        return
    fi

    if ! gcloud secrets describe "$name" --project="$PROJECT_ID" &>/dev/null; then
        echo ""
        read -rsp "    Enter $prompt: " secret_value
        echo ""
        if [ -z "$secret_value" ]; then
            warn "No value provided for $name. Set it later with:"
            echo "    echo -n 'VALUE' | gcloud secrets create $name --data-file=- --project=$PROJECT_ID"
            return
        fi
        echo -n "$secret_value" | gcloud secrets create "$name" \
            --data-file=- \
            --project="$PROJECT_ID"
        log "Secret '$name' created."
    else
        log "Secret '$name' already exists."
    fi
}

store_secret "agentic-hybrid-search-google-api-key" "GOOGLE_API_KEY (from https://aistudio.google.com/apikey)"
store_secret "agentic-hybrid-search-api-key" "API_KEY (app authentication key, or press Enter to auto-generate)"
# Login gate: shared password the audience types into the UI. Prompted so
# the operator can pick something memorable; if blank, auto-generated below.
store_secret "agentic-hybrid-search-login-password" "LOGIN_PASSWORD (shared demo password, or press Enter to auto-generate)"
# Session-cookie signing secret. Auto-generated below — never prompted, no
# operator should ever type a 32-byte random string by hand.

# Auto-generate API_KEY if not provided
if $DRY_RUN; then
    echo "[DRY RUN] Auto-generate API_KEY and store in Secret Manager"
elif ! gcloud secrets describe "agentic-hybrid-search-api-key" --project="$PROJECT_ID" &>/dev/null; then
    API_KEY_VALUE=$(openssl rand -hex 32)
    echo -n "$API_KEY_VALUE" | gcloud secrets create "agentic-hybrid-search-api-key" \
        --data-file=- \
        --project="$PROJECT_ID"
    log "Auto-generated API_KEY and stored in Secret Manager."
fi

# Auto-generate LOGIN_PASSWORD if the operator skipped the prompt above.
if $DRY_RUN; then
    echo "[DRY RUN] Auto-generate LOGIN_PASSWORD if missing"
elif ! gcloud secrets describe "agentic-hybrid-search-login-password" --project="$PROJECT_ID" &>/dev/null; then
    LOGIN_PASSWORD_VALUE=$(openssl rand -hex 6)
    echo -n "$LOGIN_PASSWORD_VALUE" | gcloud secrets create "agentic-hybrid-search-login-password" \
        --data-file=- \
        --project="$PROJECT_ID"
    log "Auto-generated LOGIN_PASSWORD and stored in Secret Manager."
    log "  Value: $LOGIN_PASSWORD_VALUE  (share this with your audience.)"
fi

# Auto-generate SESSION_SECRET (always; never prompted).
if $DRY_RUN; then
    echo "[DRY RUN] Auto-generate SESSION_SECRET if missing"
elif ! gcloud secrets describe "agentic-hybrid-search-session-secret" --project="$PROJECT_ID" &>/dev/null; then
    SESSION_SECRET_VALUE=$(openssl rand -hex 32)
    echo -n "$SESSION_SECRET_VALUE" | gcloud secrets create "agentic-hybrid-search-session-secret" \
        --data-file=- \
        --project="$PROJECT_ID"
    log "Auto-generated SESSION_SECRET and stored in Secret Manager."
fi

# Grant Secret Manager access to the Compute Engine default service account
log "Granting secret access to Cloud Run service account..."
for secret_name in \
    agentic-hybrid-search-google-api-key \
    agentic-hybrid-search-api-key \
    agentic-hybrid-search-login-password \
    agentic-hybrid-search-session-secret \
    agentic-hybrid-search-db-password; do
    run gcloud secrets add-iam-policy-binding "$secret_name" \
        --member="serviceAccount:${COMPUTE_SA}" \
        --role="roles/secretmanager.secretAccessor" \
        --project="$PROJECT_ID" \
        --quiet
done

log "Secret access granted."

# ============================================================================
# STEP 6: BUILD AND PUSH DOCKER IMAGE
# ============================================================================

log "Building and pushing Docker image..."

# Get the repo root directory (Dockerfile expects context to be repo root)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LANGCHAIN_AGENT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_ROOT="$(dirname "$LANGCHAIN_AGENT_DIR")"

# Configure Docker for Artifact Registry
run gcloud auth configure-docker "${REGION}-docker.pkg.dev" --quiet

# Build with Docker locally and push
log "Building Docker image..."
run docker build \
    --platform=linux/amd64 \
    --no-cache \
    -t "$IMAGE_URI" \
    -f "$LANGCHAIN_AGENT_DIR/Dockerfile" \
    "$REPO_ROOT"

log "Pushing Docker image to Artifact Registry..."
run docker push "$IMAGE_URI"

log "Docker image built and pushed."

# ============================================================================
# STEP 7: DEPLOY TO CLOUD RUN
# ============================================================================

log "Deploying to Cloud Run..."

run gcloud run deploy "$SERVICE_NAME" \
    --image="$IMAGE_URI" \
    --platform=managed \
    --region="$REGION" \
    --project="$PROJECT_ID" \
    --allow-unauthenticated \
    --memory="$MEMORY" \
    --cpu="$CPU" \
    --min-instances="$MIN_INSTANCES" \
    --max-instances="$MAX_INSTANCES" \
    --concurrency="$CONCURRENCY" \
    --cpu-throttling \
    --timeout=3600 \
    --startup-probe=timeoutSeconds=5,periodSeconds=30,failureThreshold=20,tcpSocket.port=8080 \
    --add-cloudsql-instances="$CLOUD_SQL_CONNECTION" \
    --service-account=agentic-hybrid-search-sa@${PROJECT_ID}.iam.gserviceaccount.com \
    --set-env-vars="\
POSTGRES_HOST=/cloudsql/${CLOUD_SQL_CONNECTION},\
POSTGRES_USER=${DB_USER},\
POSTGRES_DB=${DB_NAME},\
LLM_MODEL=gemini-3-flash-preview,\
EMBEDDINGS_MODEL=models/gemini-embedding-001,\
RERANKER_TYPE=cross-encoder,\
CROSS_ENCODER_MODEL=cross-encoder/ms-marco-MiniLM-L-12-v2,\
QUERY_EVAL_MODEL=gemini-3.1-flash-lite-preview,\
VECTOR_DIMENSION=768,\
LOG_FORMAT=json,\
LOG_LEVEL=INFO,\
ENABLE_RERANKING=true,\
ENABLE_QUERY_EVALUATION=true,\
ENABLE_CONTENT_TYPE_CLASSIFICATION=true,\
SESSION_COOKIE_SECURE=true,\
SESSION_MAX_AGE_SECONDS=86400,\
ENABLE_COMPACTION=true,\
MAX_CONTEXT_TOKENS=3000,\
OPENSEARCH_HOST=34.138.97.13,\
OPENSEARCH_PORT=9200,\
OPENSEARCH_USE_SSL=true,\
OPENSEARCH_VERIFY_CERTS=false,\
OPENSEARCH_INDEX_NAME=agentic_hybrid_search_docs" \
    --set-secrets="\
GOOGLE_API_KEY=agentic-hybrid-search-google-api-key:latest,\
API_KEY=agentic-hybrid-search-api-key:latest,\
LOGIN_PASSWORD=agentic-hybrid-search-login-password:latest,\
SESSION_SECRET=agentic-hybrid-search-session-secret:latest,\
POSTGRES_PASSWORD=agentic-hybrid-search-db-password:latest,\
OPENSEARCH_USER=agentic-hybrid-search-opensearch-user:latest,\
OPENSEARCH_PASSWORD=agentic-hybrid-search-opensearch-password:latest" \
    --quiet

# ============================================================================
# STEP 8: PRINT RESULTS
# ============================================================================

echo ""
echo "============================================================"
log "DEPLOYMENT COMPLETE"
echo "============================================================"
echo ""

if $DRY_RUN; then
    SERVICE_URL="https://${SERVICE_NAME}-xxxxx-uc.a.run.app"
else
    SERVICE_URL=$(gcloud run services describe "$SERVICE_NAME" \
        --region="$REGION" \
        --project="$PROJECT_ID" \
        --format="value(status.url)" 2>/dev/null)

    # Rebuild Docker image with the discovered SERVICE_URL for better frontend performance
    # The frontend can now discover the URL via /api/config at runtime, but baking it in
    # at build time improves initial load performance (no extra network call)
    if [ -n "$SERVICE_URL" ] && ! $DRY_RUN; then
        log "Rebuilding Docker image with discovered SERVICE_URL..."
        if run docker build \
            --platform=linux/amd64 \
            --no-cache \
            -t "$IMAGE_URI" \
            -f "$LANGCHAIN_AGENT_DIR/Dockerfile" \
            "$REPO_ROOT" > /dev/null 2>&1; then
            log "Pushing updated Docker image..."
            if run docker push "$IMAGE_URI" > /dev/null 2>&1; then
                log "Redeploying with updated image..."
                if run gcloud run deploy "$SERVICE_NAME" \
                    --image="$IMAGE_URI" \
                    --platform=managed \
                    --region="$REGION" \
                    --project="$PROJECT_ID" \
                    --quiet > /dev/null 2>&1; then
                    log "Service redeployed with latest configuration."
                fi
            fi
        fi
    fi
fi

echo "  Service URL:     $SERVICE_URL"
echo "  Health Check:    ${SERVICE_URL}/api/health"
echo "  API Docs:        ${SERVICE_URL}/swagger"
echo ""
echo "  Cloud SQL:       $CLOUD_SQL_INSTANCE ($REGION)"
echo "  Database:        $DB_NAME"
echo "  Image:           $IMAGE_URI"
echo ""
echo "NEXT STEPS:"
echo "  1. Initialize Cloud SQL + ingest docs (one-time):"
echo "     ./scripts/gcp-init.sh --project $PROJECT_ID"
echo ""
echo "  2. View logs:"
echo "     gcloud run services logs read $SERVICE_NAME --region=$REGION --project=$PROJECT_ID"
echo ""
echo "COST CONTROL:"
echo "  - min-instances=0 (scales to zero when idle)"
echo "  - max-instances=2 (prevents runaway scaling)"
echo "  - cpu-throttling enabled (CPU only during requests)"
echo "  - Cloud SQL db-f1-micro tier"
echo ""
echo "  To stop all billing, run:"
echo "    ./scripts/gcp-teardown.sh --project $PROJECT_ID"
echo ""
echo "============================================================"
