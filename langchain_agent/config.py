"""
Configuration constants for Agentic Hybrid Search RAG Agent.

All configuration values are loaded from the `.env` file via python-dotenv.
Copy `.env.example` to `.env` and customize as needed.

## Configuration Sections

### LLM & Embeddings (`GOOGLE_API_KEY`, `LLM_*`, `EMBEDDINGS_*`)
Google Gemini models for generation, classification, and embeddings.
- `LLM_MODEL`: Main generation model (e.g., gemini-3-flash-preview)
- `LLM_TEMPERATURE`: Controls output creativity (0.0=deterministic, 1.0=creative)
- `EMBEDDINGS_MODEL`: Embedding model (e.g., models/gemini-embedding-001, 768-dim)
- `RERANKER_MODEL`: Reranking model (e.g., gemini-3.1-flash-lite-preview)
- `QUERY_EVAL_MODEL`: Query evaluation model (lightweight, fast)

### Database & Checkpoints (`POSTGRES_*`, `DATABASE_URL`, `DB_POOL_MAX_SIZE`)
PostgreSQL stores LangGraph checkpoints for conversation memory and state persistence.
All fields optional (defaults provided); only `DATABASE_URL` is used if set.

### Vector Database (`OPENSEARCH_*`, `VECTOR_*`)
OpenSearch cluster for hybrid search (HNSW knn_vector + BM25 lexical).
- `OPENSEARCH_HOST/PORT`: Server location (local: localhost:9200, Cloud: external IP)
- `OPENSEARCH_INDEX_NAME`: Index containing ESCI products (agentic_hybrid_search_docs)
- `VECTOR_DIMENSION`: Embedding dimension (768 for Gemini)

### Retrieval & Reranking (`RETRIEVER_*`, `RERANKER_*`, `ENABLE_RERANKING`)
Controls hybrid search balance and LLM-based relevance scoring.
- `RETRIEVER_K`: Final documents returned to agent
- `RETRIEVER_FETCH_K`: Candidates fetched before reranking
- `RETRIEVER_ALPHA`: Default semantic/lexical weighting (0.0-1.0) — usually overridden by query evaluator

### Query Evaluation & Alpha (`ENABLE_QUERY_EVALUATION`, `QUERY_EVAL_*`)
Dynamic alpha selection based on query intent.
- `QUERY_EVAL_MODEL`: Fast classifier (gemini-3.1-flash-lite-preview)
- `QUERY_EVAL_TIMEOUT_MS`: Max wait for alpha decision
- Alpha table: 0.0 (pure lexical) ← intent categories → 1.0 (pure semantic)

### Quality Gate (`ENABLE_QUALITY_GATE`, `QUALITY_GATE_THRESHOLD`)
Retry retrieval with adjusted alpha if max reranker score < threshold (default 0.50).
Catches cases where initial alpha was poorly calibrated.

### Link Verification & Caching (`ENABLE_LINK_VERIFICATION`, `LINK_CACHE_TTL_MINUTES`)
Validates product URLs before including in citations. 60-minute TTL cache reduces API calls.

### ESCI Dataset (`ESCI_*`, `CHUNKING_STRATEGY`)
Amazon Shopping Queries Dataset configuration.
- `ESCI_DATASET_DIR`: Path to parquet files (~1.8M products, ~1GB)
- `ESCI_PRODUCT_LOCALE`: Filter by region (default: "us")
- `ESCI_INGEST_LIMIT`: Sample size for ingestion (default: 10000)
- `CHUNKING_STRATEGY`: "none" for whole products (default), "fixed" for chunks

### Context Management (`ENABLE_COMPACTION`, `MAX_CONTEXT_TOKENS`)
Conversation memory management for long chat sessions.
- Compaction trims older messages when context exceeds `MAX_CONTEXT_TOKENS`
- Conservative estimate (3000 tokens) leaves room for retrieval + agent output

### Embedding Cache (`ENABLE_EMBEDDING_CACHE`, `EMBEDDING_CACHE_MAX_SIZE`)
In-memory cache for query embeddings (60-minute TTL). Reduces API calls for repeated queries.

## Getting Started

1. Copy `.env.example` to `.env`
2. Get a Google API key from https://aistudio.google.com/apikey
3. Set `GOOGLE_API_KEY=your-key-here`
4. For local dev: `docker compose up -d` starts PostgreSQL + OpenSearch
5. Run `python3 setup.py` to validate config, create tables, ingest ESCI products

All other variables have sensible defaults in this file.
"""

import os
from pathlib import Path

from dotenv import load_dotenv
from psycopg.rows import dict_row

# Load environment variables from .env file
load_dotenv()

__all__ = [
    # Google AI configuration
    "GOOGLE_API_KEY",
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
    "RETRIEVER_SEARCH_TYPE",
    # Reranker configuration
    "ENABLE_RERANKING",
    "RERANKER_TYPE",
    "RERANKER_MODEL",
    "CROSS_ENCODER_MODEL",
    "RERANKER_FETCH_K",
    "RERANKER_TOP_K",
    "RERANKER_BATCH_SIZE",
    "RERANKER_WARMUP_ENABLED",
    # Query evaluation configuration
    "ENABLE_QUERY_EVALUATION",
    "DEFAULT_ALPHA",
    "QUERY_EVAL_TIMEOUT_MS",
    "ENABLE_QUERY_EVAL_CACHE",
    "QUERY_EVAL_CACHE_MAX_SIZE",
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
    # ESCI e-commerce dataset configuration
    "ESCI_DATASET_DIR",
    "ESCI_PRODUCT_LOCALE",
    "ESCI_INGEST_LIMIT",
    "CHUNKING_STRATEGY",
    "SEARCH_DEFAULTS",
    # Sample data
    "DEFAULT_THREAD_ID",
    # Conversation compaction
    "ENABLE_COMPACTION",
    "MAX_CONTEXT_TOKENS",
    "COMPACTION_THRESHOLD_PCT",
    "MESSAGES_TO_KEEP_FULL",
    "MIN_MESSAGES_FOR_COMPACTION",
    "TOKEN_CHAR_RATIO",
    # Observable agent streaming configuration
    "ENABLE_ASYNC_STREAMING",
    # API Security
    "RATE_LIMIT_CONVERSATIONS",
    "RATE_LIMIT_CHAT",
    "RATE_LIMIT_LOGIN",
    "RATE_LIMIT_ENABLED",
    # Login gate (shared-password session auth)
    "LOGIN_PASSWORD",
    "SESSION_SECRET",
    "SESSION_COOKIE_SECURE",
    "SESSION_MAX_AGE_SECONDS",
    "SESSION_COOKIE_NAME",
    # Server
    "PORT",
    # Logging
    "LOG_LEVEL",
    "LOG_FORMAT",
    "LOG_INCLUDE_TIMESTAMP",
    # LangSmith Observability
    "LANGSMITH_API_KEY",
    "LANGSMITH_PROJECT",
    "LANGSMITH_TRACING_ENABLED",
    # Advanced Streaming
    "ENABLE_ASTREAM_EVENTS",
    # Checkpoint Optimization
    "CHECKPOINT_SELECTIVE_SERIALIZATION",
    "CHECKPOINT_KEEP_VERSIONS",
    "CHECKPOINT_COMPACTION_DAYS",
]

# ============================================================================
# GOOGLE AI CONFIGURATION
# ============================================================================

# Google API Key (required for Gemini models)
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

# LLM Model (Gemini)
LLM_MODEL = os.getenv("LLM_MODEL", "gemini-3-flash-preview")
LLM_TEMPERATURE = int(os.getenv("LLM_TEMPERATURE", 0))

# Embeddings Model (Gemini)
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "models/gemini-embedding-001")

# ============================================================================
# POSTGRES CONFIGURATION
# ============================================================================

# Database connection details (use environment variables for Docker compatibility)
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "langchain_agent")

# Cloud SQL uses Unix sockets at /cloudsql/PROJECT:REGION:INSTANCE
# When detected, skip TCP port and use socket-based connection string
if POSTGRES_HOST.startswith("/cloudsql/"):
    POSTGRES_PORT = None
    DATABASE_URL = (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@/{POSTGRES_DB}?host={POSTGRES_HOST}"
    )
else:
    POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
    DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Server port (Cloud Run sets PORT env var)
PORT = int(os.getenv("PORT", 8000))

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

# Vector embedding dimension (text-embedding-005 with output_dimensionality=768)
# Default is 1024 but 768 is recommended: nearly identical quality with 4x less storage
VECTOR_DIMENSION = 768

# Collection name for vector storage
# Use "esci_products" for Amazon ESCI e-commerce products
VECTOR_COLLECTION_NAME = "esci_products"

# ============================================================================
# OPENSEARCH CONFIGURATION
# ============================================================================

OPENSEARCH_HOST = os.getenv("OPENSEARCH_HOST", "34.138.97.13")
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

# Default search type: "similarity" (vector-only) or "hybrid" (vector + lexical using RRF)
RETRIEVER_SEARCH_TYPE = "hybrid"

# ============================================================================
# RERANKER CONFIGURATION (Gemini LLM-as-Reranker)
# ============================================================================

# Enable reranking of hybrid search results using LLM scoring
ENABLE_RERANKING = True

# Gemini model for LLM-based reranking (scores documents via batch prompting)
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

# Number of candidates to fetch before reranking
# 40 enables the "wide net recall" → cross-encoder precision narrative
RERANKER_FETCH_K = 40

# Final number of documents to return after reranking
RERANKER_TOP_K = 10

# Documents per API call (all scored in a single prompt per batch)
RERANKER_BATCH_SIZE = int(os.getenv("RERANKER_BATCH_SIZE", 20))

# Enable API connection priming on startup to reduce first-query latency
RERANKER_WARMUP_ENABLED = os.getenv("RERANKER_WARMUP_ENABLED", "true").lower() == "true"

# Reranker backend: "cross-encoder" (local, ~10ms/batch) or "gemini" (LLM, ~500ms/batch)
# Default to cross-encoder for speed; set to "gemini" to revert to LLM-based reranking
RERANKER_TYPE = os.getenv("RERANKER_TYPE", "cross-encoder")

# Cross-encoder model for local reranking (ignored if RERANKER_TYPE == "gemini")
CROSS_ENCODER_MODEL = os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")

# ============================================================================
# QUERY EVALUATOR CONFIGURATION
# ============================================================================

# Enable intelligent query evaluation for dynamic alpha adjustment
ENABLE_QUERY_EVALUATION = True

# Default alpha when evaluation is disabled or fails (0.0 = lexical, 1.0 = semantic)
DEFAULT_ALPHA = 0.25

# Query evaluation timeout (milliseconds) - max time to wait for LLM evaluation
QUERY_EVAL_TIMEOUT_MS = 3000  # 3 seconds max for LLM evaluation

# Query evaluator caching configuration
ENABLE_QUERY_EVAL_CACHE = True
QUERY_EVAL_CACHE_MAX_SIZE = 100

# Query evaluator model settings (lightweight alpha estimator)
QUERY_EVAL_MODEL = os.getenv("QUERY_EVAL_MODEL", "gemini-3.1-flash-lite-preview")
# LLM-as-judge for the Pipeline Quality Summary "Generation" stage. Distinct
# from the agent's main LLM to reduce self-preference bias.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", "gemini-3.1-flash-lite-preview")
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
# ESCI E-COMMERCE DATASET CONFIGURATION
# ============================================================================

# Path to ESCI dataset directory
ESCI_DATASET_DIR = os.getenv(
    "ESCI_DATASET_DIR", str(Path(BASE_DIR).parent / "esci" / "shopping_queries_dataset")
)

# Product locale for filtering (e.g., "us" for English US)
ESCI_PRODUCT_LOCALE = os.getenv("ESCI_PRODUCT_LOCALE", "us")

# Default number of products to ingest (can be overridden with --limit flag)
ESCI_INGEST_LIMIT = int(os.getenv("ESCI_INGEST_LIMIT", "10000"))

# ============================================================================
# CHUNKING STRATEGY (per-collection)
# ============================================================================
# Products are short (50-500 words) and should be indexed as whole units.
# New collections can override with {"enabled": True, "chunk_size": 1000, "chunk_overlap": 200}.
CHUNKING_STRATEGY = {
    "esci_products": {
        "enabled": False,
    },
}

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
# SAMPLE DATA
# ============================================================================

# Default conversation thread ID (can be overridden per conversation)
DEFAULT_THREAD_ID = "default_thread"

# ============================================================================
# CONVERSATION COMPACTION (Smart Context Management)
# ============================================================================

# Enable automatic conversation compaction
ENABLE_COMPACTION = True

# Maximum estimated tokens in context (conservative estimate for gemini-3-flash-preview)
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
# OBSERVABLE AGENT STREAMING CONFIGURATION
# ============================================================================

# Enable incremental async streaming for improved responsiveness (EXPERIMENTAL)
# When False (default): Backward compatible behavior - waits for entire node completion
#   - Runs entire graph in executor, collects all timing info after completion
#   - More blocking but stable behavior
# When True: Improved streaming with incremental event emission
#   - Emits NodeStartEvent immediately when node begins execution
#   - Processes events as they complete instead of waiting for full node
#   - Emits NodeEndEvent with accurate timing after processing
#   - TRADEOFF: Timing may be slightly less accurate than legacy mode, but
#     provides better UI responsiveness and prevents async event loop blocking
ENABLE_ASYNC_STREAMING = True

# ============================================================================
# API SECURITY CONFIGURATION
# ============================================================================

# API Key authentication (REQUIRED)
# Rate limiting configuration
RATE_LIMIT_CONVERSATIONS = "10/minute"  # List/manage conversations
RATE_LIMIT_CHAT = "20/minute"  # Chat requests (REST + WebSocket)
RATE_LIMIT_LOGIN = "5/minute"  # Login attempts per IP
RATE_LIMIT_ENABLED = True

# ----------------------------------------------------------------------------
# Login gate (shared-password session auth)
# ----------------------------------------------------------------------------
# Single shared password to gate UI access and reduce token burn during demos.
# A login submits the password; on match the server stores authenticated=True
# in a Starlette signed-cookie session (HttpOnly, SameSite=Lax). The cookie
# rides every REST + WebSocket request thereafter.

LOGIN_PASSWORD = os.getenv("LOGIN_PASSWORD")
SESSION_SECRET = os.getenv("SESSION_SECRET")

# In dev (HTTP) the cookie must not be Secure-flagged or browsers drop it.
# Cloud Run terminates TLS so this should be true in production.
SESSION_COOKIE_SECURE = os.getenv("SESSION_COOKIE_SECURE", "true").lower() == "true"

# 24h default — long enough for a demo session, short enough that a leaked
# cookie ages out without a redeploy.
SESSION_MAX_AGE_SECONDS = int(os.getenv("SESSION_MAX_AGE_SECONDS", "86400"))

# Cookie name kept short and non-revealing.
SESSION_COOKIE_NAME = os.getenv("SESSION_COOKIE_NAME", "ahs_session")

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")  # "json" for production, "console" for development
LOG_INCLUDE_TIMESTAMP = True

# ============================================================================
# LANGSMITH OBSERVABILITY CONFIGURATION
# ============================================================================

# LangSmith tracing (optional - requires API key from https://smith.langchain.com)
# Enable by setting LANGSMITH_API_KEY environment variable
LANGSMITH_API_KEY = os.getenv("LANGSMITH_API_KEY")
LANGSMITH_PROJECT = os.getenv("LANGSMITH_PROJECT", "agentic-hybrid-search")
LANGSMITH_TRACING_ENABLED = LANGSMITH_API_KEY is not None

# ============================================================================
# ADVANCED STREAMING CONFIGURATION
# ============================================================================

# Enable astream_events for fine-grained token-level streaming (EXPERIMENTAL)
# When True: Uses LangGraph's astream_events v2 API for token-by-token streaming
# When False: Uses existing streaming mode (entire node outputs)
# Requires LangGraph >= 1.0.5
ENABLE_ASTREAM_EVENTS = os.getenv("ENABLE_ASTREAM_EVENTS", "false").lower() == "true"

# ============================================================================
# CHECKPOINT OPTIMIZATION CONFIGURATION
# ============================================================================

# Enable selective state serialization (excludes large fields from checkpoints)
# Reduces checkpoint size by ~10x by excluding retrieved_documents and document_grades
# These fields are regenerated on retrieval, not needed for conversation continuity
CHECKPOINT_SELECTIVE_SERIALIZATION = True

# Number of recent checkpoint versions to keep per thread during compaction
CHECKPOINT_KEEP_VERSIONS = 3

# Compact checkpoints older than this many days
CHECKPOINT_COMPACTION_DAYS = 7
