#!/usr/bin/env bash
# lucille_ingest.sh — Ingest ESCI products and judgments into OpenSearch using Lucille ETL
#
# Steps:
#   1. Install Lucille plugins to local Maven repo (skipped if already installed)
#   2. Build the lucille/esci module (skipped if JAR is up-to-date)
#   3. Pre-aggregate judgments parquet (skipped if output already exists)
#   4. (Optional) Delete the products index + recreate mapping for a clean rebuild
#   5. Run Lucille products ingest (ParquetConnector → OpenSearch)
#   6. Run Lucille judgments ingest (ParquetConnector → OpenSearch)
#
# Required env vars (sourced from langchain_agent/.env):
#   OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_INDEX_NAME
#
# Parquet files are read from: <repo-root>/data/
#   esci_products_sample_10000.parquet  — precomputed products (shipped with repo)
#   esci_judgments_aggregated.parquet   — pre-aggregated judgments (generated on first run)
#
# Optional env vars:
#   LUCILLE_THREADS (default: 2) — worker threads per pipeline
#   LUCILLE_DIR     — path to an external Lucille checkout, used in Step 1 to
#                     install the lucille-parquet plugin into ~/.m2. Defaults to
#                     a sibling clone at ~/github/kmwtechnology/lucille. Only
#                     needed on first run (or after a Lucille version bump);
#                     once the plugin is in ~/.m2 the checkout is not read again.
#
# Optional flags:
#   --reset-index     Delete the products index, then recreate the mapping via
#                     setup.py before ingest. Use when mappings change.
#   --skip-judgments  Skip Step 6 (judgments ingest)

set -euo pipefail

# ── Argument parsing ─────────────────────────────────────────────────────────
SKIP_JUDGMENTS=false
RESET_INDEX=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-judgments) SKIP_JUDGMENTS=true; shift ;;
    --reset-index)    RESET_INDEX=true;    shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$AGENT_DIR")"
LUCILLE_DIR="${LUCILLE_DIR:-$HOME/github/kmwtechnology/lucille}"
ESCI_MODULE_DIR="$AGENT_DIR/lucille-esci"

# ── Colour helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[lucille_ingest]${NC} $*"; }
warn()  { echo -e "${YELLOW}[lucille_ingest]${NC} $*"; }
error() { echo -e "${RED}[lucille_ingest] ERROR:${NC} $*" >&2; }

# ── Load .env ────────────────────────────────────────────────────────────────
# NON-OVERRIDE semantics (matches python-dotenv default): a variable already
# present in the environment wins over the .env value. This is what lets callers
# like gcp-init.sh export OPENSEARCH_HOST=<hosted-ip> and have Lucille target it
# — without this guard the .env line (OPENSEARCH_HOST=localhost) would clobber
# the exported host and the ingest would silently write to localhost.
ENV_FILE="$AGENT_DIR/.env"
if [[ -f "$ENV_FILE" ]]; then
  while IFS='=' read -r key value; do
    [[ -z "$key" || "$key" == \#* ]] && continue
    # Skip keys already set in the environment (non-override).
    [[ -n "${!key+x}" ]] && continue
    # Strip inline comments and surrounding quotes
    value="${value%%#*}"
    value="${value%"${value##*[![:space:]]}"}"
    value="${value#\"}" ; value="${value%\"}"
    value="${value#\'}" ; value="${value%\'}"
    export "$key=$value"
  done < <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | grep '=')
fi

# ── Defaults ─────────────────────────────────────────────────────────────────
OPENSEARCH_HOST="${OPENSEARCH_HOST:-localhost}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
OPENSEARCH_SCHEME="${OPENSEARCH_USE_SSL:-false}"
OPENSEARCH_USER="${OPENSEARCH_USER:-}"
OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD:-}"

# Lucille reads credentials from the URL itself (user:pass@host).
# Embed them only when both are set (local Docker has no auth).
if [[ -n "$OPENSEARCH_USER" && -n "$OPENSEARCH_PASSWORD" ]]; then
  _AUTH="${OPENSEARCH_USER}:${OPENSEARCH_PASSWORD}@"
else
  _AUTH=""
fi

if [[ "$OPENSEARCH_SCHEME" == "true" ]]; then
  OPENSEARCH_URL="https://${_AUTH}${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"
  _DISPLAY_URL="https://${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"
else
  OPENSEARCH_URL="http://${_AUTH}${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"
  _DISPLAY_URL="http://${OPENSEARCH_HOST}:${OPENSEARCH_PORT}"
fi
OPENSEARCH_INDEX="${OPENSEARCH_INDEX_NAME:-agentic_hybrid_search_docs}"
DATA_DIR="$REPO_DIR/data"
LUCILLE_VERSION="1.0.0-SNAPSHOT"

# ── Step 4 (optional): Reset products index ──────────────────────────────────
# Passes --reset-index to setup.py, which deletes and atomically recreates the
# index with the correct knn_vector mapping before Lucille starts. Doing this
# in Python (not curl) prevents a race where Lucille's indexer initialization
# auto-creates the index with default mappings between the curl DELETE and
# Lucille's first write.
if [[ "$RESET_INDEX" == "true" ]]; then
  info "Resetting index mapping: deleting and recreating via setup.py $_DISPLAY_URL/$OPENSEARCH_INDEX"
  PYTHON="${AGENT_DIR}/.venv/bin/python"
  if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
  fi
  (cd "$AGENT_DIR" && PYTHONPATH=. "$PYTHON" setup.py --reset-index --skip-db --skip-docs --skip-models)
  info "Index mapping recreated."
fi

# ── Prerequisite checks ──────────────────────────────────────────────────────
if ! command -v java &>/dev/null; then
  error "Java not found. Install Java 17+ (brew install openjdk@17)."
  exit 1
fi
if ! command -v mvn &>/dev/null; then
  error "Maven not found. Install with: brew install maven"
  exit 1
fi

JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
if [[ "$JAVA_VER" -lt 17 ]]; then
  error "Java 17+ required, found: $JAVA_VER"
  exit 1
fi

# ── Step 1: Install Lucille plugins to local Maven repo ──────────────────────
PARQUET_JAR=~/.m2/repository/com/kmwllc/lucille-parquet/${LUCILLE_VERSION}/lucille-parquet-${LUCILLE_VERSION}.jar
if [[ ! -f "$PARQUET_JAR" ]]; then
  info "Installing Lucille plugins to local Maven repo..."
  if [[ ! -d "$LUCILLE_DIR/lucille-plugins" ]]; then
    error "Lucille source not found at $LUCILLE_DIR"
    error "Clone it (or set LUCILLE_DIR to an existing checkout):"
    error "  git clone https://github.com/kmwtechnology/lucille.git $LUCILLE_DIR"
    exit 1
  fi
  # lucille-bom is imported by lucille-esci/pom.xml but is not pulled in by the
  # parquet plugin's reactor (-am), so install it explicitly alongside.
  (cd "$LUCILLE_DIR" && mvn install -pl lucille-bom,lucille-plugins/lucille-parquet -am -q -DskipTests)
  info "Lucille plugins installed."
else
  info "Lucille parquet plugin already in local Maven repo."
fi

# ── Step 2: Build lucille/esci module ────────────────────────────────────────
ESCI_JAR="$ESCI_MODULE_DIR/target/lucille-esci-1.0.0.jar"
# Rebuild if pom.xml or any conf file is newer than the JAR
NEEDS_BUILD=false
if [[ ! -f "$ESCI_JAR" ]]; then
  NEEDS_BUILD=true
else
  for f in "$ESCI_MODULE_DIR/pom.xml" "$ESCI_MODULE_DIR/conf/"*.conf; do
    if [[ "$f" -nt "$ESCI_JAR" ]]; then
      NEEDS_BUILD=true
      break
    fi
  done
fi

if [[ "$NEEDS_BUILD" == "true" ]]; then
  info "Building lucille/esci Maven module..."
  (cd "$ESCI_MODULE_DIR" && mvn package -q -DskipTests)
  info "Build complete."
else
  info "lucille/esci JAR is up-to-date."
fi

# ── Step 3: Pre-aggregate judgments parquet ──────────────────────────────────
JUDGMENTS_PARQUET="$DATA_DIR/esci_judgments_aggregated.parquet"
if [[ ! -f "$JUDGMENTS_PARQUET" ]]; then
  info "Pre-aggregating ESCI judgments (2.6M rows → ~97k per-query rows)..."
  PYTHON="${AGENT_DIR}/.venv/bin/python"
  if [[ ! -x "$PYTHON" ]]; then
    PYTHON="$(command -v python3)"
  fi
  "$PYTHON" "$SCRIPT_DIR/prepare_judgments_parquet.py" --locale us
  info "Judgments parquet ready."
else
  info "Judgments parquet already exists: $JUDGMENTS_PARQUET"
fi

# ── Step 5: Run products ingest ───────────────────────────────────────────────
PRODUCTS_PARQUET="$DATA_DIR/esci_products_sample_10000.parquet"
if [[ ! -f "$PRODUCTS_PARQUET" ]]; then
  error "Products parquet not found: $PRODUCTS_PARQUET"
  exit 1
fi

info "Running Lucille products ingest..."
info "  Source: $PRODUCTS_PARQUET"
info "  Target: $_DISPLAY_URL/$OPENSEARCH_INDEX"

PARQUET_PATH="$PRODUCTS_PARQUET" \
OPENSEARCH_URL="$OPENSEARCH_URL" \
OPENSEARCH_INDEX="$OPENSEARCH_INDEX" \
  java \
    -Dconfig.file="$ESCI_MODULE_DIR/conf/products.conf" \
    -cp "$ESCI_MODULE_DIR/target/lib/*:$ESCI_MODULE_DIR/target/lucille-esci-1.0.0.jar" \
    com.kmwllc.lucille.core.Runner

info "Products ingest complete."

# ── Step 5b: Enrich with normalized attributes ────────────────────────────────
info "Enriching products with normalized color and brand attributes..."
PYTHON="${AGENT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

OPENSEARCH_HOST="$OPENSEARCH_HOST" \
OPENSEARCH_PORT="$OPENSEARCH_PORT" \
OPENSEARCH_USE_SSL="${OPENSEARCH_SCHEME}" \
OPENSEARCH_USER="$OPENSEARCH_USER" \
OPENSEARCH_PASSWORD="$OPENSEARCH_PASSWORD" \
OPENSEARCH_INDEX_NAME="$OPENSEARCH_INDEX" \
  "$PYTHON" "$REPO_DIR/scripts/enrich_attribute_normalization.py"

info "Attribute enrichment complete."

# ── Step 6: Run judgments ingest ──────────────────────────────────────────────
if [[ "$SKIP_JUDGMENTS" == "false" ]]; then
  info "Running Lucille judgments ingest..."
  info "  Source: $JUDGMENTS_PARQUET"
  info "  Target: $_DISPLAY_URL/esci_judgments"

  JUDGMENTS_PARQUET_PATH="$JUDGMENTS_PARQUET" \
  OPENSEARCH_URL="$OPENSEARCH_URL" \
    java \
      -Dconfig.file="$ESCI_MODULE_DIR/conf/judgments.conf" \
      -cp "$ESCI_MODULE_DIR/target/lib/*:$ESCI_MODULE_DIR/target/lucille-esci-1.0.0.jar" \
      com.kmwllc.lucille.core.Runner

  info "Judgments ingest complete."
  info "All done. Products → $OPENSEARCH_INDEX | Judgments → esci_judgments"
else
  info "Skipping judgments ingest (--skip-judgments)."
  info "All done. Products → $OPENSEARCH_INDEX"
fi
