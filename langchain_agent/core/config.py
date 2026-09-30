"""Configuration for the agent, API and scripts.

Values read with os.getenv come from `.env` (see `.env.example`, the list of what is
actually read). Retrieval tuning (RETRIEVER_*, RERANKER_*, VECTOR_DIMENSION, the quality
gate's per-intent thresholds) is plain Python below and is not env-overridable.
"""

import os

from dotenv import load_dotenv
from psycopg.rows import dict_row

load_dotenv()

# ============================================================================
# LOCAL MODELS (OLLAMA) -- #148
# ============================================================================

# Everything runs on a local Ollama server (native on the host, for Metal GPU access):
# generation, classification, evaluation, judging and query embeddings.
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# How long Ollama keeps a model resident (a cold load is 7-18s). Accepts Ollama's duration
# syntax ("90s", "60m", "1h") or bare seconds, normalized to int seconds because
# langchain-ollama's OllamaEmbeddings only takes an int.
def _duration_seconds(value: str) -> int:
    value = value.strip().lower()
    for suffix, factor in (("h", 3600), ("m", 60), ("s", 1)):
        if value.endswith(suffix):
            return int(float(value[:-1]) * factor)
    return int(value)


OLLAMA_KEEP_ALIVE = _duration_seconds(os.getenv("OLLAMA_KEEP_ALIVE", "60m"))
# Chat context window in tokens; Ollama silently truncates beyond it (see core/llm.py).
# Real prompts (system prompt + 10 products + history) stay well under; a larger window
# only costs KV-cache memory.
OLLAMA_NUM_CTX = int(os.getenv("OLLAMA_NUM_CTX", "32768"))

# One model for every chat call: qwen3.6:35b-a3b is a mixture-of-experts model (~3B active
# params) that handled every demo turn and ran faster than a 9B dense model.
# QUERY_EVAL_MODEL / JUDGE_MODEL below are separate settings so they can be split out.
LLM_MODEL = os.getenv("LLM_MODEL", "qwen3.6:35b-a3b-q4_K_M")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0))

# Must be the model the corpus was embedded with (768-dim, matching the index mapping).
# nomic-embed-text is asymmetric; the prefixes are applied in retrieval/embeddings.py.
EMBEDDINGS_MODEL = os.getenv("EMBEDDINGS_MODEL", "nomic-embed-text")

# ============================================================================
# POSTGRES CONFIGURATION
# ============================================================================

POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "postgres")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_DB = os.getenv("POSTGRES_DB", "langchain_agent")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", 5432))
DATABASE_URL = f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"

# Native `make dev` listens here; the demo container does too, published on host :8000.
PORT = int(os.getenv("PORT", 8080))

# Shared by the OpenAPI spec (api/main.py) and /api/health.
API_VERSION = "1.0.0"

DB_CONNECTION_KWARGS = {
    "autocommit": True,
    "prepare_threshold": 0,
    "row_factory": dict_row,  # Required for PostgresSaver
}
DB_POOL_MAX_SIZE = 20

# ============================================================================
# VECTOR CONFIGURATION
# ============================================================================

# nomic-embed-text is natively 768-dim.
VECTOR_DIMENSION = 768

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

ENABLE_EMBEDDING_CACHE = os.getenv("ENABLE_EMBEDDING_CACHE", "true").lower() == "true"

EMBEDDING_CACHE_MAX_SIZE = int(os.getenv("EMBEDDING_CACHE_MAX_SIZE", 100))

# ============================================================================
# RETRIEVER CONFIGURATION
# ============================================================================

# Candidates per method (kNN and BM25) fetched for hybrid search.
RETRIEVER_FETCH_K = 40

# Max wait for the pipeline's hidden LLM calls (alpha estimation, attribute extraction,
# query expansion): they have no timeout of their own and one was measured hanging ~18.7s.
# Each falls back gracefully (default alpha / no filters / the original query).
ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS = float(os.getenv("ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS", "5"))

# ============================================================================
# RERANKER CONFIGURATION (local cross-encoder)
# ============================================================================

# Candidates handed to the reranker.
RERANKER_FETCH_K = 40

# How much wider the quality gate's retry searches. Re-weighting alpha alone measurably
# changed nothing: the best reranker score was identical at alpha 0.1-1.0.
RETRY_FETCH_MULTIPLIER = 4

# Documents the agent receives after reranking.
RERANKER_TOP_K = 10

# Warm the cross-encoder in the background at startup to spare the first query.
RERANKER_WARMUP_ENABLED = os.getenv("RERANKER_WARMUP_ENABLED", "true").lower() == "true"

# Reported on reranker_result events; the UI keys its description off it.
RERANKER_TYPE = "cross-encoder"

CROSS_ENCODER_MODEL = os.getenv("CROSS_ENCODER_MODEL", "cross-encoder/ms-marco-MiniLM-L-12-v2")

# ============================================================================
# QUERY EVALUATOR CONFIGURATION
# ============================================================================

# Alpha for a turn that has none yet (initial state, quality-gate default).
DEFAULT_ALPHA = 0.25

# Alpha the query evaluator falls back to when its LLM call fails or times out; products
# need more semantic weight than DEFAULT_ALPHA.
EVALUATOR_FALLBACK_ALPHA = 0.65

QUERY_EVAL_MODEL = os.getenv("QUERY_EVAL_MODEL", LLM_MODEL)
# LLM-as-judge for the Pipeline Summary "Generation" stage.
JUDGE_MODEL = os.getenv("JUDGE_MODEL", LLM_MODEL)
QUERY_EVAL_TEMPERATURE = float(os.getenv("QUERY_EVAL_TEMPERATURE", "0"))
QUERY_EVAL_MAX_TOKENS = int(os.getenv("QUERY_EVAL_MAX_TOKENS", "1024"))

# ============================================================================
# QUALITY GATE CONFIGURATION
# ============================================================================

# One retry with alpha shifted 0.3 when the top reranker score is under the threshold.
ENABLE_QUALITY_GATE = os.getenv("ENABLE_QUALITY_GATE", "true").lower() == "true"

# Fallback threshold for intents not listed in pipeline_nodes._QUALITY_THRESHOLD_BY_INTENT.
QUALITY_GATE_THRESHOLD = float(os.getenv("QUALITY_GATE_THRESHOLD", "0.5"))

# ============================================================================
# LOGGING CONFIGURATION
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = os.getenv("LOG_FORMAT", "console")  # "json" for production, "console" for development

# ============================================================================
# AGENTIC ENRICHMENT FLYWHEEL (DEMO-SPECIFIC)
# ============================================================================

# Gates the trigger_enrichment agent tool and /api/admin/enrich. It writes to the live
# index and the attribute mapping store, so it is opt-in (`.env.example` turns it on).
ENABLE_ENRICHMENT_TOOL = os.getenv("ENABLE_ENRICHMENT_TOOL", "false").lower() == "true"

# Tags on LLM calls inside agent_node, read by observable_agent when deciding which
# on_chat_model_stream chunks to forward to the chat window.
# INTERNAL_LLM_TAG: deliberation (trigger_enrichment offer, value judge) that must not be
# shown as the reply.
INTERNAL_LLM_TAG = "internal_deliberation"

# ANSWER_STREAM_TAG: the call that produces the answer, which agent_node streams itself
# through the sync emit bridge; forwarding these chunks too would render every token twice.
ANSWER_STREAM_TAG = "answer_stream"
