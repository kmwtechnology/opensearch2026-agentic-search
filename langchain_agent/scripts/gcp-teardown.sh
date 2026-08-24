#!/bin/bash
# Agentic Hybrid Search — GCP Resource Teardown
# Removes all GCP resources created by deploy.sh
#
# This script deletes:
#   - Cloud Run service
#   - Cloud SQL instance (and all data)
#   - Secret Manager secrets
#   - Artifact Registry images
#
# Usage:
#   ./scripts/gcp-teardown.sh                     # Uses gcloud default project
#   ./scripts/gcp-teardown.sh --project my-proj   # Specific project

set -euo pipefail

# ============================================================================
# CONFIGURATION — Must match deploy.sh
# ============================================================================

REGION="us-central1"
SERVICE_NAME="agentic-hybrid-search"
CLOUD_SQL_INSTANCE="agentic-hybrid-search-db"
ARTIFACT_REPO="agentic-hybrid-search"

# ============================================================================
# ARGUMENT PARSING
# ============================================================================

PROJECT_ID=""

while [[ $# -gt 0 ]]; do
    case $1 in
        --project)
            PROJECT_ID="$2"
            shift 2
            ;;
        -h|--help)
            cat << 'EOF'
Usage: ./scripts/gcp-teardown.sh [OPTIONS]

Remove all GCP resources for Agentic Hybrid Search.

WARNING: This is destructive and cannot be undone.
All Cloud SQL data, secrets, and deployed services will be deleted.

OPTIONS:
    --project PROJECT_ID   GCP project ID (otherwise uses gcloud default)
    -h, --help             Show this help message

WHAT THIS SCRIPT DELETES:
    1. Cloud Run service (agentic-hybrid-search)
    2. Cloud SQL instance (agentic-hybrid-search-db) and all data
    3. Secret Manager secrets (API keys, passwords)
    4. Artifact Registry images

NOTE: This does NOT affect:
    - Hosted OpenSearch instance (managed separately)
    - Local development environment
    - GCP APIs (remain enabled)

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

# ============================================================================
# VALIDATE
# ============================================================================

if ! command -v gcloud &> /dev/null; then
    err "gcloud CLI not found. Install from https://cloud.google.com/sdk/docs/install"
fi

if [ -z "$PROJECT_ID" ]; then
    PROJECT_ID=$(gcloud config get-value project 2>/dev/null)
    if [ -z "$PROJECT_ID" ] || [ "$PROJECT_ID" = "(unset)" ]; then
        err "No GCP project set. Use --project PROJECT_ID or run: gcloud config set project PROJECT_ID"
    fi
fi

echo ""
echo "⚠️  GCP TEARDOWN — $PROJECT_ID"
echo ""
echo "This will permanently delete:"
echo "  - Cloud Run service:   $SERVICE_NAME"
echo "  - Cloud SQL instance:  $CLOUD_SQL_INSTANCE (all data)"
echo "  - Secrets:             agentic-hybrid-search-* in Secret Manager"
echo "  - Docker images:       $ARTIFACT_REPO in Artifact Registry"
echo ""
read -p "Are you sure you want to continue? (y/N): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    echo "Teardown cancelled."
    exit 0
fi

echo ""

# ============================================================================
# DELETE CLOUD RUN SERVICE
# ============================================================================

log "Deleting Cloud Run service..."
if gcloud run services describe "$SERVICE_NAME" \
    --region="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    gcloud run services delete "$SERVICE_NAME" \
        --region="$REGION" --project="$PROJECT_ID" --quiet
    log "Cloud Run service deleted."
else
    log "Cloud Run service not found (already deleted)."
fi

# ============================================================================
# DELETE CLOUD SQL INSTANCE
# ============================================================================

log "Deleting Cloud SQL instance (this takes 1-2 minutes)..."
if gcloud sql instances describe "$CLOUD_SQL_INSTANCE" \
    --project="$PROJECT_ID" &>/dev/null; then
    gcloud sql instances delete "$CLOUD_SQL_INSTANCE" \
        --project="$PROJECT_ID" --quiet
    log "Cloud SQL instance deleted."
else
    log "Cloud SQL instance not found (already deleted)."
fi

# ============================================================================
# DELETE SECRETS
# ============================================================================

log "Deleting Secret Manager secrets..."
for secret_name in agentic-hybrid-search-google-api-key agentic-hybrid-search-api-key agentic-hybrid-search-login-password agentic-hybrid-search-session-secret agentic-hybrid-search-db-password agentic-hybrid-search-opensearch-user agentic-hybrid-search-opensearch-password; do
    if gcloud secrets describe "$secret_name" --project="$PROJECT_ID" &>/dev/null; then
        gcloud secrets delete "$secret_name" --project="$PROJECT_ID" --quiet
        log "Deleted secret: $secret_name"
    fi
done

# ============================================================================
# DELETE ARTIFACT REGISTRY IMAGES (optional)
# ============================================================================

log "Cleaning up Artifact Registry..."
if gcloud artifacts repositories describe "$ARTIFACT_REPO" \
    --location="$REGION" --project="$PROJECT_ID" &>/dev/null; then
    read -p "Delete Artifact Registry repository '$ARTIFACT_REPO'? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        gcloud artifacts repositories delete "$ARTIFACT_REPO" \
            --location="$REGION" --project="$PROJECT_ID" --quiet
        log "Artifact Registry repository deleted."
    else
        log "Artifact Registry repository kept."
    fi
else
    log "Artifact Registry repository not found."
fi

# ============================================================================
# DONE
# ============================================================================

echo ""
echo "============================================================"
log "GCP TEARDOWN COMPLETE"
echo "============================================================"
echo ""
echo "  All Cloud Run and Cloud SQL resources have been deleted."
echo "  Monthly GCP charges for this project should drop to ~$0."
echo ""
echo "  NOTE: Hosted OpenSearch instance is not affected."
echo "  NOTE: GCP APIs remain enabled (no cost)."
echo ""
echo "  To redeploy: ./scripts/deploy.sh --project $PROJECT_ID"
echo ""
echo "============================================================"
