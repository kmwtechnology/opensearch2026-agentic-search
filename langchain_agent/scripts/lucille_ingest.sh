#!/usr/bin/env bash
# lucille_ingest.sh — Ingest ESCI products and judgments into OpenSearch using Lucille ETL
#
# Two ways to run the actual Lucille steps (5 and 6), chosen by LUCILLE_USE_DOCKER:
#
#   Docker (default, LUCILLE_USE_DOCKER unset/true) — runs Lucille via
#   `docker compose run --rm --no-deps lucille`, using the image built from
#   docker/lucille/Dockerfile. No local Java/Maven/Lucille checkout needed.
#   Works against both a local OpenSearch (the compose service, targeted via
#   its DNS name when OPENSEARCH_HOST=localhost) and a remote hosted OpenSearch
#   (targeted directly via OPENSEARCH_URL if you point it at one).
#
#   Native (LUCILLE_USE_DOCKER=false) — the original path: builds lucille-esci
#   locally against a Lucille source checkout and runs `java -cp ...`. Requires
#   local Java 21+/Maven and LUCILLE_DIR pointed at (or defaulting to) a
#   checkout of https://github.com/kmwtechnology/lucille. Kept as a fallback
#   for environments without Docker.
#
# Steps:
#   1. (native only) Install Lucille plugins to local Maven repo
#   2. (native only) Build the lucille/esci module
#   3. Pre-aggregate judgments parquet (skipped if output already exists)
#   4. (Optional) Delete the products index + recreate mapping for a clean rebuild
#   4b. Regenerate products.generated.conf (config_generator.py) — one
#       AttributeDetectorStage entry per attribute type currently registered
#       in the OS-backed attribute mapping store; always fresh, never
#       hand-edited (see langchain_agent/config_generator.py)
#   5. Run Lucille products ingest (ParquetConnector → OpenSearch). chunk_text
#      is embedded in-pipeline by OllamaEmbedStage against the host's Ollama
#      (#148) -- ~26 min for the full ~158K-product corpus.
#   5b. (--seed-taxonomy only) Rebuild the color attribute taxonomy in the
#       OS-backed mapping store via discovery against the products just
#       indexed (scripts/rebuild_attribute_taxonomies.py), regenerate
#       products.generated.conf (now with one detect* stage per type), and
#       run the products ingest a second time so every product gets its
#       product_<type>_primary fields. The FIRST pass skips embedding: it only
#       exists to put chunk_text in the index for discovery, and the second
#       pass re-indexes every product with vectors anyway. This is how a fresh cluster (hosted or
#       local) gets a color taxonomy at all -- nothing else seeds the store
#       (#71). "waterproof" is deliberately NOT part of this step; it starts
#       empty and is grown entirely by the live enrichment flywheel.
#   6. Run Lucille judgments ingest (ParquetConnector → OpenSearch)
#
# Required env vars (sourced from langchain_agent/.env):
#   OPENSEARCH_HOST, OPENSEARCH_PORT, OPENSEARCH_INDEX_NAME
#   OLLAMA_HOST (default http://localhost:11434), EMBEDDINGS_MODEL (default
#   nomic-embed-text) -- Ollama runs natively on the host (Metal GPU); the
#   Docker path reaches it via host.docker.internal.
#
# Parquet files are read from: <repo-root>/data/
#   esci_products.parquet               — products, text + product_image_url, no
#                                         vectors (scripts/build_product_sample.py)
#   esci_judgments_aggregated.parquet   — pre-aggregated judgments (generated on first run)
#
# Optional env vars:
#   LUCILLE_THREADS   (default: 2) — worker threads per pipeline
#   LUCILLE_USE_DOCKER (default: true) — see path selection above
#   LUCILLE_DIR       — native path only. Path to an external Lucille checkout,
#                     used in Step 1 to install the lucille-parquet plugin into
#                     ~/.m2. Defaults to a sibling clone at
#                     ~/github/kmwtechnology/lucille.
#
# Optional flags:
#   --reset-index     Delete the products index, then recreate the mapping via
#                     setup.py before ingest. Use when mappings change.
#   --skip-judgments  Skip Step 6 (judgments ingest)
#   --skip-products   Skip Steps 4b-5b (products ingest) and only refresh the
#                     judgments -- e.g. after the products index changed, since
#                     the judgments filter keeps only products present in it.
#                     Not combinable with --reset-index or --seed-taxonomy.
#   --seed-taxonomy   Run Step 5b. DESTRUCTIVE to the color mapping: wipes
#                     every color mapping (including agent-learned ones) and
#                     rediscovers from scratch. Does NOT touch "waterproof".
#                     Use on a cluster whose store is empty (Step 4b warns
#                     loudly when that is the case), or to deliberately reset
#                     color to its seed state.

set -euo pipefail

# ── Argument parsing ─────────────────────────────────────────────────────────
SKIP_JUDGMENTS=false
SKIP_PRODUCTS=false
RESET_INDEX=false
SEED_TAXONOMY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --skip-judgments) SKIP_JUDGMENTS=true; shift ;;
    --skip-products)  SKIP_PRODUCTS=true;  shift ;;
    --reset-index)    RESET_INDEX=true;    shift ;;
    --seed-taxonomy)  SEED_TAXONOMY=true;  shift ;;
    *) echo "Unknown argument: $1" >&2; exit 1 ;;
  esac
done

if [[ "$SKIP_PRODUCTS" == "true" && ( "$RESET_INDEX" == "true" || "$SEED_TAXONOMY" == "true" || "$SKIP_JUDGMENTS" == "true" ) ]]; then
  echo "--skip-products only refreshes judgments; it can't be combined with --reset-index, --seed-taxonomy or --skip-judgments" >&2
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_DIR="$(dirname "$SCRIPT_DIR")"
REPO_DIR="$(dirname "$AGENT_DIR")"
LUCILLE_DIR="${LUCILLE_DIR:-$HOME/github/kmwtechnology/lucille}"
ESCI_MODULE_DIR="$AGENT_DIR/lucille-esci"
LUCILLE_USE_DOCKER="${LUCILLE_USE_DOCKER:-true}"

# ── Color helpers ──────────────────────────────────────────────────────────
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[lucille_ingest]${NC} $*"; }
warn()  { echo -e "${YELLOW}[lucille_ingest]${NC} $*"; }
error() { echo -e "${RED}[lucille_ingest] ERROR:${NC} $*" >&2; }

# ── Load .env ────────────────────────────────────────────────────────────────
# NON-OVERRIDE semantics (matches python-dotenv default): a variable already
# present in the environment wins over the .env value. This is what lets a
# caller export OPENSEARCH_HOST=<hosted-ip> and have Lucille target it
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

# Nothing in this script is traced, but the Docker CLI honors the standard
# OTEL_EXPORTER_OTLP_* vars for its OWN telemetry: with them set (from .env,
# or inherited from the backend when the enrichment flywheel runs this), every
# `docker compose` call blocks ~10s at exit flushing spans to the collector.
# That put a ~10s dead gap before the Lucille container even appeared on
# stage, and another after it finished. Keep them away from docker entirely.
unset "${!OTEL_@}"

# ── Defaults ─────────────────────────────────────────────────────────────────
OPENSEARCH_HOST="${OPENSEARCH_HOST:-localhost}"
OPENSEARCH_PORT="${OPENSEARCH_PORT:-9200}"
OPENSEARCH_SCHEME="${OPENSEARCH_USE_SSL:-false}"
OPENSEARCH_USER="${OPENSEARCH_USER:-}"
OPENSEARCH_PASSWORD="${OPENSEARCH_PASSWORD:-}"
OPENSEARCH_VERIFY_CERTS="${OPENSEARCH_VERIFY_CERTS:-true}"

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

# Container-side OpenSearch target (Docker path only). "localhost" (the local-dev
# default) doesn't resolve to the host machine from inside a container, so use
# the compose service's DNS name instead. Any other host — CI or a GCP
# workstation targeting the remote hosted OpenSearch — is reachable directly
# from the container, so pass OPENSEARCH_URL through unchanged.
if [[ "$OPENSEARCH_HOST" == "localhost" ]]; then
  CONTAINER_OPENSEARCH_URL="http://opensearch:9200"
else
  CONTAINER_OPENSEARCH_URL="$OPENSEARCH_URL"
fi
# Embeddings come from Ollama on the host (#148). From inside a container,
# localhost is the container itself, so point the Docker path at Docker
# Desktop's host alias instead; any non-local host passes through unchanged.
OLLAMA_HOST="${OLLAMA_HOST:-http://localhost:11434}"
EMBEDDINGS_MODEL="${EMBEDDINGS_MODEL:-nomic-embed-text}"
CONTAINER_OLLAMA_HOST="$(echo "$OLLAMA_HOST" | sed -E 's#://(localhost|127\.0\.0\.1)#://host.docker.internal#')"

# Single source of truth: LUCILLE_VERSION from .env (see .env.example). This
# value is also what lucille-esci/pom.xml reads via ${env.LUCILLE_VERSION}.
LUCILLE_VERSION="${LUCILLE_VERSION:-0.11.1}"
export LUCILLE_VERSION
# Docker Hub tag for the kmwtechnology/lucille base image — a SEPARATE
# namespace from LUCILLE_VERSION (Maven coordinate). See the note in
# docker/lucille/Dockerfile and .env.example before changing either.
LUCILLE_DOCKER_TAG="${LUCILLE_DOCKER_TAG:-0.11.1.0}"
export LUCILLE_DOCKER_TAG
# sha256 digest pinning LUCILLE_DOCKER_TAG's exact content — every build
# uses this byte-identical image. See .env.example for how to refresh it
# when LUCILLE_DOCKER_TAG changes.
LUCILLE_DOCKER_DIGEST="${LUCILLE_DOCKER_DIGEST:-sha256:cefa9a3b2b9ed4c3cdf92da9abb93da37dc8ba392cc64ef39b81e02387f81073}"
export LUCILLE_DOCKER_DIGEST

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

if [[ "$LUCILLE_USE_DOCKER" == "true" ]]; then
  # ── Docker path: build the lucille image ────────────────────────────────────
  if ! command -v docker &>/dev/null; then
    error "Docker not found. Install Docker Desktop, or set LUCILLE_USE_DOCKER=false to use the native Java/Maven path."
    exit 1
  fi

  info "Building Lucille Docker image (LUCILLE_VERSION=$LUCILLE_VERSION)..."
  (cd "$REPO_DIR" && docker compose build lucille)
  info "Lucille image ready."
else
  # ── Prerequisite checks (native path only) ──────────────────────────────────
  if ! command -v java &>/dev/null; then
    error "Java not found. Install Java 21+ (brew install openjdk@21)."
    exit 1
  fi
  if ! command -v mvn &>/dev/null; then
    error "Maven not found. Install with: brew install maven"
    exit 1
  fi

  JAVA_VER=$(java -version 2>&1 | awk -F '"' '/version/ {print $2}' | cut -d. -f1)
  if [[ "$JAVA_VER" -lt 21 ]]; then
    error "Java 21+ required, found: $JAVA_VER"
    exit 1
  fi

  # ── Step 1: Install Lucille plugins to local Maven repo ────────────────────
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

  # ── Step 2: Build lucille/esci module ───────────────────────────────────────
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

# ── Step 4b: Regenerate products.generated.conf ──────────────────────────────
# One AttributeDetectorStage entry per attribute type currently registered in
# the OS-backed attribute mapping store (config_generator.py) — always
# regenerated immediately before the run so a reindex reflects whatever the
# live agent enrichment flywheel has registered, with zero hand-edited config.
PYTHON="${AGENT_DIR}/.venv/bin/python"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

# Regenerates the conf and prints config_generator.py's summary line. Returns
# non-zero when the store has no registered attribute types, so callers can
# warn -- or, after --seed-taxonomy, fail -- on an empty taxonomy. A crash of
# config_generator.py itself (OpenSearch unreachable, bad credentials) aborts
# the whole ingest: callers invoke this inside `if !`, which suspends `set -e`,
# so the exit has to be explicit here or a stale generated conf would be used.
generate_products_conf() {
  info "Regenerating products.generated.conf from current OpenSearch attribute types${1:+ ($1)}..."
  local summary
  if ! summary="$(cd "$AGENT_DIR" && PYTHONPATH=. "$PYTHON" config_generator.py "$@")"; then
    error "config_generator.py failed -- cannot regenerate products.generated.conf, aborting."
    exit 1
  fi
  echo "$summary"
  [[ "$summary" != *"stages for: []"* ]]
}

if [[ "$SKIP_PRODUCTS" == "true" ]]; then
  info "Skipping products ingest (--skip-products)."
else

# The --seed-taxonomy first pass only feeds discovery, so it skips embedding
# (see Step 5b); every other run embeds.
FIRST_PASS_ARGS=()
[[ "$SEED_TAXONOMY" == "true" ]] && FIRST_PASS_ARGS=(--no-embed)

if ! generate_products_conf "${FIRST_PASS_ARGS[@]+"${FIRST_PASS_ARGS[@]}"}"; then
  if [[ "$SEED_TAXONOMY" == "true" ]]; then
    info "Attribute mapping store is empty -- Step 5b will seed it after the products ingest."
  else
    warn "Attribute mapping store at $_DISPLAY_URL has NO registered attribute types."
    warn "No detect* stages will run: every product is indexed with no product_color_primary /"
    warn "product_waterproof_primary fields, so color/waterproof filters and the enrichment"
    warn "flywheel cannot work against this cluster. Re-run with --seed-taxonomy to seed color"
    warn "(see #71) -- waterproof grows separately via the live flywheel, not this flag."
  fi
fi

# ── Step 5: Run products ingest ───────────────────────────────────────────────
# PRODUCTS_PARQUET may be overridden (e.g. a --max-products smoke sample); it
# must live in data/, which is what the Docker path mounts at /lucille/data.
PRODUCTS_PARQUET="${PRODUCTS_PARQUET:-$DATA_DIR/esci_products.parquet}"
if [[ ! -f "$PRODUCTS_PARQUET" ]]; then
  error "Products parquet not found: $PRODUCTS_PARQUET (build it with scripts/build_product_sample.py)"
  exit 1
fi

# Fail in one second here rather than minutes into a run: OllamaEmbedStage
# would refuse to start anyway, but only after the image build and connector
# spin-up. Checked from the host, where OLLAMA_HOST is meaningful.
if ! curl -sf "$OLLAMA_HOST/api/tags" | grep -q "\"$EMBEDDINGS_MODEL"; then
  error "Ollama embedding model '$EMBEDDINGS_MODEL' not available at $OLLAMA_HOST."
  error "  Start Ollama and run: ollama pull $EMBEDDINGS_MODEL"
  exit 1
fi

run_products_ingest() {
  info "Running Lucille products ingest..."
  info "  Source: $PRODUCTS_PARQUET"
  info "  Target: $_DISPLAY_URL/$OPENSEARCH_INDEX"

  if [[ "$LUCILLE_USE_DOCKER" == "true" ]]; then
    # --no-deps: don't let compose start/health-check the local `opensearch`
    # service — irrelevant (and wasted work) when CONTAINER_OPENSEARCH_URL points
    # at a remote hosted cluster instead (CI, a GCP workstation).
    (cd "$REPO_DIR" && docker compose run --rm --no-deps \
      -e LUCILLE_CONF=/lucille/conf/products.generated.conf \
      -e PARQUET_PATH="/lucille/data/$(basename "$PRODUCTS_PARQUET")" \
      -e OPENSEARCH_URL="$CONTAINER_OPENSEARCH_URL" \
      -e OPENSEARCH_INDEX="$OPENSEARCH_INDEX" \
      -e OPENSEARCH_VERIFY_CERTS="$OPENSEARCH_VERIFY_CERTS" \
      -e OLLAMA_HOST="$CONTAINER_OLLAMA_HOST" \
      -e EMBEDDINGS_MODEL="$EMBEDDINGS_MODEL" \
      lucille)
  else
    PARQUET_PATH="$PRODUCTS_PARQUET" \
    OPENSEARCH_URL="$OPENSEARCH_URL" \
    OPENSEARCH_INDEX="$OPENSEARCH_INDEX" \
    OLLAMA_HOST="$OLLAMA_HOST" \
    EMBEDDINGS_MODEL="$EMBEDDINGS_MODEL" \
      java \
        -Dconfig.file="$ESCI_MODULE_DIR/conf/products.generated.conf" \
        -cp "$ESCI_MODULE_DIR/target/lib/*:$ESCI_MODULE_DIR/target/lucille-esci-1.0.0.jar" \
        com.kmwllc.lucille.core.Runner
  fi

  info "Products ingest complete."
}

run_products_ingest

# ── Step 5b (optional): Seed the attribute taxonomy, then re-run products ────
# Discovery samples chunk_text from the products index (not the parquet), so
# it can only run after Step 5 has populated the index -- and the detect*
# stages it enables can only apply on a second products pass. Two passes
# instead of one is the price of reusing the exact same discovery script local
# dev already uses (scripts/rebuild_attribute_taxonomies.py): same result on
# the runner, a GCP workstation, or a laptop.
if [[ "$SEED_TAXONOMY" == "true" ]]; then
  info "Seeding color attribute taxonomy via discovery against $_DISPLAY_URL/$OPENSEARCH_INDEX..."
  (cd "$AGENT_DIR" && PYTHONPATH=. "$PYTHON" scripts/rebuild_attribute_taxonomies.py)
  if ! generate_products_conf; then
    error "Taxonomy seeding finished but the mapping store still has no attribute types -- refusing to re-run products without detect* stages."
    exit 1
  fi
  info "Re-running products ingest with the seeded taxonomy..."
  run_products_ingest
fi

fi  # SKIP_PRODUCTS

# ── Step 6: Run judgments ingest ──────────────────────────────────────────────
if [[ "$SKIP_JUDGMENTS" == "false" ]]; then
  # Delete first: filterJudgmentsToProducts (judgments.conf) drops most docs
  # rather than re-indexing them, and Lucille's OpenSearch indexer only
  # touches docs it actually publishes -- a stale doc from a run before the
  # products sample changed (or before filtering existed at all) would
  # otherwise sit in the index forever with content that no longer reflects
  # what's actually retrievable. The judgments ingest always fully repopulates
  # from the parquet, so starting from empty is always correct here, unlike
  # the products index (which needs --reset-index explicitly since it can be
  # deliberately reused/appended to across ingest runs).
  info "Clearing esci_judgments index before re-ingest..."
  curl -s -X DELETE "$_DISPLAY_URL/esci_judgments" -o /dev/null || true
  # Recreate it with the explicit mapping BEFORE Lucille writes to it. Left to
  # dynamic mapping, query.keyword has no lowercase normalizer -- so
  # lookup_judgments' lowercased exact match silently misses every mixed-case
  # query -- and judgments loses its nested type.
  if ! curl -sf -X PUT "$OPENSEARCH_URL/esci_judgments" -H 'Content-Type: application/json' \
      --data-binary @"$ESCI_MODULE_DIR/mapping/judgments_mapping.json" -o /dev/null; then
    error "Failed to create esci_judgments with lucille-esci/mapping/judgments_mapping.json"
    exit 1
  fi

  info "Running Lucille judgments ingest..."
  info "  Source: $JUDGMENTS_PARQUET"
  info "  Target: $_DISPLAY_URL/esci_judgments"

  if [[ "$LUCILLE_USE_DOCKER" == "true" ]]; then
    (cd "$REPO_DIR" && docker compose run --rm --no-deps \
      -e LUCILLE_CONF=/lucille/conf/judgments.conf \
      -e JUDGMENTS_PARQUET_PATH="/lucille/data/$(basename "$JUDGMENTS_PARQUET")" \
      -e OPENSEARCH_URL="$CONTAINER_OPENSEARCH_URL" \
      -e OPENSEARCH_INDEX="$OPENSEARCH_INDEX" \
      -e OPENSEARCH_VERIFY_CERTS="$OPENSEARCH_VERIFY_CERTS" \
      lucille)
  else
    JUDGMENTS_PARQUET_PATH="$JUDGMENTS_PARQUET" \
    OPENSEARCH_URL="$OPENSEARCH_URL" \
    OPENSEARCH_INDEX="$OPENSEARCH_INDEX" \
      java \
        -Dconfig.file="$ESCI_MODULE_DIR/conf/judgments.conf" \
        -cp "$ESCI_MODULE_DIR/target/lib/*:$ESCI_MODULE_DIR/target/lucille-esci-1.0.0.jar" \
        com.kmwllc.lucille.core.Runner
  fi

  info "Judgments ingest complete."
  info "All done. Products → $OPENSEARCH_INDEX | Judgments → esci_judgments"
else
  info "Skipping judgments ingest (--skip-judgments)."
  info "All done. Products → $OPENSEARCH_INDEX"
fi
