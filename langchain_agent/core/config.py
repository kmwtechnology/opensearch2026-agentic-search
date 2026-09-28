"""
Configuration constants for Agentic Hybrid Search RAG Agent.

Most configuration values are loaded from the `.env` file via python-dotenv;
a subset (see #26 -- notably RETRIEVER_K/FETCH_K/ALPHA, RERANKER_FETCH_K/
TOP_K, ENABLE_RERANKING, ENABLE_QUERY_EVALUATION,
VECTOR_DIMENSION, ENABLE_COMPACTION, MAX_CONTEXT_TOKENS)
are plain Python literals below and are NOT env-overridable, regardless of
what a matching-looking entry in `.env.example` might suggest. Copy
`.env.example` to `.env` and customize as needed -- but check `.env.example`
itself for which of its entries actually do anything.

## Configuration Sections

### LLM & Embeddings (`OLLAMA_HOST`, `LLM_*`, `EMBEDDINGS_*`)
Local Ollama models for generation, classification, and embeddings — no cloud API key.
- `LLM_MODEL`: Main generation model (e.g., qwen3.6:35b-a3b-q4_K_M)
- `LLM_TEMPERATURE`: Controls output creativity (0.0=deterministic, 1.0=creative)
- `EMBEDDINGS_MODEL`: Embedding model (e.g., nomic-embed-text, 768-dim)
- `QUERY_EVAL_MODEL`: Query evaluation model (defaults to `LLM_MODEL`)

### Database & Checkpoints (`POSTGRES_*`, `DATABASE_URL`, `DB_POOL_MAX_SIZE`)
PostgreSQL stores LangGraph checkpoints for conversation memory and state persistence.
All fields optional (defaults provided); only `DATABASE_URL` is used if set.

### Vector Database (`OPENSEARCH_*`, `VECTOR_*`)
OpenSearch cluster for hybrid search (HNSW knn_vector + BM25 lexical).
- `OPENSEARCH_HOST/PORT`: Server location (local Docker Compose: localhost:9200)
- `OPENSEARCH_INDEX_NAME`: Index containing ESCI products (agentic_hybrid_search_docs)
- `VECTOR_DIMENSION`: Embedding dimension (768, matches nomic-embed-text)

### Retrieval & Reranking (`RETRIEVER_*`, `RERANKER_*`, `ENABLE_RERANKING`)
Controls hybrid search balance and LLM-based relevance scoring.
- `RETRIEVER_K`: Final documents returned to agent
- `RETRIEVER_FETCH_K`: Candidates fetched before reranking
- `RETRIEVER_ALPHA`: Default semantic/lexical weighting (0.0-1.0) — usually overridden by query evaluator

### Query Evaluation & Alpha (`ENABLE_QUERY_EVALUATION`, `QUERY_EVAL_*`)
Dynamic alpha selection based on query intent.
- `QUERY_EVAL_MODEL`: Fast classifier (defaults to `LLM_MODEL`)
- `ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS`: Max wait for the alpha-decision LLM call (shared with the retriever's attribute-extraction/query-expansion calls, same model family)
- Alpha table: 0.0 (pure lexical) ← intent categories → 1.0 (pure semantic)

### Quality Gate (`ENABLE_QUALITY_GATE`, `QUALITY_GATE_THRESHOLD`)
Retry retrieval with adjusted alpha if max reranker score < threshold (default 0.50).
Catches cases where initial alpha was poorly calibrated.

### Link Verification & Caching (`ENABLE_LINK_VERIFICATION`, `LINK_CACHE_TTL_MINUTES`)
Validates product URLs before including in citations. 60-minute TTL cache reduces API calls.

### Context Management (`ENABLE_COMPACTION`, `MAX_CONTEXT_TOKENS`)
Conversation memory management for long chat sessions.
- Compaction trims older messages when context exceeds `MAX_CONTEXT_TOKENS`
- Conservative estimate (3000 tokens) leaves room for retrieval + agent output

### Embedding Cache (`ENABLE_EMBEDDING_CACHE`, `EMBEDDING_CACHE_MAX_SIZE`)
In-memory cache for query embeddings (60-minute TTL). Reduces API calls for repeated queries.

## Getting Started

1. Copy `.env.example` to `.env`
2. Install Ollama natively (https://ollama.com) and pull `LLM_MODEL` + `EMBEDDINGS_MODEL`
3. `docker compose up -d` starts PostgreSQL + OpenSearch
4. Run `python3 setup.py` to validate config, create tables, ingest ESCI products

All other variables have sensible defaults in this file.
"""

import os

from dotenv import load_dotenv
from psycopg.rows import dict_row

# Load environment variables from .env file
load_dotenv()

__all__ = [
    # Ollama configuration
    "OLLAMA_HOST",
    "OLLAMA_KEEP_ALIVE",
    "OLLAMA_NUM_CTX",
    "LLM_MODEL",
    "LLM_TEMPERATURE",
    "EMBEDDINGS_MODEL",
    # PostgreSQL configuration
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_HOST",
    "POSTGRES_PORT",
    "POSTGRES_DB",
    "DATABASE_URL",
    "DB_CONNECTION_KWARGS",
    "DB_POOL_MAX_SIZE",
    # Vector configuration
    "VECTOR_DIMENSION",
    "VECTOR_COLLECTION_NAME",
    # OpenSearch configuration
    "OPENSEARCH_HOST",
    "OPENSEARCH_PORT",
    "OPENSEARCH_USER",
    "OPENSEARCH_PASSWORD",
    "OPENSEARCH_USE_SSL",
    "OPENSEARCH_VERIFY_CERTS",
    "OPENSEARCH_INDEX_NAME",
    "OPENSEARCH_SEARCH_PIPELINE",
    "OPENSEARCH_TIMEOUT",
    # Embedding cache configuration
    "ENABLE_EMBEDDING_CACHE",
    "EMBEDDING_CACHE_MAX_SIZE",
    # Retriever configuration
    "RETRIEVER_K",
    "RETRIEVER_FETCH_K",
    "RETRIEVER_ALPHA",
    "ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS",
    # Reranker configuration
    "ENABLE_RERANKING",
    "RERANKER_TYPE",
    "CROSS_ENCODER_MODEL",
    "RERANKER_FETCH_K",
    "RETRY_FETCH_MULTIPLIER",
    "RERANKER_TOP_K",
    "RERANKER_WARMUP_ENABLED",
    # Query evaluation configuration
    "ENABLE_QUERY_EVALUATION",
    "DEFAULT_ALPHA",
    "QUERY_EVAL_MODEL",
    "JUDGE_MODEL",
    "QUERY_EVAL_TEMPERATURE",
    "QUERY_EVAL_MAX_TOKENS",
    # Quality gate configuration
    "ENABLE_QUALITY_GATE",
    "QUALITY_GATE_THRESHOLD",
    # Link verification configuration
    "ENABLE_LINK_VERIFICATION",
    "LINK_VERIFICATION_TIMEOUT_MS",
    "LINK_CACHE_TTL_MINUTES",
    "MIN_VALID_DOCUMENTS",
    # Project paths
    "BASE_DIR",
    "SEARCH_DEFAULTS",
    # Sample data
    # Conversation compaction
    "ENABLE_COMPACTION",
    "MAX_CONTEXT_TOKENS",
    "COMPACTION_THRESHOLD_PCT",
    "MESSAGES_TO_KEEP_FULL",
    "MIN_MESSAGES_FOR_COMPACTION",
    "TOKEN_CHAR_RATIO",
    # API Security
    "RATE_LIMIT_CONVERSATIONS",
    "RATE_LIMIT_CHAT",
    "RATE_LIMIT_ENABLED",
    # Server
    "PORT",
    "API_VERSION",
    # Logging
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LOG_INCLUDE_TIMESTAMP",
    # Checkpoint Optimization
    "CHECKPOINT_SELECTIVE_SERIALIZATION",
    # Agentic Enrichment Flywheel
    "ENABLE_ENRICHMENT_TOOL",
]

# ============================================================================
# LOCAL MODELS (OLLAMA) -- #148
# ============================================================================

# Everything runs on a local Ollama server (native on the host for Metal GPU
# access): generation, classify/eval/judge, and query embeddings. Documents
# were embedded once when the corpus was built, against the same server.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# How long Ollama keeps a model resident after a call. A cold load is 7-18s,
# which would land mid-demo on the first turn after an idle spell.
# Same variable name the Ollama server reads, so a host already running
# `OLLAMA_KEEP_ALIVE=1h ollama serve` behaves the same for this app. Accepts
# Ollama's duration syntax ("90s", "60m", "1h") or bare seconds; normalized
# to int seconds because langchain-ollama's OllamaEmbeddings only takes an int.
def _duration_seconds(value: str) -> int:
    value = value.strip().lower()
    for suffix, factor in (("h", 3600), ("m", 60), ("s", 1)):
        if value.endswith(suffix):
            return int(float(value[:-1]) * factor)
    return int(value)


OLLAMA_KEEP_ALIVE = _duration_seconds(os.getenv("OLLAMA_KEEP_ALIVE", "60m"))
# Chat context window, in tokens. Ollama silently truncates anything longer
# (see core/llm.py). The longest real prompts -- agent system prompt + up to
# 10 products + multi-turn history -- stay well under this; qwen3.6 supports
# far more, but every extra token of window costs KV-cache memory.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

# One model for every chat call. qwen3.6:35b-a3b is a mixture-of-experts model
# (~3B active params per token): on the real intent prompt it matched all 8
# DEMO.md demo turns and ran FASTER than qwen3.5:9b on every call measured
# (intent ~1.5s vs ~2.5s warm). QUERY_EVAL_MODEL / JUDGE_MODEL below stay
# separate settings so a smaller classifier can be split out later.
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6:35b-a3b-q4_K_M")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0))

# Query embeddings. Must be the model the corpus was embedded with, and
# 768-dim to match the index mapping. nomic-embed-text is asymmetric -- the
# search_query:/search_document: prefixes are applied in retrieval/embeddings.py.
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "nomic-embed-text")

# ============================================================================
# POSTGRES CONFIGURATION
# ============================================================================

# Database connection details (use environment variables for Docker compatibility)
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "langchain_agent")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Port the API listens on. Native `make dev` runs here; the demo container
# listens on it too and is published on host :8000.
PORT = int(os.getenv("PORT", 8080))

# API version -- single source of truth for both the FastAPI app's own
# `version=` (api/main.py, shows up in the OpenAPI spec/Swagger UI) and the
# /api/health response body (api/routes/health.py). Previously hardcoded
# separately in both places and had drifted out of sync (1.0.0 vs 1.1.0).
API_VERSION = "1.0.0"

# Connection pool settings
DB_CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,  # Required for PostgresSaver
}
DB_POOL_MAX_SIZE = 20

# ============================================================================
# VECTOR CONFIGURATION
# ============================================================================

# Vector embedding dimension (nomic-embed-text is natively 768-dim)
# Default is 3072 but 768 is recommended: nearly identical quality with far less storage
VECTOR_DIMENSION = 768

# Collection name for vector storage
# Use "esci_products" for Amazon ESCI e-commerce products
VECTOR_COLLECTION_NAME = "esci_products"

# ============================================================================
# OPENSEARCH CONFIGURATION
# ============================================================================

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "localhost")
OPENSEARCH_PORT = int(os.getenv("OPENSEARCH_PORT", 9200))
OPENSEARCH_USER = os.getenv("OPENSEARCH_USER", "admin")
OPENSEARCH_PASSWORD = os.getenv("OPENSEARCH_PASSWORD", "")
OPENSEARCH_USE_SSL = os.getenv("OPENSEARCH_USE_SSL", "true").lower() == "true"
OPENSEARCH_VERIFY_CERTS = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
OPENSEARCH_INDEX_NAME = os.getenv("OPENSEARCH_INDEX_NAME", "agentic_hybrid_search_docs")
OPENSEARCH_SEARCH_PIPELINE = os.getenv("OPENSEARCH_SEARCH_PIPELINE", "hybrid_search_pipeline")
OPENSEARCH_TIMEOUT = int(os.getenv("OPENSEARCH_TIMEOUT", 30))

# ============================================================================
# EMBEDDING CACHE CONFIGURATION
# ============================================================================

# Enable query embedding caching (reduces latency for repeated queries)
ENABLE_EMBEDDING_CACHE = os.getenv("ENABLE_EMBEDDING_CACHE", "true").lower() == "true"

# Maximum number of cached query embeddings
EMBEDDING_CACHE_MAX_SIZE = int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", 100))

# ============================================================================
# RETRIEVER CONFIGURATION
# ============================================================================

# Number of documents to retrieve from vector store
RETRIEVER_K = 10

# Number of documents to fetch before filtering (for hybrid search)
# 40 candidates provides diversity for reranker to "rescue from outside top 12"
RETRIEVER_FETCH_K = 40

# Lambda multiplier for hybrid search (standard convention: 0.0 = pure lexical/BM25, 1.0 = pure semantic/vector)
# Optimized from benchmarks: 0.25 provides best quality (0.611) with acceptable latency (22ms)
RETRIEVER_ALPHA = 0.25

# Max wait (seconds) for the pipeline's three hidden alpha_estimator_llm /
# structured-alpha-estimator calls: Retriever._extract_attributes
# (brand/color/waterproof/price parsing for attribute_filter/refinement
# queries), Retriever._expand_vague_query (follow-up query expansion), and
# query_evaluator_node's alpha-estimation call. None of these calls has a
# timeout of its own -- one was measured hanging ~18.7s in one
# reindex-adjacent trial vs. a normal <1s (issue #117/#120/#122). On
# timeout, each falls back gracefully (no filters / original query /
# collection-default alpha) rather than blocking the whole turn.
ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS = float(os.getenv("ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS", "5"))

# ============================================================================
# RERANKER CONFIGURATION (local cross-encoder)
# ============================================================================

# Enable cross-encoder reranking of hybrid search results
ENABLE_RERANKING = True

# Number of candidates to fetch before reranking
# 40 enables the "wide net recall" → cross-encoder precision narrative
RERANKER_FETCH_K = 40

# How much wider the quality gate's retry searches than the first pass.
# The retry used to only nudge alpha, which measurably changed nothing: the
# reranker's best score was identical at alpha 0.1/0.4/0.7/1.0 for every
# conceptual query tested, because re-weighting reorders a pool that already
# holds the same best document. Multiplying the pool is what lets the second
# pass see candidates the first one never scored (#103).
RETRY_FETCH_MULTIPLIER = 4

# Final number of documents to return after reranking
RERANKER_TOP_K = 10

# Enable API connection priming on startup to reduce first-query latency
RERANKER_WARMUP_ENABLED = os.getenv("RERANKER_WARMUP_ENABLED", "true").lower() == "true"

# Reranker backend. Only "cross-encoder" exists since the earlier LLM-as-reranker
# option was removed (#148); kept as a constant because reranker_result events carry it
# and the UI keys its description off it (#87). ~2s for a 40-doc batch.
RERANKER_TYPE = "cross-encoder"

# Cross-encoder model for local reranking
CROSS_ENCODER_MODEL = os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")

# ============================================================================
# QUERY EVALUATOR CONFIGURATION
# ============================================================================

# Enable intelligent query evaluation for dynamic alpha adjustment
ENABLE_QUERY_EVALUATION = True

# Default alpha when evaluation is disabled or fails (0.0 = lexical, 1.0 = semantic)
DEFAULT_ALPHA = 0.25

# Query evaluation timeout: see ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS above
# (retriever config section) -- shared with the retriever's attribute-
# extraction/query-expansion calls, same underlying model. Was previously
# its own dead constant (QUERY_EVAL_TIMEOUT_MS, declared but never wired to
# anything that enforced it -- issue #122); collapsed into the one real
# timeout budget instead of carrying two.

# Query evaluator model settings (lightweight alpha estimator)
QUERY_EVAL_MODEL = os.getenv("QUERY_EVAL_MODEL", LLM_MODEL)
# LLM-as-judge for the Pipeline Quality Summary "Generation" stage. Distinct
# from the agent's main LLM to reduce self-preference bias.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", LLM_MODEL)
QUERY_EVAL_TEMPERATURE = float(os.getenv("QUERY_EVAL_TEMPERATURE", "0"))
QUERY_EVAL_MAX_TOKENS = int(os.getenv("QUERY_EVAL_MAX_TOKENS", "1024"))

# ============================================================================
# QUALITY GATE CONFIGURATION
# ============================================================================

# Enable quality gate that retries retrieval with adjusted alpha when results have low relevance
# Single retry with alpha shifted ±0.3 if top reranker score < threshold
ENABLE_QUALITY_GATE = os.getenv("ENABLE_QUALITY_GATE", "true").lower() == "true"

# Retry if top reranker score is below this threshold (0.0-1.0)
# Default: 0.5 (moderate threshold)
QUALITY_GATE_THRESHOLD = float(os.getenv("QUALITY_GATE_THRESHOLD", "0.5"))

# ============================================================================
# LINK VERIFICATION CONFIGURATION
# ============================================================================

# Enable verification of citation links before sending to LLM
# When enabled, checks if all document URLs are accessible (not 404)
# Replaces broken-link documents with valid alternatives to maintain document count
ENABLE_LINK_VERIFICATION = os.getenv("ENABLE_LINK_VERIFICATION", "true").lower() == "true"

# Timeout per URL check in milliseconds
# URLs that don't respond within this time are marked as broken
# Default: 2000ms (2 seconds)
LINK_VERIFICATION_TIMEOUT_MS = int(os.getenv("LINK_VERIFICATION_TIMEOUT_MS", "2000"))

# Cache TTL for verification results in minutes
# Avoids re-checking the same URL repeatedly
# Default: 60 minutes
LINK_CACHE_TTL_MINUTES = int(os.getenv("LINK_CACHE_TTL_MINUTES", "60"))

# Minimum number of documents to maintain after link verification
# If documents are removed due to broken links, replacements are found
# to maintain this count
# Default: 10 (standard retrieval count)
MIN_VALID_DOCUMENTS = int(os.getenv("MIN_VALID_DOCUMENTS", "10"))

# ============================================================================
# PROJECT PATHS
# ============================================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ============================================================================
# SEARCH DEFAULTS (per-collection)
# ============================================================================
# Products need higher semantic weight (α=0.65) for similarity matching.
# New collections can define their own alpha/fetch_k/reranker_top_k.
SEARCH_DEFAULTS = {
    "esci_products": {
        "alpha": 0.65,
        "fetch_k": 40,
        "reranker_top_k": 10,
    },
}

# ============================================================================
# CONVERSATION COMPACTION (Smart Context Management)
# ============================================================================

# Enable automatic conversation compaction
ENABLE_COMPACTION = True

# Maximum estimated tokens in context (conservative estimate for the local LLM)
MAX_CONTEXT_TOKENS = 3000

# Trigger compaction at this percentage of max context (0.8 = 80%)
COMPACTION_THRESHOLD_PCT = 0.8

# Keep this many recent messages uncompacted (always preserved in full)
MESSAGES_TO_KEEP_FULL = 10

# Minimum number of messages before considering compaction
MIN_MESSAGES_FOR_COMPACTION = 20

# Token estimation (1 token ≈ 4 characters, conservative)
TOKEN_CHAR_RATIO = 4

# ============================================================================
# API SECURITY CONFIGURATION
# ============================================================================

# Rate limiting configuration
RATE_LIMIT_CONVERSATIONS = "10/minute"  # List/manage conversations
RATE_LIMIT_CHAT = "20/minute"  # Chat requests (REST + WebSocket)
RATE_LIMIT_ENABLED = True

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")  # "json" for production, "console" for development
LOG_INCLUDE_TIMESTAMP = True

# ============================================================================
# CHECKPOINT OPTIMIZATION CONFIGURATION
# ============================================================================

# Enable selective state serialization (excludes large fields from checkpoints)
# Reduces checkpoint size by ~10x by excluding retrieved_documents and document_grades
# These fields are regenerated on retrieval, not needed for conversation continuity
CHECKPOINT_SELECTIVE_SERIALIZATION = True

# ============================================================================
# AGENTIC ENRICHMENT FLYWHEEL (DEMO-SPECIFIC)
# ============================================================================

# Gates both the trigger_enrichment agent tool and the /api/admin/enrich
# endpoint. Off by default — this writes to the live index and the
# OpenSearch-backed attribute mapping store, so it's kept opt-in outside the
# conference demo environment.
ENABLE_ENRICHMENT_TOOL = os.getenv("ENABLE_ENRICHMENT_TOOL", "false").lower() == "true"

# Tag applied to LLM calls made INSIDE agent_node that are deliberation, not
# the answer — the trigger_enrichment tool-offer call and the enrichment value
# judge. observable_agent streams every on_chat_model_stream it sees while the
# agent node is current, so without this the model's internal reasoning is
# shown to the user as if it were the reply. Observed live: asking for
# wireless headphones produced the answer "Nothing in the query ... looks like
# a color or material term", which is the tool-offer prompt thinking out loud.
INTERNAL_LLM_TAG = "internal_deliberation"

# Tag applied to the ONE call that produces the user-visible answer, which
# agent_node streams itself through the sync emit bridge
# (_stream_llm_response_simple). observable_agent must not also stream that
# call's on_chat_model_stream chunks: both paths fire for the same tokens, and
# the browser appends them to one buffer, so the reply renders interleaved with
# itself ("...offer various stylesThese wireless headphones offer various
# styles including..."), every sentence doubled mid-clause (#103).
#
# The pipeline's own emit is the one that survives: agent_node runs on a worker
# thread, where the LangChain callback cannot reach the astream_events iterator
# reliably, which is why it was moved onto the bridge in the first place.
ANSWER_STREAM_TAG = "answer_stream"
