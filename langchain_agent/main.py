#!/usr/bin/env python3
"""
E-Commerce Product RAG Agent with Real-Time Streaming, Hybrid Search, and Persistent Memory

A production-grade LangGraph pipeline for e-commerce product discovery:
- 6-intent classifier (search, comparison, attribute_filter, refinement, follow_up, summary)
- Hybrid vector + BM25 retrieval fused via Reciprocal Rank Fusion (RRF, k=60)
- LLM-based reranking with quality gate and alpha-adjustment retry
- Conversational query rewriting to resolve pronouns and follow-up references
- Persistent conversation memory via PostgreSQL LangGraph checkpointer
- Real-time token-by-token streaming over WebSocket with typed observability events
- Per-turn Pipeline Quality Summary (NDCG@10, MRR, Recall@20, Precision@10)

Powered by:
- LLM: Google Gemini (gemini-3-flash-preview) for generation
- Classify/Rerank: Google Gemini (gemini-3.1-flash-lite-preview)
- Embeddings: Google Gemini (text-embedding-005, 768-dim) for semantic search
- Vector Store: OpenSearch 2.19.1 with HNSW knn + BM25
- Database: PostgreSQL for LangGraph checkpoints
- Framework: LangGraph (graph-based pipeline, not ReAct tool-binding)
- Observability: Pydantic-validated WebSocket events with real-time streaming
"""

import asyncio
import json
import logging
import os
import re
import sys
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx
import psycopg
from langchain_core.documents import Document
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from psycopg_pool import AsyncConnectionPool, ConnectionPool
from pydantic import BaseModel

# Import extracted modules
from agent_state import CustomAgentState
from doc_replacer import DocumentReplacer
from exceptions import LLMError, SearchTimeoutError
from judge import RETRY_ELIGIBLE_CATEGORIES, LLMJudge
from link_verifier import LinkVerifier
from reranker import CrossEncoderReranker, GeminiReranker
from vector_store import OpenSearchVectorStore

# Setup logging
logger = logging.getLogger(__name__)

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

# Import event types for observability
try:
    from api.schemas.events import (
        DocumentReplacementEvent,
        HybridSearchResultEvent,
        LinkVerificationEvent,
        LLMResponseChunkEvent,
        LLMResponseStartEvent,
        OpenSearchQueryEvent,
        QueryExpansionEvent,
        RerankerProgressEvent,
        RerankerStartEvent,
        SearchCandidate,
        SearchProgressEvent,
    )

    _EVENTS_AVAILABLE = True
except ImportError:
    # Event types might not be available in all contexts (e.g., CLI mode)
    HybridSearchResultEvent = None
    RerankerStartEvent = None
    SearchCandidate = None
    SearchProgressEvent = None
    RerankerProgressEvent = None
    LinkVerificationEvent = None
    DocumentReplacementEvent = None
    LLMResponseStartEvent = None
    LLMResponseChunkEvent = None
    QueryExpansionEvent = None
    OpenSearchQueryEvent = None
    _EVENTS_AVAILABLE = False

# ============================================================================
# LANGSMITH TRACING (Optional - enable with LANGSMITH_API_KEY env var)
# ============================================================================

if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "agentic-hybrid-search")


def _flatten_llm_content(response: Any) -> str:
    """Normalize an LLM response's `content` to a flat string.

    Gemini-family models return ``content`` as a list of content blocks
    (e.g. ``[{"type": "text", "text": "..."}, ...]``) instead of a flat
    string. Pydantic event models in api/schemas/events.py declare these
    fields as ``str``, so passing the raw list raises a validation error.
    This helper picks out the text blocks and joins them.

    Accepts either an ``AIMessage``-like object (extracts ``.content``)
    or a raw content payload.
    """
    content = getattr(response, "content", response)
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and "text" in block:
                parts.append(str(block["text"]))
            elif isinstance(block, str):
                parts.append(block)
        return "".join(parts)
    return content if isinstance(content, str) else str(content)


class AlphaEstimation(BaseModel):
    alpha: float
    reasoning: str


class IntentClassification(BaseModel):
    intent: str
    reasoning: str
    confidence: float
    clarifying_questions: list[str] = []


from config import (
    COMPACTION_THRESHOLD_PCT,
    CROSS_ENCODER_MODEL,
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    DEFAULT_ALPHA,
    EMBEDDINGS_MODEL,
    ENABLE_COMPACTION,
    ENABLE_QUERY_EVALUATION,
    ENABLE_RERANKING,
    GOOGLE_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    MAX_CONTEXT_TOKENS,
    MESSAGES_TO_KEEP_FULL,
    MIN_MESSAGES_FOR_COMPACTION,
    QUERY_EVAL_MAX_TOKENS,
    QUERY_EVAL_MODEL,
    QUERY_EVAL_TEMPERATURE,
    RERANKER_FETCH_K,
    RERANKER_MODEL,
    RERANKER_TOP_K,
    RERANKER_TYPE,
    RERANKER_WARMUP_ENABLED,
    RETRIEVER_ALPHA,
    RETRIEVER_FETCH_K,
    RETRIEVER_K,
    SEARCH_DEFAULTS,
    TOKEN_CHAR_RATIO,
    VECTOR_COLLECTION_NAME,
    VECTOR_DIMENSION,
)


class EcommerceSearchAgent:
    """
    Production-grade LangGraph RAG agent for e-commerce product discovery.

    This is the main orchestrator for a conversational product search system powered by
    Google Gemini, OpenSearch hybrid search, and LangGraph. It implements a sophisticated
    6-intent classifier, dynamic alpha weighting for semantic/lexical balance, LLM-based
    reranking, and real-time WebSocket streaming with full observability.

    ## Architecture

    The agent executes a stateful pipeline:

        intent_classifier (6 intents)
          ├→ search / comparison / attribute_filter / refinement / follow_up
          │   → query_evaluator (dynamic alpha) → retriever (hybrid search)
          │   → reranker (LLM scoring) → quality_gate (retry if needed) → agent (response)
          ├→ summary → agent (conversation recap)
          └→ clarify (low confidence) → agent (ask user to disambiguate)

    ## Key Capabilities

    **Intent Classification (6 types)**:
    - `search`: General product discovery ("Find wireless headphones")
    - `comparison`: Compare products ("Compare Sony vs Bose")
    - `attribute_filter`: Filter by attributes ("Show me boots in blue under $100")
    - `refinement`: Narrow prior results ("Make them waterproof") — with context validation
    - `follow_up`: Vague expansion ("Tell me more") — uses conversation history
    - `summary`: Recap previous results

    **Hybrid Search**:
    - Vector search (768-dim Gemini embeddings) + BM25 lexical search
    - Reciprocal Rank Fusion (k=60) for score fusion
    - Dynamic alpha (0.0–1.0) per query: lexical-heavy for exact matches, semantic-heavy for conceptual needs

    **Quality Gate**:
    - Reranker scores products on 0.0–1.0 scale
    - If max score < threshold, adjusts alpha ±0.3 and retries once
    - Prevents low-quality responses

    **Observable Events**:
    - Real-time WebSocket streaming with typed Pydantic events
    - 15+ event types: IntentClassification, QueryEvaluation, HybridSearchResult, RerankerProgress, QualityGateDecision, etc.
    - Enables live visualization in frontend ObservabilityPanel

    **Conversational Context**:
    - PostgreSQL checkpoints for multi-turn memory
    - Query expansion: resolves pronouns/comparatives from history
    - Refinement context validation: category + document overlap scoring

    ## Usage Example

        agent = EcommerceSearchAgent()
        agent.verify_prerequisites()  # Check Postgres, OpenSearch, Google API
        agent.initialize_components()  # Load LLM, embeddings, reranker

        # Build the LangGraph pipeline
        compiled_graph = agent.build_graph()

        # Execute a query
        result = compiled_graph.invoke(
            {"messages": [HumanMessage(content="Find wireless headphones under $100")]},
            config={"configurable": {"thread_id": "user-123"}}
        )

        # Result contains assistant response and metadata
        for msg in result["messages"]:
            if isinstance(msg, AIMessage):
                print(msg.content)

    ## Extension Points

    **Add a new intent**:
        1. Add intent string to `_build_intent_prompt()` available intents list
        2. Add classification logic in `_build_intent_prompt()`
        3. Add fast-path alpha in `query_evaluator_node()` if deterministic
        4. Add conditional edge in `build_graph()` routing to correct node
        5. Add test in `tests/unit/intent/test_intent_classifier.py`

    **Add a new pipeline node**:
        1. Implement `def my_node(self, state: CustomAgentState) -> Dict[str, Any]:`
        2. Add any required fields to `CustomAgentState` (agent_state.py)
        3. Add node to graph in `build_graph()` using `workflow.add_node("my_node", self.my_node)`
        4. Add edges: `workflow.add_edge("prior_node", "my_node")`
        5. Add test in `tests/integration/` covering state transitions

    **Observe a new event**:
        1. Create Pydantic model in `api/schemas/events.py` inheriting BaseEvent
        2. Create matching TypeScript type in `web/src/types/events.ts`
        3. Emit from node: `self._emit_event_from_sync(MyEvent(...))`
        4. Update `observabilityStore.ts` and `StepCard.tsx` to render the event

    **Swap the LLM provider** (e.g., Claude instead of Gemini):
        1. Update `LLM_MODEL` in `config.py`
        2. Update `EMBEDDINGS_MODEL` if switching embedding provider
        3. Update LLM instantiation in `initialize_components()` (line 240)
        4. Update alpha_estimator_llm if using different classification model (line 250)
        5. Update reranker initialization (line 313) for new provider's structured output syntax

    ## Implementation Notes

    - All node methods follow the signature: `(self, state: CustomAgentState) -> Dict[str, Any]`
    - State fields are optional (`total=False`); always use `state.get(key, default)` for safe access
    - The graph is built lazily in `build_graph()` and stored in `self.app`
    - Streaming is handled by `_stream_llm_response_simple()` and WebSocket callback
    - Link verification (404 detection) prevents dead citations in responses
    """

    def __init__(self):
        """Initialize the agent and all its components"""
        self.llm = None
        self.embeddings = None
        self.vector_store = None
        self.pool = None
        self.async_pool = None
        self.checkpointer = None
        self.app = None
        self.thread_id = None
        self.emit_callback = None  # For emitting intermediate events from retriever_node
        self.event_loop = None  # The running event loop (set when emit_callback is set)
        self.event_queue = []  # Queue for intermediate events
        self.retriever = None  # Base retriever
        self.reranker = None  # Cross-encoder reranker
        self.alpha_estimator_llm = None  # Lightweight model for query evaluation

        # Link verification and document replacement
        from config import LINK_CACHE_TTL_MINUTES, LINK_VERIFICATION_TIMEOUT_MS

        self.link_verifier = LinkVerifier(
            timeout_ms=LINK_VERIFICATION_TIMEOUT_MS,
            cache_ttl_minutes=LINK_CACHE_TTL_MINUTES,
        )
        self.doc_replacer = DocumentReplacer()

    def verify_prerequisites(self):
        """Verify that all required services are running"""
        print("Verifying prerequisites...")
        print()

        # Check Postgres connection
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    print("✓ Postgres is accessible")
        except Exception as e:
            print(f"✗ Cannot connect to Postgres: {e}")
            print(f"  Connection string: {DATABASE_URL}")
            sys.exit(1)

        # Check OpenSearch connection
        try:
            info = self.vector_store.client.info()
            print(f"✓ OpenSearch is accessible (v{info['version']['number']})")
        except Exception as e:
            print(f"✗ Cannot connect to OpenSearch: {e}")
            sys.exit(1)

        # Check if OpenSearch index has data
        try:
            from config import OPENSEARCH_INDEX_NAME

            count = self.vector_store.client.count(
                index=OPENSEARCH_INDEX_NAME,
                body={"query": {"term": {"collection_id": VECTOR_COLLECTION_NAME}}},
            )["count"]
            if count == 0:
                print(f"✗ No documents found in OpenSearch index")
                print("  Run: python ingest_esci_products.py")
                sys.exit(1)
            print(f"✓ OpenSearch has {count} document chunks")
        except Exception as e:
            print(f"✗ Error checking OpenSearch: {e}")
            print("  Run: python setup.py")
            sys.exit(1)

        # Check Google API key — required; langchain-google-genai uses the Gemini Developer
        # API which authenticates only with an API key string, not ADC / service accounts.
        if not GOOGLE_API_KEY:
            print("✗ GOOGLE_API_KEY is not set")
            print("  Get a key at https://aistudio.google.com/apikey and set it in .env")
            sys.exit(1)
        print("✓ GOOGLE_API_KEY is set")

        print()

    def initialize_components(self):
        """Initialize all LLM and storage components"""
        print("Initializing components...")
        print()

        # Initialize LLM with streaming enabled
        print(f"Loading LLM: {LLM_MODEL}")
        self.llm = ChatGoogleGenerativeAI(
            model=LLM_MODEL,
            temperature=LLM_TEMPERATURE,
            streaming=True,
            max_output_tokens=8192,
        )
        print("✓ LLM initialized")

        if ENABLE_QUERY_EVALUATION:
            print(f"Loading query evaluator (alpha estimator): {QUERY_EVAL_MODEL}")
            self.alpha_estimator_llm = ChatGoogleGenerativeAI(
                model=QUERY_EVAL_MODEL,
                temperature=QUERY_EVAL_TEMPERATURE,
                streaming=False,
                max_output_tokens=QUERY_EVAL_MAX_TOKENS,
            )
            self.alpha_structured = self.alpha_estimator_llm.with_structured_output(AlphaEstimation)
            self.intent_structured = self.alpha_estimator_llm.with_structured_output(
                IntentClassification
            )
            print("✓ Query evaluator model initialized")
        else:
            self.alpha_estimator_llm = None
            self.alpha_structured = None
            self.intent_structured = None

        # Initialize Embeddings
        print(f"Loading embeddings: {EMBEDDINGS_MODEL}")
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL,
            output_dimensionality=VECTOR_DIMENSION,
        )
        print("✓ Embeddings initialized")

        # Initialize Postgres connection pools (must be before vector store)
        print("Connecting to Postgres checkpoint store...")
        connection_kwargs = DB_CONNECTION_KWARGS.copy()

        # Sync pool for vector store operations
        self.pool = ConnectionPool(
            conninfo=DATABASE_URL, max_size=DB_POOL_MAX_SIZE, kwargs=connection_kwargs
        )

        # Async pool for checkpointer (required for astream_events)
        self.async_pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            max_size=DB_POOL_MAX_SIZE,
            kwargs=connection_kwargs,
            open=False,  # Will be opened asynchronously
        )
        print("✓ Postgres connection pools initialized")

        # Initialize Vector Store using OpenSearch
        print(f"Loading OpenSearch vector store: {VECTOR_COLLECTION_NAME}")
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        print("✓ Vector store initialized")

        # Create base retriever
        self.retriever = self.vector_store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": RERANKER_FETCH_K if ENABLE_RERANKING else RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": RETRIEVER_ALPHA,
            },
        )

        # Initialize Reranker (cross-encoder or LLM-based)
        if ENABLE_RERANKING:
            if RERANKER_TYPE == "cross-encoder":
                print(f"Loading cross-encoder reranker: {CROSS_ENCODER_MODEL}")
                self.reranker = CrossEncoderReranker(model_name=CROSS_ENCODER_MODEL)
            else:
                print(f"Loading Gemini reranker: {RERANKER_MODEL}")
                self.reranker = GeminiReranker(model_name=RERANKER_MODEL)
            print("✓ Reranker initialized")
            # Warmup is deferred to observable_agent lifespan to avoid blocking startup
        else:
            self.reranker = None

        # Lazy LLM-as-judge — only constructed when first needed (judge node
        # only runs when user toggles llm_judge:on AND llm:on).
        self.judge: Optional[LLMJudge] = None

        # Checkpointer will be created asynchronously via create_async_checkpointer()
        # This is required because AsyncPostgresSaver needs a running event loop
        self.checkpointer = None
        print("✓ Postgres checkpoint store will be initialized on first use (async)")

        # Ensure conversation metadata table exists
        self._ensure_metadata_table()

        print()

    # ========================================================================
    # AGENT GRAPH NODES FOR DYNAMIC QUERY EVALUATION
    # ========================================================================

    def intent_classifier_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Classify the latest user message to determine intent for e-commerce product search.

        Uses keyword fast-path (deterministic, <100ms) for high-confidence classification,
        falls back to LLM for ambiguous queries. If confidence < 0.7, returns intent=clarify
        with clarifying questions for user confirmation.

        Intents (6 types):
        - `search`: General product discovery queries (DEFAULT)
        - `comparison`: Comparing two or more products ("Compare X vs Y")
        - `attribute_filter`: Requests with specific attributes ("Show me X in [color] under [price]")
        - `refinement`: Narrowing prior search with new constraints ("Make them waterproof")
        - `follow_up`: Vague expansions needing context ("Tell me more", "Any alternatives?")
        - `summary`: Conversation recap ("Summarize what we discussed")
        - `clarify`: Low-confidence queries requiring disambiguation

        Args:
            state: CustomAgentState with 'messages' required. Other fields set by prior nodes.

        Returns:
            Dict with keys:
            - intent: str, one of the 6 intent types above
            - user_query: str, extracted user message
            - intent_confidence: float, 0.0–1.0 confidence in classification
            - reasoning: str, explanation for classification decision
            - clarifying_questions: list[str], questions if confidence < 0.7

        Examples:
            Query: "Find me wireless headphones under $100"
            Output: {
                "intent": "search",
                "intent_confidence": 0.95,
                "reasoning": "General product discovery query",
                "clarifying_questions": []
            }

            Query: "Hmm, maybe cheaper ones?"
            Output: {
                "intent": "follow_up",
                "intent_confidence": 0.68,
                "reasoning": "Vague price refinement, low confidence",
                "clarifying_questions": ["Price range? e.g., under $50", "Any other constraints?"]
            }

        LangSmith Observability:
            This node emits structured logs with metadata that LangSmith picks up:
            - node: "intent_classifier"
            - intent: detected intent class
            - confidence: classification confidence (0.0–1.0)
            - path: "keyword" or "llm" (fast-path or fallback)
        """
        messages = state["messages"]
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, "content") and msg.content:
                user_query = _flatten_llm_content(msg)
                break

        intent, reasoning, confidence, clarifying_questions = self._classify_intent(
            user_query, messages
        )
        logger.info(
            f"Intent classification: intent={intent}, confidence={confidence:.2f}, query={user_query[:50] if user_query else '<empty>'}..."
        )

        # NEW: Category continuity validation for refinement intents
        if intent == "refinement":
            prior_docs = state.get("prior_search_documents", [])
            if prior_docs:
                # Validate category continuity
                continuity_score, category_reasoning = self._validate_category_continuity(
                    prior_docs, user_query, []
                )

                # If categories are very different, downgrade to search
                if continuity_score < 0.3:
                    logger.info(
                        f"Category continuity check failed ({continuity_score:.2f}): {category_reasoning} → downgrading to search"
                    )
                    intent = "search"
                    reasoning = (
                        f"{category_reasoning}. Treating as new search instead of refinement."
                    )
                    confidence = 0.95  # High confidence that this is a new search
                # If ambiguous, lower confidence to trigger clarification
                elif continuity_score < 0.7:
                    logger.info(
                        f"Category continuity ambiguous ({continuity_score:.2f}): {category_reasoning}"
                    )
                    confidence = min(confidence, 0.65)
                    reasoning = f"{category_reasoning}. Need clarification on intent."

        return {
            "intent": intent,
            "user_query": user_query,
            "reasoning": reasoning,
            "confidence": confidence,  # For UI display
            "intent_confidence": confidence,
            "clarifying_questions": clarifying_questions,
            # Reset per-turn guard so every new user message gets a fresh retry budget.
            # LangGraph persists state through Postgres checkpoints; without this reset,
            # a retry fired in turn N permanently disables the gate for turns N+1, N+2, …
            # (issue #83).
            "hallucination_retry_used": False,
        }

    def query_evaluator_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Evaluate query type and determine optimal alpha for hybrid search balance.

        Sets the alpha parameter (0.0=pure lexical/BM25, 1.0=pure semantic/vector) based on:
        - Intent fast-path: deterministic alpha for comparison (0.60), attribute_filter (0.25), refinement (0.35)
        - LLM path: semantic analysis for search/follow_up intents, prompt-guided selection

        Also expands vague queries using conversation history (pronouns, comparatives).

        Alpha Interpretation:
        - 0.0–0.15: Pure lexical (exact model numbers, ASINs, brand+model)
        - 0.15–0.40: Lexical-heavy (specific features, color/size, brand combos)
        - 0.40–0.60: Balanced (feature comparisons, activity-based queries)
        - 0.60–0.75: Semantic-heavy (conceptual needs, occasion-based)
        - 0.75–1.0: Pure semantic (gift ideas, mood/style, open-ended exploration)

        Args:
            state: CustomAgentState with 'messages' (required) and 'intent' (set by classifier).
                   May contain 'prior_search_documents' for refinement context.

        Returns:
            Dict with keys:
            - alpha: float, 0.0–1.0 hybrid search weight
            - query_analysis: str, reasoning for alpha choice
            - search_strategy: str, human-readable strategy (e.g., "Semantic-Heavy")
            - intent_optimized: bool, True if fast-path, False if LLM-driven

        Examples:
            Intent: "comparison", Query: "Compare Sony vs Bose headphones"
            Output: {
                "alpha": 0.60,
                "query_analysis": "Comparison query: prioritizing semantic search for quality differences",
                "search_strategy": "Semantic-Heavy (Vector dominant)",
                "intent_optimized": True
            }

            Intent: "search", Query: "best headphones for long flights"
            Output: {
                "alpha": 0.72,
                "query_analysis": "Activity-based query requiring semantic understanding",
                "search_strategy": "Semantic-Heavy (Vector dominant)",
                "intent_optimized": False
            }
        """
        start_time = time.time()
        messages = state["messages"]

        # Extract last user message
        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = _flatten_llm_content(msg)
                break

        if not last_user_msg:
            # No user message, use collection-aware default
            collection_defaults = SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {})
            return {
                "alpha": collection_defaults.get("alpha", DEFAULT_ALPHA),
                "query_analysis": "No query detected",
            }

        intent = state.get("intent", "search")
        print(
            f"\n[Query Evaluator] Starting evaluation for query: '{last_user_msg[:80]}...' (intent: {intent})"
        )

        # FAST PATH: Intent-specific alpha selection (high confidence, no LLM)
        # These patterns are deterministic and highly accurate for e-commerce

        # 1. COMPARISON queries: Highlight product differences
        if intent == "comparison":
            alpha = 0.60  # Semantic-heavy for quality/feature differences
            strategy = "Semantic-Heavy (Vector dominant)"
            reasoning = (
                f"Comparison query: prioritizing semantic search for quality/feature differences"
            )

            elapsed = time.time() - start_time
            logger.info(
                f"Query evaluation (FAST PATH - comparison): alpha={alpha:.2f}, elapsed={elapsed:.3f}s"
            )
            return {
                "alpha": alpha,
                "query_analysis": reasoning,
                "search_strategy": strategy,
                "intent_optimized": True,
            }

        # 2. ATTRIBUTE_FILTER queries: Match specific attributes (color, size, price, features)
        elif intent == "attribute_filter":
            alpha = 0.25  # Lexical-heavy for exact attribute matching
            strategy = "Lexical-Heavy (BM25 dominant)"
            reasoning = (
                f"Attribute filter query: prioritizing lexical search for exact attribute matches"
            )

            elapsed = time.time() - start_time
            logger.info(
                f"Query evaluation (FAST PATH - attribute_filter): alpha={alpha:.2f}, elapsed={elapsed:.3f}s"
            )
            return {
                "alpha": alpha,
                "query_analysis": reasoning,
                "search_strategy": strategy,
                "intent_optimized": True,
            }

        # 3. REFINEMENT queries: Adding constraint to prior search (category context + new attribute)
        elif intent == "refinement":
            alpha = (
                0.35  # Slightly more semantic than attribute_filter to preserve category context
            )
            strategy = "Lexical-Heavy (BM25 dominant)"
            reasoning = "Refinement query: preserving category context while matching new attribute constraint"

            elapsed = time.time() - start_time
            logger.info(
                f"Query evaluation (FAST PATH - refinement): alpha={alpha:.2f}, elapsed={elapsed:.3f}s"
            )
            return {
                "alpha": alpha,
                "query_analysis": reasoning,
                "search_strategy": strategy,
                "intent_optimized": True,
            }

        # FULL LLM PATH: General search queries (flexible, intent-aware guidance)
        # For: search, follow_up (need semantic analysis)

        intent_guidance = ""
        if intent == "follow_up":
            intent_guidance = "\nNOTE: This is a FOLLOW_UP query continuing a previous search. Analyze query semantics and adjust alpha to refine previous results."
        else:  # search
            intent_guidance = "\nNOTE: This is a general SEARCH query. Analyze semantics to determine optimal balance between exact matching and conceptual relevance."

        evaluation_prompt = f"""Determine the optimal alpha for hybrid search on this query.{intent_guidance}

=== YOUR TASK ===
Query to analyze: "{last_user_msg}"

=== ALPHA GUIDE (0.0=pure lexical/BM25, 1.0=pure semantic/vector) ===
- 0.00-0.15: PURE LEXICAL - Exact product model numbers, ASINs, UPCs, brand+model combos
- 0.15-0.40: LEXICAL-HEAVY - Brand + category, specific features, color/size combos
- 0.40-0.60: BALANCED - Feature comparisons, activity-based product queries, how-to usage
- 0.60-0.75: SEMANTIC-HEAVY - Conceptual needs, occasion-based queries, comfort/quality focus
- 0.75-1.0: PURE SEMANTIC - Gift ideas, mood/style queries, open-ended exploration

=== EXAMPLES ===
"Sony WH-1000XM5" → alpha=0.05 (exact model number needs exact match)
"B07XJ8C8F5" → alpha=0.05 (ASIN identifier, pure lexical)
"Samsung noise cancelling headphones" → alpha=0.25 (brand + feature, lexical-heavy)
"blue running shoes size 10" → alpha=0.30 (specific attributes, lexical-heavy)
"best headphones for long flights" → alpha=0.55 (activity-based, balanced)
"comfortable office chair for back pain" → alpha=0.65 (conceptual need, semantic-heavy)
"good gift ideas for music lovers" → alpha=0.85 (open-ended exploration, semantic)

=== OUTPUT ===
Respond with ONLY valid JSON. The "reasoning" MUST describe the actual query "{last_user_msg}", not copy example text.

{{"alpha": <0.0-1.0>, "reasoning": "<1 sentence about THIS specific query>"}}
"""

        structured_llm = self.alpha_structured or self.llm.with_structured_output(AlphaEstimation)
        try:
            result = structured_llm.invoke(evaluation_prompt)

            alpha = max(0.0, min(1.0, result.alpha))
            reasoning = result.reasoning or "No reasoning provided"

            # Categorize search strategy
            if alpha <= 0.15:
                strategy = "Pure Lexical (BM25)"
            elif alpha <= 0.4:
                strategy = "Lexical-Heavy (BM25 dominant)"
            elif alpha <= 0.6:
                strategy = "Balanced (Hybrid)"
            elif alpha <= 0.75:
                strategy = "Semantic-Heavy (Vector dominant)"
            else:
                strategy = "Pure Semantic (Vector)"

            elapsed = time.time() - start_time
            logger.info(
                f"Query evaluation (LLM path): strategy={strategy}, alpha={alpha:.2f}, elapsed={elapsed:.3f}s"
            )
            logger.debug(f"Query evaluation details: reasoning={reasoning}, query={last_user_msg}")

            return {
                "alpha": alpha,
                "query_analysis": reasoning,
                "search_strategy": strategy,
                "intent_optimized": False,  # LLM-driven, not fast-path
            }

        except SearchTimeoutError as e:
            elapsed = time.time() - start_time
            collection_defaults = SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {})
            fallback_alpha = collection_defaults.get("alpha", DEFAULT_ALPHA)
            logger.warning(
                "Query evaluation timeout",
                extra={
                    "elapsed_ms": int(elapsed * 1000),
                    "timeout_ms": getattr(e, "timeout_ms", None),
                    "fallback_alpha": fallback_alpha,
                },
            )
            return {
                "alpha": fallback_alpha,
                "intent_description": "Unknown (timeout)",
                "query_analysis": {},
                "search_strategy": "default",
                "intent_optimized": False,
            }
        except LLMError as e:
            elapsed = time.time() - start_time
            collection_defaults = SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {})
            fallback_alpha = collection_defaults.get("alpha", DEFAULT_ALPHA)
            logger.warning(
                "Query evaluation LLM error",
                extra={
                    "model": getattr(e, "model", None),
                    "elapsed_ms": int(elapsed * 1000),
                    "fallback_alpha": fallback_alpha,
                },
            )
            return {
                "alpha": fallback_alpha,
                "intent_description": "Unknown (LLM error)",
                "query_analysis": {},
                "search_strategy": "default",
                "intent_optimized": False,
            }
        except Exception as e:
            # Fallback to collection-aware default if evaluation fails
            elapsed = time.time() - start_time
            collection_defaults = SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {})
            fallback_alpha = collection_defaults.get("alpha", DEFAULT_ALPHA)
            logger.warning(
                "Query evaluation failed",
                extra={
                    "error": str(e),
                    "elapsed_ms": int(elapsed * 1000),
                    "fallback_alpha": fallback_alpha,
                },
            )
            return {
                "alpha": fallback_alpha,
                "query_analysis": f"Evaluation failed: {str(e)}",
                "search_strategy": "Fallback",
                "intent_optimized": False,
            }

    def _verify_and_replace_documents(
        self,
        documents: List[Document],
        min_valid_documents: int,
    ) -> List[Document]:
        """
        Verify all document links and replace broken ones.

        Args:
            documents: Retrieved documents to verify
            min_valid_documents: Maintain this many docs with valid links

        Returns:
            Documents with verified/replaced links
        """
        if not documents:
            return documents

        logger.info(f"LinkVerifier: checking {len(documents)} document links")

        # Extract all URLs from documents
        urls = []
        for doc in documents:
            url = doc.metadata.get("url")
            if url and url not in urls:
                urls.append(url)

        # Verify all URLs
        verification_results = self.link_verifier.verify_urls(urls)

        # Count results
        broken_urls = {
            url: reason for url, (is_valid, reason) in verification_results.items() if not is_valid
        }
        valid_count = len([is_valid for is_valid, _ in verification_results.values() if is_valid])
        broken_count = len(broken_urls)

        logger.info(f"LinkVerifier: {valid_count} valid, {broken_count} broken links")

        # Emit link verification event
        broken_sources = [
            doc.metadata.get("source", "unknown")
            for doc in documents
            if doc.metadata.get("url") in broken_urls
        ]

        if LinkVerificationEvent:
            try:
                event = LinkVerificationEvent(
                    total_links_checked=len(verification_results),
                    valid_links=valid_count,
                    broken_links=broken_count,
                    broken_link_sources=broken_sources,
                    cache_hits=0,  # Would need to track in LinkVerifier
                )
                self._emit_event_from_sync(event)
            except Exception as e:
                logger.debug(f"Could not emit link verification event: {e}")

        # Replace broken documents if any
        if broken_urls:
            documents, replacement_info = self.doc_replacer.replace_broken_documents(
                documents,
                verification_results,
                min_valid_documents,
            )

            # Emit replacement event
            if DocumentReplacementEvent and replacement_info:
                try:
                    event = DocumentReplacementEvent(
                        replacements_made=len(self.doc_replacer.replacement_log),
                        replacement_details=self.doc_replacer.replacement_log,
                        documents_after_replacement=len(documents),
                    )
                    self._emit_event_from_sync(event)
                except Exception as e:
                    logger.debug(f"Could not emit document replacement event: {e}")

        return documents

    @staticmethod
    def _build_grounded_context(documents: List[Document]) -> str:
        """Render retrieved documents as numbered, isolated FACTS blocks.

        Each block carries a hard boundary so the LLM treats facts as
        per-product (not transferable between products). Inputs to this
        function feed both the agent_node prompt and the llm_judge_node
        regeneration helper, so the grounding semantics are identical.
        """
        if not documents:
            return "No relevant documents were found."

        blocks = []
        sep = "═══════════════════════════════════════════════════════════"
        for i, doc in enumerate(documents, 1):
            title = doc.metadata.get("title", "(untitled)")
            product_id = doc.metadata.get("product_id") or "—"
            brand = doc.metadata.get("product_brand") or ""
            color = doc.metadata.get("product_color") or ""
            score = doc.metadata.get("reranker_score") or doc.metadata.get("retrieval_score") or 0.0

            facts: List[str] = [f"  Title: {title}"]
            if brand:
                facts.append(f"  Brand: {brand}")
            if color:
                facts.append(f"  Color: {color}")
            content = (doc.page_content or "").strip()
            if content:
                facts.append(f"  Description: {content}")

            blocks.append(
                f"{sep}\n"
                f"[Product {i}] product_id={product_id} (relevance: {score:.3f})\n"
                f"FACTS — only the lines below count as supported context for this product:\n"
                + "\n".join(facts)
            )
        return "\n".join(blocks) + f"\n{sep}"

    # Markdown links: [text](url). DOTALL so multi-line link text still matches.
    _MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(\s*<?https?://[^)\s]+>?\s*\)", re.DOTALL)
    # Bare http(s) URLs (with optional surrounding ** or angle brackets).
    _BARE_URL_RE = re.compile(r"<?\*{0,2}https?://\S+?\*{0,2}>?(?=[\s.,;:!?)\]]|$)")

    @staticmethod
    def _citation_url_for_doc(doc: Document) -> Optional[str]:
        """Resolve a stable, user-facing URL for a retrieved document.

        Preference order:
          1. explicit `metadata['url']` (non-ESCI sources)
          2. Amazon search-by-title (`/s?k=<title>`) — robust to delisted ASINs,
             which is the failure mode behind issue #4
          3. Amazon search-by-product_id as a last resort if no title exists

        Returns None when no usable URL can be constructed.
        """
        url = doc.metadata.get("url")
        if url:
            return url

        from urllib.parse import quote_plus

        title = doc.metadata.get("title", "")
        if title:
            return f"https://www.amazon.com/s?k={quote_plus(title)}"

        product_id = doc.metadata.get("product_id", "")
        if product_id:
            return f"https://www.amazon.com/s?k={quote_plus(product_id)}"

        return None

    @staticmethod
    def _strip_inline_links(text: str) -> str:
        """Remove markdown hyperlinks and bare URLs from LLM-generated text.

        The agent prompt forbids the LLM from emitting URLs (it has no canonical
        product URLs and reliably hallucinates ASINs — see issue #4). This is a
        belt-and-suspenders guard: if a slipped link survives, collapse
        `[text](url)` to `text` and drop bare URLs entirely so the user is not
        shown dead/incorrect Amazon links.
        """
        if not text or "http" not in text:
            return text
        # Collapse markdown links to their visible text. Strip surrounding `**`
        # the LLM sometimes adds around the URL portion (issue #4 example).
        cleaned = EcommerceSearchAgent._MARKDOWN_LINK_RE.sub(r"\1", text)
        # Drop any remaining bare URLs.
        cleaned = EcommerceSearchAgent._BARE_URL_RE.sub("", cleaned)
        return cleaned

    @staticmethod
    def _format_search_results(documents: List[Document], user_query: Optional[str]) -> str:
        """
        Render retrieved documents as a plain search-results-style markdown list.
        Used when the user has disabled LLM response generation — order reflects
        whatever the upstream pipeline produced (reranker scores if reranking is
        on, otherwise raw retriever order).
        """
        if not documents:
            return (
                f"No products found for **{user_query or 'your search'}**.\n\n"
                "Try a different keyword or relax your filters."
            )

        header = (
            f"### Search results for *{user_query}*  \n*{len(documents)} products*\n\n"
            if user_query
            else f"### Search results  \n*{len(documents)} products*\n\n"
        )

        rows = []
        for i, doc in enumerate(documents, 1):
            title = doc.metadata.get("title") or "(untitled product)"
            brand = doc.metadata.get("product_brand") or doc.metadata.get("brand")
            url = doc.metadata.get("url") or ""
            # Prefer the reranker's relevance score; fall back to the raw
            # OpenSearch retrieval score (BM25 / kNN / RRF) when reranking is off.
            reranker_score = doc.metadata.get("reranker_score")
            retrieval_score = doc.metadata.get("retrieval_score")
            snippet = (doc.page_content or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240].rstrip() + "…"

            meta_bits = []
            if brand:
                meta_bits.append(f"**Brand:** {brand}")
            if reranker_score is not None and reranker_score > 0:
                meta_bits.append(f"**Reranker Score:** {reranker_score:.3f}")
            elif retrieval_score is not None and retrieval_score > 0:
                meta_bits.append(f"**Score:** {retrieval_score:.3f}")
            meta_line = " · ".join(meta_bits)

            heading = f"**{i}. [{title}]({url})**" if url else f"**{i}. {title}**"
            block = [heading]
            if meta_line:
                block.append(meta_line)
            if snippet:
                block.append(snippet)
            rows.append("\n\n".join(block))

        return header + "\n\n---\n\n".join(rows)

    def agent_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Agent response generation node - generates response from retrieved documents.

        This is a deterministic node that runs after retriever_node.
        Uses retrieved documents as context to answer the user's question.

        Features:
        - Verifies citation links (no 404s sent to LLM)
        - Replaces broken-link documents to maintain document count
        - Emits observability events for link verification
        """
        from config import ENABLE_LINK_VERIFICATION, MIN_VALID_DOCUMENTS

        start_time = time.time()
        messages = list(state["messages"])
        retrieved_documents = state.get("retrieved_documents", [])
        intent = state.get("intent", "question")
        summary_text = state.get("summary_text")

        if intent == "summary" and summary_text:
            logger.info("Agent: summary intent detected, returning cached summary")
            return {"messages": [AIMessage(content=summary_text)], "citations": []}

        # Handle clarify intent - ask user for more context
        if intent == "clarify":
            clarifying_questions = state.get("clarifying_questions", [])
            # Always return clarification response, even if questions list is empty
            if clarifying_questions:
                questions_text = "\n".join(f"- {q}" for q in clarifying_questions)
                clarify_response = (
                    "I'd love to help you find the right product! A few details would let me "
                    "give you better recommendations:\n\n"
                    f"{questions_text}\n\n"
                    'You could also try a more specific search like "wireless headphones under '
                    '$100" or "running shoes for flat feet" — I can take it from there.'
                )
            else:
                # Fallback response if no questions were generated
                clarify_response = (
                    "I'd love to help! To point you at the right products, could you share a "
                    "little more about what you're looking for? For example:\n\n"
                    '- A category or use case ("headphones for the gym", "a gift for a coffee lover")\n'
                    "- A brand, color, or feature you care about\n"
                    "- A budget range\n\n"
                    "Even a rough idea helps me narrow things down."
                )
            logger.info(
                f"Agent: clarify intent detected, asking {len(clarifying_questions)} questions"
            )
            return {"messages": [AIMessage(content=clarify_response)], "citations": []}

        logger.info(f"Agent: processing with {len(retrieved_documents)} retrieved documents")

        # Verify citation links if enabled
        if ENABLE_LINK_VERIFICATION and retrieved_documents:
            retrieved_documents = self._verify_and_replace_documents(
                retrieved_documents, MIN_VALID_DOCUMENTS
            )

        # Extract user query
        user_query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = _flatten_llm_content(msg)
                break

        # Check if retrieval failed even after quality gate retry
        # If quality gate retried and max relevance is still very low, return honest acknowledgment
        MIN_RELEVANCE_THRESHOLD = 0.10  # Same as citation suppression threshold
        quality_gate_retried = state.get("quality_gate_retried", False)
        max_relevance = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0,
        )

        # The "no info" branch only fires when the reranker actually scored the
        # documents — if reranking is off there are no scores to evaluate and
        # zero relevance doesn't mean low relevance. Skip this gate when the
        # user has disabled reranking or the LLM (raw-results mode).
        opts = state.get("optimizations", {})
        reranker_skipped = opts.get("reranking", True) is False
        llm_off = opts.get("llm", True) is False

        if (
            quality_gate_retried
            and max_relevance < MIN_RELEVANCE_THRESHOLD
            and not reranker_skipped
            and not llm_off
        ):
            logger.info(
                f"Agent: retrieval failed after quality gate retry "
                f"(max_relevance={max_relevance:.3f} < {MIN_RELEVANCE_THRESHOLD})"
            )
            no_info_response = (
                f"I searched for \"{user_query or 'your question'}\" but didn't find a strong "
                "match in the catalog. A few things that usually help:\n\n"
                '- Try a more specific phrase — a brand ("Sony"), a use case '
                '("wireless earbuds for running"), or a feature ("noise cancelling")\n'
                '- Add a price range ("under $50") or a color\n'
                "- Or describe who it's for and what they'd use it for, and I'll suggest "
                "categories worth exploring\n\n"
                "Want to try one of those?"
            )
            return {"messages": [AIMessage(content=no_info_response)], "citations": []}

        # Build context from retrieved documents
        if retrieved_documents:
            context = self._build_grounded_context(retrieved_documents)
        else:
            context = "No relevant documents were found."

        # Build citation list from retrieved documents' URLs (deduplicated)
        # Only include citations if documents have meaningful relevance scores
        citations_dict: Dict[str, Tuple[str, List[int]]] = {}  # Map URL to (label, doc_indices)

        # Check max relevance score - suppress citations if all docs are irrelevant.
        # When the user has disabled reranking, no doc has a `reranker_score`
        # (defaults to 0.0), so the standard floor would suppress every citation.
        # In that case we trust the retriever's BM25/RRF ranking and emit
        # citations for every doc.
        max_relevance = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0,
        )
        MIN_CITATION_RELEVANCE = 0.10  # Don't cite docs below 10% relevance
        reranker_skipped_for_citations = (
            state.get("optimizations", {}).get("reranking", True) is False
        )

        if reranker_skipped_for_citations or max_relevance >= MIN_CITATION_RELEVANCE:
            for i, doc in enumerate(retrieved_documents, 1):
                # Skip docs with very low relevance, but only when scores are real
                doc_score = doc.metadata.get("reranker_score", 0.0)
                if not reranker_skipped_for_citations and doc_score < MIN_CITATION_RELEVANCE:
                    continue

                url = self._citation_url_for_doc(doc)
                if not url:
                    continue
                # If URL already tracked, just append the doc index
                if url in citations_dict:
                    citations_dict[url][1].append(i)
                    continue
                # Use title first, fallback to extracted title from filename or path
                label = doc.metadata.get("title")
                if not label:
                    # Try to extract a readable title from filename/path
                    label = self._extract_title_from_path(
                        doc.metadata.get("source", doc.metadata.get("filename", ""))
                    )
                # If still no label, extract class/method name from source path
                if not label and "source" in doc.metadata:
                    source = doc.metadata["source"]
                    if source.endswith(".html"):
                        # Java documentation - extract class name
                        label = source.split("/")[-1].replace(".html", "")
                    elif source.endswith(".md"):
                        # Markdown - extract from path
                        parts = source.rstrip("/").split("/")
                        # Use filename, but improve readability
                        filename = parts[-1].replace(".md", "").replace(".mdx", "")
                        if filename.lower() != "readme":
                            label = filename.replace("_", " ").replace("-", " ").title()
                        elif len(parts) > 1:
                            label = parts[-2].replace("_", " ").replace("-", " ").title()
                if not label:
                    label = "Documentation"
                citations_dict[url] = (label, [i])
        else:
            logger.info(
                f"Suppressing citations: max_relevance={max_relevance:.3f} < {MIN_CITATION_RELEVANCE}"
            )

        # Convert to list format with document index prefixes
        citations = []
        for url, (label, indices) in citations_dict.items():
            index_prefix = ",".join(str(idx) for idx in indices)
            citations.append({"label": f"[{index_prefix}] {label}", "url": url})

        # LLM-off short-circuit: render a plain search-results list (no Gemini call).
        # Document order respects the reranker toggle — if reranking is off the
        # documents arrive here in retriever-determined order, otherwise in
        # reranker-scored order.
        if state.get("optimizations", {}).get("llm", True) is False:
            results_md = self._format_search_results(retrieved_documents, user_query)
            logger.info(
                f"Agent: LLM disabled, returning {len(retrieved_documents)} raw search results"
            )
            return {
                "messages": [AIMessage(content=results_md)],
                "citations": citations,
            }

        # Build recent conversation context (excluding the current query)
        recent_context = self._build_recent_context(messages)
        recent_context_block = f"Recent context:\n{recent_context}\n\n" if recent_context else ""

        # Create intent-aware prompt
        intent = state.get("intent", "search")

        # Intent-specific instructions
        if intent == "comparison":
            intent_instruction = """Your task is to COMPARE the retrieved products, highlighting key differences and trade-offs:
- Discuss quality, features, performance, price, and other relevant dimensions
- Help the user understand which product is best for their specific needs
- Clearly indicate product names and key differentiators
- Use a structured format (e.g., "Product A is better for X because..., while Product B excels at Y...")"""
        elif intent == "attribute_filter":
            intent_instruction = """Your task is to filter and present products matching specific criteria:
- Focus on products that match the requested attributes (color, size, price, features, etc.)
- For each product, clearly state which attributes it matches and which it doesn't
- Recommend the best matches first
- Be specific: e.g., "This product comes in blue and costs $45"
- If some requested attributes aren't available, note that clearly"""
        elif intent == "refinement":
            # Extract prior search category for explicit feedback
            prior_docs = state.get("prior_search_documents", [])
            prior_category = (
                self._extract_product_category_from_documents(prior_docs) if prior_docs else ""
            )
            prior_count = len(prior_docs)

            category_context = (
                f"From the {prior_count} {prior_category}"
                if prior_category
                else f"From the {prior_count} products"
            )

            intent_instruction = f"""Your task is to narrow the prior search results by applying the user's new constraint:
- Start with explicit context: "{category_context} I showed you earlier, here are the ones that match your new criteria:"
- State the new constraint being applied: "...filtering for [new attribute]..."
- List ONLY products that satisfy BOTH the original search AND the new constraint
- Where possible, cross-reference against products mentioned in the previous response
- If a previously recommended product also meets the new constraint, highlight it: "Notably, [Product X] from my earlier recommendations also meets this requirement"
- If no products satisfy both criteria, be honest: "None of the {prior_category} options I found earlier are [attribute]. Here are the closest matches..."
- Be specific about which attribute is being filtered (e.g., "waterproof", "under $100", "leather")"""
        elif intent == "follow_up":
            intent_instruction = """Your task is to refine your previous search results based on the user's follow-up:
- Connect this response to your previous recommendation(s)
- Address what the user is asking for (cheaper, different color, better features, etc.)
- Clearly show how new suggestions compare to earlier recommendations"""
        else:  # search (default)
            intent_instruction = """Your task is to help the user find products matching their needs:
- Recommend relevant products from the knowledge base
- Explain why each product is a good match for their stated needs
- Include key product features and specifications
- Help them make an informed decision"""

        system_prompt = f"""You are a helpful e-commerce product search assistant. Answer questions using a knowledge base of Amazon product listings.
{recent_context_block}RETRIEVED DOCUMENTS FROM KNOWLEDGE BASE:
{context}

INTENT: {intent.upper()}
{intent_instruction}

GROUNDING RULES (override creativity preferences — non-negotiable):
1. Every factual claim about a specific product (origin / "Made in X", material, certifications like "FDA-approved" or "BPA-free", size, manufacturer claims, pricing) MUST be supported by THAT product's FACTS block above.
2. Facts are PER-PRODUCT. If "Made in USA" appears in Product 3's FACTS but not in Product 1's FACTS, you MUST NOT attribute "Made in USA" to Product 1, even if it's the same brand or category.
3. If a fact is not in any FACTS block, OMIT it. Do not infer from brand reputation, product category, prior knowledge, or implication.
4. Comparison tables/summaries: every cell or claim must trace to a specific product's FACTS block. Leave cells blank rather than fabricating.
5. When writing about a product, prefer paraphrasing its FACTS over inventing supporting language.

CITATION & STYLE:
- Cite products descriptively by name (e.g., "the Nylabone 3 Pack Puppy Chew listing"), never as "Document N".
- DO NOT include URLs, hyperlinks, or markdown links (e.g., `[name](url)`) in your response. The system appends a verified "Sources" list separately — any link you write yourself will be wrong because you do not have access to canonical product URLs.
- Refer to products by name only. Do not write `https://...`, `amazon.com/...`, `[text](http...)`, or any link-shaped text.
- If you cannot find relevant products, explain what you searched for, suggest two or three alternative searches the user could try (different brand, broader category, related use case), and end with an open question that invites them to share more about what they need.
- Tone: warm, conversational, and encouraging — like a knowledgeable friend helping them shop. Avoid dismissive phrasing ("you need to narrow down", "I can't help with that"). Prefer guiding language ("a few details would help me find the right fit", "here are some directions worth trying").
"""

        # Build messages for LLM
        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query or "Please summarize the context."),
        ]

        # Generate response with streaming if available
        if hasattr(self.llm, "stream") and callable(getattr(self.llm, "stream")):
            response = self._stream_llm_response_simple(llm_messages)
        else:
            logger.debug("LLM does not support streaming, using invoke()")
            response = self.llm.invoke(llm_messages)

        # Strip any inline URLs the LLM emitted in spite of the prompt — ESCI
        # ASINs are frequently delisted on Amazon and the model also hallucinates
        # the same ID across distinct products (issue #4). The system-generated
        # `citations` list below is the authoritative link surface.
        if hasattr(response, "content") and isinstance(response.content, str):
            stripped = self._strip_inline_links(response.content)
            if stripped != response.content:
                logger.info("Agent: stripped inline URLs from LLM response")
                response = AIMessage(content=stripped)

        # Calculate response statistics
        response_length = len(response.content) if hasattr(response, "content") else 0
        elapsed = time.time() - start_time

        logger.info(f"Agent: generated response ({response_length} chars) in {elapsed:.3f}s")

        return {"messages": [response], "citations": citations}

    def _build_recent_context(self, messages: Sequence[BaseMessage], limit: int = 6) -> str:
        """
        Format a short history block from the most recent messages (excluding the current query).
        """
        if not messages:
            return ""

        history_entries: list[str] = []
        recent_messages = list(messages)

        # Drop the current query if it's the last message (it will be appended separately)
        if recent_messages and isinstance(recent_messages[-1], HumanMessage):
            recent_messages = recent_messages[:-1]

        for msg in reversed(recent_messages):
            content = getattr(msg, "content", "")
            if not content or not str(content).strip():
                continue
            label = self._label_for_message(msg)
            history_entries.append(f"{label}: {str(content).strip()}")
            if len(history_entries) >= limit:
                break

        history_entries.reverse()
        return "\n".join(history_entries)

    def _expand_vague_query(self, query: str, messages: Sequence[BaseMessage]) -> str:
        """
        Expand follow-up queries using LLM and conversation context.

        Lets the LLM intelligently decide if a query needs expansion and
        what the expanded query should be based on conversation context.

        Args:
            query: The user's query
            messages: Conversation history

        Returns:
            Expanded query with topic context, or original query if expansion not needed
        """
        # Filter to user turns only — AI responses (product listings) inflate the query bloat.
        # For resolving what the user meant ("those", "the one you mentioned"),
        # only user context matters; AI descriptions are irrelevant and cause maxClauseCount errors (issue #85).
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]
        context = self._build_recent_context(user_messages, limit=4)
        if not context:
            return query

        # Let LLM decide if expansion is needed based on context
        prompt = f"""Given the conversation context and a follow-up message, determine if the message needs expansion to be self-contained.

USER MESSAGE: "{query}"

CONVERSATION CONTEXT:
{context}

TASK:
If the message references previous context (pronouns, comparisons, vague mentions), rewrite it to be self-contained.
Otherwise, return it unchanged.

RULES:
- Replace pronouns ("it", "them", "those") with actual names from context
- Expand vague references ("For a wedding", "In winter") with previous topic context
- For comparisons ("Which is cheaper?"), include what's being compared
- If already self-contained, return unchanged

Return ONLY the query text, nothing else."""

        try:
            response = self.alpha_estimator_llm.invoke(prompt)
            expanded = _flatten_llm_content(response).strip()

            # Remove any quotes the LLM might have added
            expanded = expanded.strip("\"'")

            # Sanity check - don't accept empty or very long expansions
            if not expanded or len(expanded) > 500:
                return query

            if expanded != query:
                logger.info(f"Query expansion: '{query}' → '{expanded}'")
                # Emit query expansion event
                if QueryExpansionEvent:
                    try:
                        self._emit_event_from_sync(
                            QueryExpansionEvent(
                                original_query=query,
                                expanded_query=expanded,
                                expansion_reason="Follow-up expanded with conversation context",
                            )
                        )
                    except Exception as emit_error:
                        logger.debug(f"Could not emit query expansion event: {emit_error}")

            return expanded
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}, using original query")
            return query

    def _extract_product_category_from_documents(self, docs: List[Document]) -> str:
        """
        Extract primary product category from document titles.

        Uses LLM fast-path to infer category from first 5 product titles.
        Examples: "boots", "headphones", "dresses", "shoes", "electronics"

        Args:
            docs: List of documents to extract category from

        Returns:
            Inferred product category (lowercase string), or empty string if unknown
        """
        if not docs:
            return ""

        try:
            # Extract first 5 titles for category inference
            titles = [
                doc.metadata.get("title", "") for doc in docs[:5] if doc.metadata.get("title")
            ]

            if not titles:
                return ""

            # Use fast LLM to categorize (Lite model for speed)
            prompt = f"""Based on these product titles, what is the primary product category?
Answer with ONLY the category name in lowercase (e.g., boots, headphones, shoes, dresses).
Do not include any explanation.

Titles:
{chr(10).join(titles)}"""

            response = self.query_eval_llm.invoke(prompt)
            category = _flatten_llm_content(response).strip().lower()

            # Validate response is a single word/category
            if category and len(category) < 50 and " " not in category:
                logger.debug(f"Extracted product category from documents: '{category}'")
                return category

            return ""
        except Exception as e:
            logger.debug(f"Category extraction from documents failed: {e}")
            return ""

    def _extract_product_category_from_query(self, query: str) -> str:
        """
        Extract product category mention from user query using patterns.

        First tries keyword patterns (fast), then LLM for unknown categories.
        Examples: "boots", "headphones", "dresses", "shoes"

        Args:
            query: User query string

        Returns:
            Inferred product category (lowercase string), or empty string if unknown
        """
        if not query:
            return ""

        query_lower = query.lower()

        # Quick pattern matching for common product types
        category_patterns = {
            "boots": ["boot", "bootie", "ankle boot"],
            "shoes": ["shoe", "sneaker", "loafer", "heel", "pump"],
            "headphones": ["headphone", "earbud", "earphone", "headset", "wireless"],
            "dresses": ["dress", "gown", "evening", "cocktail", "maxi"],
            "shirts": ["shirt", "t-shirt", "top", "blouse"],
            "pants": ["pant", "trouser", "jean", "jeans", "legging"],
            "jackets": ["jacket", "coat", "blazer", "cardigan"],
            "watches": ["watch", "smartwatch", "timepiece"],
            "bags": ["bag", "purse", "backpack", "handbag", "tote"],
            "electronics": ["phone", "laptop", "tablet", "computer", "device"],
        }

        for category, keywords in category_patterns.items():
            if any(kw in query_lower for kw in keywords):
                logger.debug(f"Detected product category from query via pattern: '{category}'")
                return category

        # Fallback to LLM for unknown categories
        try:
            prompt = f"""What product category does this query mention?
Answer with ONLY the category name in lowercase (e.g., boots, headphones, shoes, dresses).
If no specific category is mentioned, respond with empty string.
Do not include any explanation.

Query: "{query}" """

            response = self.query_eval_llm.invoke(prompt)
            category = _flatten_llm_content(response).strip().lower()

            if category and len(category) < 50 and " " not in category:
                logger.debug(f"Detected product category from query via LLM: '{category}'")
                return category
        except Exception as e:
            logger.debug(f"Category extraction from query (LLM) failed: {e}")

        return ""

    def _validate_category_continuity(
        self,
        prior_docs: List[Document],
        current_query: str,
        current_results: List[Document],
    ) -> Tuple[float, str]:
        """
        Validate if current query continues prior search or starts new.

        Calculates continuity score (0.0-1.0) based on:
        1. Product category match (extracted from prior docs vs query)
        2. Document ID overlap (% of prior results still in new results)

        Returns:
            (continuity_score, reasoning_text)
            - Score > 0.7: "Strong category continuity"
            - Score 0.3-0.7: "Ambiguous category continuity"
            - Score < 0.3: "Different product categories"
        """
        if not prior_docs:
            return 0.5, "No prior search context available"

        scores = []
        reasons = []

        # 1. Category name matching
        prior_category = self._extract_product_category_from_documents(prior_docs)
        current_category = self._extract_product_category_from_query(current_query)

        if prior_category and current_category:
            if prior_category == current_category:
                scores.append(1.0)
                reasons.append(f"Category match: {prior_category} == {current_category}")
            elif self._are_related_categories(prior_category, current_category):
                scores.append(0.7)
                reasons.append(f"Related categories: {prior_category} ≈ {current_category}")
            else:
                scores.append(0.0)
                reasons.append(f"Different categories: {prior_category} ≠ {current_category}")
        elif current_category:
            scores.append(0.5)
            reasons.append(f"Could not extract prior category, current: {current_category}")

        # 2. Document ID overlap
        prior_ids = {
            doc.metadata.get("product_id") for doc in prior_docs if doc.metadata.get("product_id")
        }
        current_ids = {
            doc.metadata.get("product_id")
            for doc in current_results
            if doc.metadata.get("product_id")
        }

        if prior_ids:
            overlap = len(prior_ids & current_ids) / len(prior_ids)
            scores.append(overlap)
            reasons.append(f"Document overlap: {overlap:.1%} of prior results")

        # Calculate final score
        final_score = sum(scores) / len(scores) if scores else 0.5

        # Generate reasoning
        if final_score > 0.7:
            conclusion = "Strong category continuity - treating as refinement"
        elif final_score > 0.3:
            conclusion = "Ambiguous category continuity - need clarification"
        else:
            conclusion = "Different product categories - treating as new search"

        full_reasoning = f"{conclusion} (score: {final_score:.2f}). " + "; ".join(reasons)

        logger.info(f"Category continuity check: {full_reasoning}")

        return final_score, full_reasoning

    @staticmethod
    def _are_related_categories(cat1: str, cat2: str) -> bool:
        """Check if two categories are related (e.g., 'boots' and 'shoes')."""
        related_groups = [
            {"boots", "shoes", "sneakers", "heels", "loafers"},
            {"headphones", "earbuds", "earphones", "headsets"},
            {"dresses", "gowns", "shirts", "tops", "blouses"},
            {"pants", "trousers", "jeans", "leggings"},
        ]

        for group in related_groups:
            if cat1 in group and cat2 in group:
                return True
        return False

    def _extract_attributes(self, query: str) -> list:
        """
        Extract product attributes from attribute_filter queries.

        Returns a list of OpenSearch filter clauses for:
        - product_brand: Brand names ("Sony", "Apple", "Nike", etc.)
        - product_color: Colors ("blue", "red", "black", etc.)

        Args:
            query: The user's attribute filter query

        Returns:
            List of OpenSearch filter objects (to be combined with AND in filter context),
            or empty list if no attributes found
        """
        if not query or len(query) < 5:
            return []

        prompt = f"""Extract product attributes from a shopping query. Return ONLY a JSON object.

QUERY: "{query}"

Extract these attributes if present:
- brand: Product brand/manufacturer (e.g., "Sony", "Apple", "Nike")
- color: Product color (e.g., "blue", "black", "red", "white", "silver")
- material_or_feature: Physical feature or material keyword users add as constraints
  (e.g., "waterproof", "breathable", "insulated", "vegan leather", "leather", "mesh",
   "wireless", "noise canceling", "anti-slip", "slip-resistant", "Gore-Tex")
- size: Size specification (e.g., "size 10", "XL", "large", "medium", "10.5")
- price_max: Maximum price as a number only if "under $X" or "less than $X" present (e.g., 100)
- price_min: Minimum price as a number only if "over $X" or "more than $X" present (e.g., 50)

Return ONLY a JSON object (use null for missing attributes):
{{"brand": "...", "color": "...", "material_or_feature": "...", "size": "...", "price_max": null, "price_min": null}}"""

        try:
            response = self.alpha_estimator_llm.invoke(prompt)
            text = _flatten_llm_content(response).strip()

            # Extract JSON from response
            import json
            import re

            json_match = re.search(r"\{.*?\}", text, re.DOTALL)
            if not json_match:
                return []

            attributes = json.loads(json_match.group())
            filters = []

            # Coerce LLM-extracted attribute values to strings. Gemini sometimes
            # returns array values (e.g. material_or_feature=["noise canceling"])
            # even when the prompt asks for a single string. Passing a list to
            # an OpenSearch ``query`` field fails with
            #   [multi_match] unknown token [START_ARRAY] after [query]
            def _coerce(val: Any) -> Optional[str]:
                if val is None:
                    return None
                if isinstance(val, list):
                    parts = [str(v).strip() for v in val if v not in (None, "")]
                    return " ".join(parts) if parts else None
                s = str(val).strip()
                return s or None

            # Build OpenSearch filter clauses (as separate filter objects - they're implicitly AND'd)
            brand = _coerce(attributes.get("brand"))
            if brand:
                filters.append({"match": {"product_brand_normalized": {"query": brand}}})

            color = _coerce(attributes.get("color"))
            if color:
                filters.append({"match": {"product_color_primary": {"query": color}}})

            # material_or_feature → multi_match against title + content
            material = _coerce(attributes.get("material_or_feature"))
            if material:
                filters.append(
                    {
                        "multi_match": {
                            "query": material,
                            "fields": ["title", "chunk_text"],
                            "type": "best_fields",
                        }
                    }
                )

            # size → multi_match against title + content
            size = _coerce(attributes.get("size"))
            if size:
                filters.append(
                    {
                        "multi_match": {
                            "query": size,
                            "fields": ["title", "chunk_text"],
                            "type": "best_fields",
                        }
                    }
                )

            # price range → range filter (if price field exists in index)
            if attributes.get("price_max") is not None:
                try:
                    filters.append({"range": {"price": {"lte": float(attributes["price_max"])}}})
                except (ValueError, TypeError):
                    logger.debug(f"Could not parse price_max: {attributes.get('price_max')}")

            if attributes.get("price_min") is not None:
                try:
                    filters.append({"range": {"price": {"gte": float(attributes["price_min"])}}})
                except (ValueError, TypeError):
                    logger.debug(f"Could not parse price_min: {attributes.get('price_min')}")

            return filters

        except Exception as e:
            logger.debug(f"Attribute extraction failed: {e}")
            return []

    def _format_filter_summary(self, filters: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """
        Format filter objects into human-readable summary.

        Example:
            [{"match": {"product_brand": {"query": "Sony"}}}]
            → "brand: Sony"
        """
        if not filters:
            return None

        try:
            parts = []
            for f in filters:
                if "match" in f:
                    match_obj = f["match"]
                    if "product_brand" in match_obj:
                        query = match_obj["product_brand"].get("query", "")
                        parts.append(f"brand: {query}")
                    elif "product_color" in match_obj:
                        query = match_obj["product_color"].get("query", "")
                        parts.append(f"color: {query}")
                elif "multi_match" in f:
                    mm = f["multi_match"]
                    query_text = mm.get("query", "")
                    fields = mm.get("fields", [])
                    if "chunk_text" in fields or "title" in fields:
                        parts.append(f"feature: {query_text}")
                elif "range" in f:
                    range_obj = f["range"]
                    if "price" in range_obj:
                        price_range = range_obj["price"]
                        if "lte" in price_range:
                            parts.append(f"price: under ${price_range['lte']}")
                        if "gte" in price_range:
                            parts.append(f"price: over ${price_range['gte']}")
            return ", ".join(parts) if parts else None
        except Exception:
            logger.warning("Failed to format filter summary", exc_info=True)
            return None

    def _classify_intent(
        self, user_input: str, messages: Sequence[BaseMessage]
    ) -> tuple[str, str, float, list]:
        """
        Classify user intent using LLM.

        Returns:
            Tuple of (intent, reasoning, confidence, clarifying_questions)
            - intent: The classified intent (question, summary, follow_up, clarify)
            - reasoning: Explanation for the classification
            - confidence: 0.0-1.0 confidence score
            - clarifying_questions: List of questions to ask if confidence is low
        """

        prompt = self._build_intent_prompt(user_input, messages)

        structured_llm = self.intent_structured or self.llm.with_structured_output(
            IntentClassification
        )
        try:
            result = structured_llm.invoke(prompt)
            intent = result.intent.strip().lower()
            reasoning = result.reasoning
            confidence = result.confidence
            clarifying_questions = result.clarifying_questions

            # If confidence is below threshold, switch to clarify intent — UNLESS
            # there's already a product search in the conversation, in which case
            # the new message is almost certainly a follow_up/refinement (audience,
            # situation, or vague expansion). Asking for clarification mid-thread
            # is jarring and discards the user's context.
            CONFIDENCE_THRESHOLD = 0.7
            if confidence < CONFIDENCE_THRESHOLD and clarifying_questions:
                prior_human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
                has_prior_context = len(prior_human_msgs) > 1
                if has_prior_context:
                    logger.info(
                        f"Low confidence ({confidence:.2f}) but prior context exists — "
                        f"downgrading clarify to follow_up"
                    )
                    return "follow_up", reasoning, confidence, []
                logger.info(f"Low confidence ({confidence:.2f}), will ask for clarification")
                return "clarify", reasoning, confidence, clarifying_questions

            # Guard: refinement requires prior conversation context
            if intent == "refinement":
                prior_human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
                if len(prior_human_msgs) <= 1:  # Only the current message, no prior context
                    logger.info(
                        "Refinement intent with no prior context — downgrading to attribute_filter"
                    )
                    intent = "attribute_filter"

            return intent, reasoning, confidence, clarifying_questions
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return (
                "question",
                f"Classification failed, defaulting to question: {str(e)[:50]}",
                0.5,
                [],
            )

    def _build_intent_prompt(self, user_input: str, messages: Sequence[BaseMessage]) -> str:
        """Build the LLM prompt for intent classification, including recent conversation context."""
        history_block = self._build_recent_context(messages, limit=6)

        # Available intents for e-commerce product search
        available_intents = [
            "search",
            "comparison",
            "attribute_filter",
            "refinement",
            "follow_up",
            "summary",
        ]

        intents_str = "|".join(available_intents)
        example_intent = "search"

        prompt = f"""Classify user intent for e-commerce product search. Return ONLY valid JSON.

CRITICAL - CHECK THESE KEYWORDS FIRST (in order):
1. Is message a short acknowledgment (<5 words: "ok", "got it", "thanks", "understood", "yes", "no", "perfect")? → follow_up (ALWAYS)
2. Does message contain "summarize", "recap", "summary", "what have we covered"? → summary (ALWAYS)
3. Does message compare two or more products? ("Compare X vs Y", "Which is better: X or Y?", "How does X compare to Y?") → comparison (ALWAYS)
4. Does message add a NEW constraint to a PRIOR product search in this conversation? ("they should also be waterproof", "make them under $100", "only in leather", "but size 10", "can they also be breathable?") AND prior search exists in history? → refinement (ALWAYS - takes priority over attribute_filter when prior search exists)
5. Does message add SITUATIONAL or AUDIENCE context to a prior product search? ("my coworkers will be there", "it's an outdoor event", "the venue is fancy", "I'm 5'8\"", "I'll be the host", "it's a daytime event") AND prior search exists? → refinement (ALWAYS — context narrows the prior search even without an explicit product attribute)
6. Does message request products with specific attributes (standalone, no prior context)? ("Show me X in [color/size/brand]", "Find X with [attribute]", "X under/over [price]") → attribute_filter (ALWAYS)
7. Is message vague expansion? ("more", "show", "tell me", "alternatives", "cheaper", "similar", "other options") → follow_up (ALWAYS)
8. Everything else (general product searches) → search (DEFAULT)

IMPORTANT FOR E-COMMERCE:
- "Find wireless headphones" → search (general discovery)
- "Compare Sony vs Bose headphones" → comparison (product comparison)
- "Show me headphones in blue under $100" → attribute_filter (specific attributes, standalone)
- "Oh, they should also be waterproof" (after boot search) → refinement (constraint added to prior search)
- "Make them under $100" (after showing options) → refinement (narrowing prior search)
- "My coworkers will all be there" (after dress search) → refinement (audience context narrows the prior search)
- "It's an outdoor event" (after attire search) → refinement (situational context narrows the prior search)
- "But they need to be waterproof" (no prior context) → attribute_filter (standalone filter)
- "Tell me more about those" → follow_up (vague expansion)

WHEN PRIOR PRODUCT SEARCH EXISTS, prefer follow_up or refinement over clarify — even if the new message is short or doesn't name a product. Only fall back to clarify when the message is genuinely incomprehensible in the surrounding context.

AVAILABLE INTENTS: {intents_str}

OUTPUT FORMAT:
{{
  "intent": "{example_intent}",  // MUST be one of: {intents_str}
  "reasoning": "Brief explanation",
  "confidence": 0.0-1.0,
  "clarifying_questions": ["Question 1?", "Question 2?"]  // Only if confidence < 0.7
}}

CLASSIFICATION RULES:

1. SEARCH: General product discovery and information queries
   - User is looking for products without specific filtering or comparison
   - Examples: "Find wireless headphones", "What are the best gaming laptops?", "Show me running shoes"
   - Key: Open-ended product search - the DEFAULT intent for most queries

2. COMPARISON: User wants to compare two or more products
   - Keywords: "compare", "vs", "versus", "which is better", "how does X compare to Y", "difference between"
   - Examples: "Compare Sony WH-1000XM5 vs Bose QuietComfort 45", "Which is better: Apple Watch or Garmin?"
   - Key: User wants to understand differences/tradeoffs between products

3. ATTRIBUTE_FILTER: User requests products with specific attributes/filters (standalone)
   - Keywords: colors, sizes, brands, prices, features, ranges
   - Examples: "Show me headphones in blue under $100", "Find wireless earbuds with 30+ hour battery", "Running shoes in size 10"
   - Key: User has specific attribute requirements (color/size/brand/price/feature) WITHOUT prior search context
   - Pattern: "[Product] with/in [attribute] [value]" or "[Product] under/over [price]"

4. REFINEMENT: User adds a NEW constraint to a prior product search in this conversation
   - REQUIRES: Conversation history must contain a prior product search
   - Keywords/patterns: "they should also", "but also", "make them", "only if", "can they be", "I want ones that are", implicit constraint additions using pronouns
   - Examples: "Oh, they should also be waterproof" (after "show me men's boots"), "Make them under $100" (after showing headphones), "Can they also be breathable?" (after running shoe search)
   - CONTRAST with ATTRIBUTE_FILTER: "Show me waterproof boots" with NO prior search → attribute_filter
   - CONTRAST with FOLLOW_UP: "Tell me more about those" (vague, no new constraint) → follow_up

5. FOLLOW_UP: Vague continuation/expansion requests that need conversation context
   - Vague expansion: "show me more", "tell me more", "other options", "alternatives", "something cheaper"
   - Short acknowledgments: "ok", "got it", "thanks", "yes", "no"
   - Key: Request only makes sense with conversation history
   - Examples: "Any cheaper alternatives?", "Tell me more about that one", "What else do you have?"

6. SUMMARY: User explicitly requests a recap of the conversation
   - Keywords: "summarize", "recap", "summary", "what have we covered"
   - Examples: "Summarize what we discussed", "What products did we look at?"

PRIORITY ORDER - Check in this exact order:
1. SUMMARY if "summarize", "recap", or "summary" present
2. FOLLOW_UP if very short acknowledgment or vague expansion keyword
3. COMPARISON if "compare", "vs", "which is better", "how does X compare"
4. REFINEMENT if a new constraint is being added to a PRIOR search (check conversation history for prior product search)
5. ATTRIBUTE_FILTER if specific attribute/filter keywords AND no prior search context
6. SEARCH for everything else (DEFAULT)

CONFIDENCE GUIDELINES:
- 0.9-1.0: Very clear intent, unambiguous message
- 0.7-0.9: Reasonably clear, minor ambiguity
- 0.5-0.7: Ambiguous, could be interpreted multiple ways
- 0.0-0.5: Very unclear, need more context

IF CONFIDENCE < 0.7:
- Provide 1-3 clarifying questions in "clarifying_questions" array
- Questions should help disambiguate the user's intent
- Keep questions concise and specific

USER MESSAGE: "{user_input}"

CONVERSATION HISTORY:
{history_block or 'No prior context.'}

Respond with JSON only. No other text."""
        return prompt

    def _label_for_message(self, message: BaseMessage) -> str:
        """Return a human-readable role label for a message (User / Assistant / Tool)."""
        if isinstance(message, HumanMessage):
            return "User"
        if isinstance(message, AIMessage):
            return "Assistant"
        if isinstance(message, ToolMessage):
            tool_name = getattr(message, "tool_name", "tool")
            return f"Tool:{tool_name}"
        if isinstance(message, SystemMessage):
            return "System"
        return "Message"

    def _extract_title_from_path(self, path: str) -> str:
        """
        Extract a readable title from a file path.

        Examples:
        - src/oss/python/concepts/langchain.md → "LangChain Concepts"
        - src/oss/python/integrations/llms/moonshot.mdx → "Moonshot LLM Integration"
        - docs/how-to/vector_stores.md → "Vector Stores How-To"
        """
        if not path:
            return ""

        # Extract filename without extension
        import os

        filename = os.path.splitext(os.path.basename(path))[0]

        # Skip common non-document filenames
        if filename in ("index", "readme", "_", "__"):
            return ""

        # Convert snake_case/kebab-case to Title Case
        title = filename.replace("_", " ").replace("-", " ")

        # Add context from parent directories if helpful
        parts = path.split("/")
        if len(parts) >= 2:
            parent_dir = parts[-2].lower()
            # Add doc type suffix from path
            if parent_dir in ("concepts", "conceptual"):
                title = f"{title.title()} Concepts"
            elif parent_dir in ("how-to", "how_to"):
                title = f"{title.title()} How-To"
            elif parent_dir == "tutorials":
                title = f"{title.title()} Tutorial"
            elif parent_dir in ("quickstart", "getting-started", "getting_started"):
                title = f"{title.title()} Quickstart"
            elif parent_dir == "integrations":
                title = f"{title.title()} Integration"
            elif parent_dir == "llms":
                title = f"{title.title()} LLM"
            elif parent_dir == "tools":
                title = f"{title.title()} Tool"
            elif parent_dir == "chat_models":
                title = f"{title.title()} Chat Model"
            else:
                title = title.title()
        else:
            title = title.title()

        return title

    def _stream_llm_response_simple(self, messages: Sequence[BaseMessage]) -> AIMessage:
        """
        Stream the LLM response and accumulate the full response while emitting events.

        Simplified version without tool binding - for direct response generation.

        Args:
            messages: The input messages for the LLM

        Returns:
            The accumulated AIMessage response
        """
        stream_start = time.time()

        # Emit start event (if event classes are available)
        if LLMResponseStartEvent is not None:
            start_event = LLMResponseStartEvent()
            self._emit_streaming_event(start_event)

        # Accumulate response content
        accumulated_content = ""
        chunk_count = 0

        try:
            # Stream from the LLM
            for chunk in self.llm.stream(messages):
                chunk_count += 1

                # Extract content from chunk (handle both string and Gemini's list format)
                if hasattr(chunk, "content") and chunk.content:
                    content = chunk.content

                    # Extract text if content is a list of content blocks (Gemini format)
                    if isinstance(content, list):
                        text_parts = []
                        for block in content:
                            if isinstance(block, dict) and "text" in block:
                                text_parts.append(block["text"])
                        content = "".join(text_parts) if text_parts else ""

                    # Only accumulate and emit non-empty string content
                    if content and isinstance(content, str):
                        accumulated_content += content

                        # Emit chunk event (if event classes are available)
                        if LLMResponseChunkEvent is not None:
                            chunk_event = LLMResponseChunkEvent(content=content, is_complete=False)
                            self._emit_streaming_event(chunk_event)

        except StopIteration:
            pass
        except RuntimeError as e:
            if "StopIteration" not in str(e):
                logger.warning(f"RuntimeError during LLM streaming: {e}. Falling back to invoke.")
        except Exception as e:
            logger.warning(f"Exception during LLM streaming: {e}. Falling back to invoke.")

        # If streaming produced no content, fall back to invoke
        if not accumulated_content:
            invoke_result = self.llm.invoke(messages)
            if hasattr(invoke_result, "content"):
                accumulated_content = invoke_result.content if invoke_result.content else ""
            else:
                accumulated_content = str(invoke_result)

        # Emit completion event (if event classes are available)
        if LLMResponseChunkEvent is not None:
            completion_event = LLMResponseChunkEvent(content="", is_complete=True)
            self._emit_streaming_event(completion_event)

        stream_elapsed = time.time() - stream_start
        logger.debug(
            f"Streaming complete: {chunk_count} chunks, {len(accumulated_content)} chars in {stream_elapsed:.3f}s"
        )

        return AIMessage(content=accumulated_content)

    def _emit_streaming_event(self, event) -> None:
        """
        Emit a streaming event (for future integration with WebSocket or event listeners).

        Currently logs the event. Can be extended to:
        - Send events to WebSocket clients
        - Broadcast to observability systems
        - Update real-time dashboards

        Args:
            event: The streaming event to emit
        """
        if event is None:
            return

        if LLMResponseStartEvent is not None and isinstance(event, LLMResponseStartEvent):
            logger.debug("LLM streaming started")
        elif LLMResponseChunkEvent is not None and isinstance(event, LLMResponseChunkEvent):
            if event.is_complete:
                logger.debug("LLM streaming complete")
            else:
                logger.debug(f"LLM chunk received: {len(event.content)} chars")

    def _emit_event_from_sync(self, event) -> None:
        """
        Emit an event from a synchronous context immediately.

        This is called from retriever_node to emit intermediate events
        (hybrid search result, reranker start) as they happen.

        Uses asyncio.run_coroutine_threadsafe to schedule the emit in the
        running event loop without blocking.
        """
        if not self.emit_callback or not self.event_loop:
            return

        try:
            # Use the stored event loop that was set when emit_callback was assigned
            asyncio.run_coroutine_threadsafe(self.emit_callback(event), self.event_loop)
            # Don't wait for the result - let it run asynchronously
        except Exception as e:
            # Fallback: queue the event if we can't emit directly
            logger.debug(f"Could not emit event immediately: {e}, queueing instead")
            self.event_queue.append(event)

    def llm_judge_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        LLM-as-judge for the Pipeline Quality Summary "Generation" stage.

        Compares the agent's synthesized response (whatever was just produced
        by ``agent_node``) against the deterministic raw-list response that
        ``optimizations.llm:false`` would have produced, and emits a
        structured ``JudgmentResult`` with a pairwise verdict + 4 absolute
        scores + hallucination list.

        Skipped (returns ``judgment=None``) when:
          * ``optimizations.llm_judge`` is False (per-query toggle), OR
          * ``optimizations.llm`` is False (nothing to judge — the raw list
            IS the response), OR
          * ``intent == "summary"`` (no retrieval, nothing to compare), OR
          * No retrieved documents.
        """
        opts = state.get("optimizations") or {}
        llm_on = opts.get("llm", True)
        judge_on = opts.get("llm_judge", False)
        intent = state.get("intent", "search")
        documents = state.get("retrieved_documents") or []

        if not (llm_on and judge_on) or intent == "summary" or not documents:
            return {"judgment": None, "judge_latency_ms": 0.0}

        # Pull the agent's just-produced response from the message history.
        llm_response = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                content = msg.content
                if isinstance(content, list):
                    text_parts = []
                    for block in content:
                        if isinstance(block, dict) and "text" in block:
                            text_parts.append(block["text"])
                    llm_response = "".join(text_parts)
                else:
                    llm_response = content
                break

        if not llm_response:
            logger.debug("llm_judge_node: no agent response found, skipping judge")
            return {"judgment": None, "judge_latency_ms": 0.0}

        # Compute the deterministic baseline that llm:false would have produced.
        query = state.get("user_query", "")
        baseline = self._format_search_results(documents, query)

        # Lazy-init the judge so users who never enable it pay no startup cost.
        if self.judge is None:
            from config import (  # local import to avoid circular at module load
                JUDGE_MODEL,
            )

            self.judge = LLMJudge(model_name=JUDGE_MODEL)

        t0 = time.time()
        try:
            result = self.judge.judge(query, documents, llm_response, baseline)
        except Exception as exc:
            logger.warning("llm_judge_node failed: %s", exc, exc_info=True)
            return {"judgment": None, "judge_latency_ms": (time.time() - t0) * 1000.0}

        elapsed_ms = (time.time() - t0) * 1000.0
        logger.info(
            "llm_judge_node: verdict=%s, faithfulness=%.2f, in %.0fms",
            result.verdict,
            result.faithfulness,
            elapsed_ms,
        )

        # Auto-retry path (Layer 3a). Triggered when at least one flagged
        # claim is fabrication / cross_product_bleed AND we haven't already
        # retried this turn. The faithfulness score is NOT checked here —
        # the LLM judge can assign a high score (e.g. 0.90) while simultaneously
        # flagging dangerous fabrications, making the score an unreliable gate.
        # Categorical claim classification is the authoritative signal (issue #77).
        # Inference- or overreach-only flags surface to the UI but skip the
        # ~20–30s retry — regenerating those usually makes the answer worse.
        retry_worthy_claims = [
            h for h in result.hallucinations if h.category in RETRY_ELIGIBLE_CATEGORIES
        ]
        retry_eligible = len(retry_worthy_claims) > 0 and not state.get(
            "hallucination_retry_used", False
        )
        if not retry_eligible:
            if result.hallucinations:
                logger.info(
                    "llm_judge_node: skipping retry — %d flag(s) but none are "
                    "fabrication/cross_product_bleed (inference/overreach only).",
                    len(result.hallucinations),
                )
            return {
                "judgment": result.model_dump(),
                "judge_latency_ms": elapsed_ms,
            }

        logger.info(
            "llm_judge_node: auto-retrying — faithfulness=%.2f, %d retry-worthy "
            "flag(s) of %d total",
            result.faithfulness,
            len(retry_worthy_claims),
            len(result.hallucinations),
        )
        try:
            corrected = self._regenerate_without_hallucinations(
                query, documents, llm_response, [h.claim for h in retry_worthy_claims]
            )
        except Exception as exc:
            logger.warning("Auto-retry regeneration failed: %s", exc, exc_info=True)
            return {
                "judgment": result.model_dump(),
                "judge_latency_ms": elapsed_ms,
            }

        try:
            new_baseline = self._format_search_results(documents, query)
            new_result = self.judge.judge(query, documents, corrected, new_baseline)
        except Exception as exc:
            logger.warning("Auto-retry re-judge failed: %s", exc, exc_info=True)
            return {
                "judgment": result.model_dump(),
                "judge_latency_ms": elapsed_ms,
            }

        total_ms = (time.time() - t0) * 1000.0
        logger.info(
            "llm_judge_node: retry result faithfulness=%.2f → %.2f, flags %d → %d",
            result.faithfulness,
            new_result.faithfulness,
            len(result.hallucinations),
            len(new_result.hallucinations),
        )
        return {
            "judgment": new_result.model_dump(),
            "original_judgment": result.model_dump(),
            "corrected_response": corrected,
            "hallucination_retry_used": True,
            "judge_latency_ms": total_ms,
        }

    def _regenerate_without_hallucinations(
        self,
        query: str,
        documents: List["Document"],
        original_response: str,
        hallucinations: List[str],
    ) -> str:
        """Re-prompt the agent's LLM with explicit 'do not say X' instructions.

        Used by the auto-retry path in ``llm_judge_node``. Returns the new
        response string (no streaming, no state mutation).
        """
        forbidden = "\n".join(f"  - {h}" for h in hallucinations)
        context = self._build_grounded_context(documents)
        correction_prompt = f"""Your previous response to "{query}" contained UNSUPPORTED claims that are NOT in the retrieved product descriptions. You MUST omit them and stay strictly grounded.

UNSUPPORTED CLAIMS YOU MADE (do NOT include these in the new response):
{forbidden}

PREVIOUS RESPONSE (for reference — rewrite it without the unsupported claims):
{original_response}

RETRIEVED PRODUCTS:
{context}

GROUNDING RULES (non-negotiable):
- Every factual claim about a specific product must appear in THAT product's FACTS block above.
- Facts are PER-PRODUCT — never transfer a fact from one product's FACTS block to another product.
- If a fact (e.g. "Made in USA", "BPA-free", certifications, country of origin) isn't in a product's FACTS, OMIT it for that product. Do not infer.
- Keep the helpful structure (recommendations, comparisons, summaries) but ground every detail in the FACTS blocks.

Regenerate the response to the original query, removing all unsupported claims. Preserve the helpful synthesis.

Original query: {query}
"""
        messages = [
            SystemMessage(
                content=(
                    "You are a careful product-search assistant. Stay strictly grounded in "
                    "the provided FACTS blocks. Omit any claim you cannot trace to a "
                    "specific product's FACTS."
                )
            ),
            HumanMessage(content=correction_prompt),
        ]
        response = self.llm.invoke(messages)
        # Gemini may return ``content`` as a list of content blocks
        # ([{"type": "text", "text": "..."}, ...]) — flatten to a string
        # so downstream Pydantic models accept it.
        content = getattr(response, "content", response)
        if isinstance(content, list):
            text_parts = []
            for block in content:
                if isinstance(block, dict) and "text" in block:
                    text_parts.append(block["text"])
                elif isinstance(block, str):
                    text_parts.append(block)
            return "".join(text_parts)
        return content if isinstance(content, str) else str(content)

    def summary_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Generate a conversation summary when the user intent is to summarize history.
        """
        intent = state.get("intent", "question")
        messages = state["messages"]
        if intent != "summary":
            return {"summary_text": None, "message_count": len(messages)}

        logger.info(f"Generating summary for {len(messages)} messages")
        summary_text = self.summarize_messages(messages)
        if not summary_text:
            summary_text = "No additional context available for summary."
        return {"summary_text": summary_text, "message_count": len(messages)}

    def retriever_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Intent-aware hybrid retrieval node - performs hybrid search with dynamic alpha.

        Behavior per intent:
        - "search": Full hybrid search (vector + BM25 fusion via RRF)
        - "comparison": Full hybrid search (alpha optimized for differences)
        - "attribute_filter": Lexical-heavy hybrid (alpha=0.25 for exact attribute matching)
        - "refinement": Hybrid search constrained to prior search results with new attribute filter
        - "follow_up": Full hybrid search (refined from previous context)
        - "summary": Skipped (no retrieval needed)

        All searches use Reciprocal Rank Fusion (RRF) with dynamic alpha weighting.
        No LLM involvement - deterministic retrieval based on query_evaluator output.
        """
        start_time = time.time()
        messages = state["messages"]
        alpha = state.get("alpha", 0.25)
        intent = state.get("intent", "search")
        intent_optimized = state.get("intent_optimized", False)

        # Save prior search context before overwriting
        prior_search_documents = state.get("retrieved_documents", [])
        prior_search_intent = state.get("intent", None)

        # Early exit for summary intent - no retrieval needed
        if intent == "summary":
            logger.debug("Retriever: skipping hybrid search (intent=summary)")
            return {
                "retrieved_documents": [],
                "prior_search_documents": prior_search_documents,
                "prior_search_intent": prior_search_intent,
            }

        # Log retrieval strategy
        if intent_optimized:
            logger.info(f"Retriever: using FAST PATH alpha={alpha:.2f} (intent={intent})")
        else:
            logger.info(f"Retriever: using LLM-determined alpha={alpha:.2f} (intent={intent})")

        # Extract original user query from messages
        query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                query = _flatten_llm_content(msg)
                break

        # Expand vague follow-up queries using conversation context
        if query:
            query = self._expand_vague_query(query, messages)

        if not query:
            logger.warning("Retriever: no user query found in messages")
            return {
                "retrieved_documents": [],
                "prior_search_documents": prior_search_documents,
                "prior_search_intent": prior_search_intent,
            }

        logger.info(f"Retriever: query='{query[:50]}...', alpha={alpha:.2f}")

        # Extract attributes for attribute_filter and refinement intents
        attribute_filters = None
        if intent in ("attribute_filter", "refinement"):
            attribute_filters = self._extract_attributes(query)
            if attribute_filters:
                logger.info(f"Retriever: applying {len(attribute_filters)} attribute filter(s)")

        # For refinement intents, constrain results to prior search documents
        if intent == "refinement" and prior_search_documents:
            prior_product_ids = [
                doc.metadata.get("product_id")
                for doc in prior_search_documents
                if doc.metadata.get("product_id")
            ]
            if prior_product_ids:
                # Add product_id filter to constrain refinement to prior results
                product_id_filter = {"terms": {"product_id": prior_product_ids}}
                if attribute_filters is None:
                    attribute_filters = []
                attribute_filters.append(product_id_filter)
                logger.info(
                    f"Retriever (refinement): constraining to {len(prior_product_ids)} prior search product(s)"
                )

        # Emit embedding progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(
                    SearchProgressEvent(stage="embedding", message="Embedding query...")
                )
            except Exception as e:
                logger.debug(f"Could not emit embedding progress event: {e}")

        # Capture sinks for the actual DSL bodies sent to OpenSearch. Each
        # parallel search gets its own dict so the threadpool workers don't
        # race when filling them in. The bodies are emitted to the
        # observability panel below once the searches return.
        hybrid_capture: Dict[str, Any] = {}
        bm25_capture: Dict[str, Any] = {}

        # Create retriever with dynamic alpha, attribute filters, and per-message
        # optimization toggles (sent by the frontend via the chat WebSocket).
        retriever = self.vector_store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": RERANKER_FETCH_K if ENABLE_RERANKING else RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": alpha,
                "filters": attribute_filters,
                "optimizations": state.get("optimizations") or {},
                "capture_body": hybrid_capture,
            },
        )

        # Emit search progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(
                    SearchProgressEvent(stage="vector_search", message="Searching vector index...")
                )
            except Exception as e:
                logger.debug(f"Could not emit vector search progress event: {e}")

        # Get results — run hybrid retrieval and the BM25 baseline in parallel.
        # The BM25 baseline powers the Pipeline Quality Summary card; opensearch-py
        # is a synchronous HTTP client that releases the GIL during I/O so two
        # worker threads cut the wall-clock cost of the second query in half.
        bm25_query_opts = dict(state.get("optimizations") or {})
        bm25_query_opts["hybrid"] = False  # force BM25 for the baseline

        def _hybrid_call() -> Tuple[List[Document], float]:
            """Run hybrid (vector + BM25) retrieval; returns docs and wall-clock ms."""
            t0 = time.time()
            docs = retriever.invoke(query)
            return docs, (time.time() - t0) * 1000.0

        def _bm25_call() -> Tuple[List[Document], float]:
            """Run BM25-only retrieval with optimization toggles; returns docs and ms."""
            t0 = time.time()
            docs = self.vector_store.bm25_only_search(
                query,
                k=RETRIEVER_FETCH_K,
                filters=attribute_filters,
                optimizations=bm25_query_opts,
                capture_body=bm25_capture,
            )
            return docs, (time.time() - t0) * 1000.0

        def _stock_bm25_call() -> Tuple[List[Document], float]:
            """Run vanilla BM25 (no optimization toggles) as a fixed baseline for the Pipeline Quality Summary."""
            # Ignores all optimization toggles so the card can show what
            # fuzzy/synonyms/phonetic actually buy over plain BM25.
            t0 = time.time()
            docs = self.vector_store.stock_bm25_search(
                query,
                k=RETRIEVER_FETCH_K,
                filters=attribute_filters,
            )
            return docs, (time.time() - t0) * 1000.0

        retrieve_start = time.time()
        with ThreadPoolExecutor(max_workers=3) as pool:
            hybrid_future = pool.submit(_hybrid_call)
            bm25_future = pool.submit(_bm25_call)
            stock_future = pool.submit(_stock_bm25_call)
            results, retriever_latency_ms = hybrid_future.result()
            bm25_results, bm25_latency_ms = bm25_future.result()
            stock_bm25_results, stock_bm25_latency_ms = stock_future.result()
        retrieve_elapsed = time.time() - retrieve_start

        logger.info(
            f"Retriever: hybrid={len(results)} docs ({retriever_latency_ms:.0f}ms), "
            f"bm25={len(bm25_results)} docs ({bm25_latency_ms:.0f}ms), "
            f"stock_bm25={len(stock_bm25_results)} docs ({stock_bm25_latency_ms:.0f}ms), "
            f"wall={retrieve_elapsed:.3f}s"
        )

        # Filter relaxation: if attribute filters returned very few results, drop
        # multi_match (material_or_feature / size) filters and retry the hybrid
        # query. Color and brand filters use `match` and are kept — the user
        # explicitly asked for those. Multi_match filters are style/material hints
        # that can over-constrain (e.g. "athletic" in "red shoes athletic").
        MIN_ATTR_FILTER_RESULTS = 3
        if (
            attribute_filters
            and len(results) < MIN_ATTR_FILTER_RESULTS
            and intent in ("attribute_filter", "refinement")
        ):
            hard_filters = [f for f in attribute_filters if "multi_match" not in f]
            if len(hard_filters) < len(attribute_filters):
                logger.info(
                    "Retriever: filter relaxation — %d doc(s) with full filters, "
                    "retrying without material/size constraints (%d → %d filter(s))",
                    len(results),
                    len(attribute_filters),
                    len(hard_filters),
                )
                relaxed_retriever = self.vector_store.as_retriever(
                    search_type="hybrid",
                    search_kwargs={
                        "k": RERANKER_FETCH_K if ENABLE_RERANKING else RETRIEVER_K,
                        "fetch_k": RETRIEVER_FETCH_K,
                        "alpha": alpha,
                        "filters": hard_filters or None,
                        "optimizations": state.get("optimizations") or {},
                        "capture_body": hybrid_capture,
                    },
                )
                relaxed_results = relaxed_retriever.invoke(query)
                if len(relaxed_results) > len(results):
                    results = relaxed_results
                    attribute_filters = hard_filters or None
                    logger.info(
                        "Retriever: relaxation succeeded — %d doc(s) returned",
                        len(results),
                    )

        # Emit OpenSearch query events with the actual DSL bodies. The hybrid
        # event flips to `quality_gate_retry` on the second pass so the UI
        # can surface the retry separately. The BM25 baseline is identical
        # across passes (alpha doesn't affect it), so we only emit it once
        # per request — on the first pass.
        if OpenSearchQueryEvent:
            filter_summary = self._format_filter_summary(attribute_filters)
            is_retry = bool(state.get("quality_gate_retried", False))
            try:
                hybrid_event = OpenSearchQueryEvent(
                    query=query,
                    alpha=alpha,
                    filters=attribute_filters,
                    filter_summary=filter_summary,
                    intent=intent,
                    optimizations=state.get("optimizations") or None,
                    query_type="quality_gate_retry" if is_retry else "hybrid",
                    body=hybrid_capture.get("body"),
                    index=hybrid_capture.get("index"),
                    params=hybrid_capture.get("params"),
                )
                self._emit_event_from_sync(hybrid_event)
            except Exception as e:
                logger.error(f"Could not emit hybrid OpenSearch query event: {e}", exc_info=True)

            if not is_retry:
                try:
                    bm25_event = OpenSearchQueryEvent(
                        query=query,
                        alpha=0.0,  # BM25 baseline is pure lexical
                        filters=attribute_filters,
                        filter_summary=filter_summary,
                        intent=intent,
                        optimizations=state.get("optimizations") or None,
                        query_type="bm25_baseline",
                        body=bm25_capture.get("body"),
                        index=bm25_capture.get("index"),
                        params=bm25_capture.get("params"),
                    )
                    self._emit_event_from_sync(bm25_event)
                except Exception as e:
                    logger.error(
                        f"Could not emit BM25 baseline OpenSearch query event: {e}",
                        exc_info=True,
                    )

        # Best-effort lookup of ESCI ground-truth judgments. Missing index or
        # missing query is silently treated as "no ground truth" — the UI
        # falls back to the confidence proxy in that case.
        judgments = self.vector_store.lookup_judgments(query)
        if judgments:
            logger.info(f"Retriever: ground truth available ({len(judgments)} judged products)")
        else:
            logger.debug("Retriever: no ground truth for query")

        # Emit text search progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(
                    SearchProgressEvent(stage="text_search", message="Full-text search complete")
                )
            except Exception as e:
                logger.debug(f"Could not emit text search progress event: {e}")

        # Emit fusion progress
        if SearchProgressEvent:
            try:
                self._emit_event_from_sync(
                    SearchProgressEvent(
                        stage="fusion",
                        message="Fusing results with Reciprocal Rank Fusion...",
                    )
                )
            except Exception as e:
                logger.debug(f"Could not emit fusion progress event: {e}")

        # Emit hybrid search result event
        if HybridSearchResultEvent and results:
            try:
                search_event = HybridSearchResultEvent(
                    candidate_count=len(results),
                    candidates=[
                        SearchCandidate(
                            source=doc.metadata.get("source", "unknown"),
                            snippet=(
                                doc.page_content[:200] + "..."
                                if len(doc.page_content) > 200
                                else doc.page_content
                            ),
                            url=doc.metadata.get("url"),
                        )
                        for doc in results[:10]
                    ],
                )
                self._emit_event_from_sync(search_event)
            except Exception as e:
                logger.debug(f"Could not emit hybrid search result event: {e}")

        elapsed = time.time() - start_time

        # Intent-specific result logging
        result_summary = f"Retrieved {len(results)} documents in {elapsed:.3f}s"
        if intent == "comparison":
            logger.info(
                f"Retriever (comparison): {result_summary} - highlighting product differences"
            )
        elif intent == "attribute_filter":
            logger.info(
                f"Retriever (attribute_filter): {result_summary} - prioritizing attribute matches"
            )
        elif intent == "refinement":
            logger.info(
                f"Retriever (refinement): {result_summary} - filtered to prior search with new constraint"
            )
        elif intent == "follow_up":
            logger.info(f"Retriever (follow_up): {result_summary} - refining previous results")
        else:  # search
            logger.info(f"Retriever (search): {result_summary}")

        return {
            "retrieved_documents": results,
            "pre_rerank_documents": list(results),
            "bm25_documents": bm25_results,
            "stock_bm25_documents": stock_bm25_results,
            "judgments": judgments,
            "bm25_latency_ms": bm25_latency_ms,
            "stock_bm25_latency_ms": stock_bm25_latency_ms,
            "retriever_latency_ms": retriever_latency_ms,
            "prior_search_documents": prior_search_documents,
            "prior_search_intent": prior_search_intent,
            "user_query": query,
            "intent": intent,  # Pass intent downstream for reranker/agent
        }

    def reranker_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Intent-aware reranker node - scores and reorders documents by relevance.

        Behavior per intent:
        - "comparison": Reranks by quality/feature differences (highlights tradeoffs)
        - "attribute_filter": Reranks by attribute match accuracy (exact matches prioritized)
        - "search": Standard relevance reranking
        - "follow_up": Reranks by relevance to refine previous results

        Returns reranked documents + reranker_max_score for quality gate.
        """
        retrieved_documents = state.get("retrieved_documents", [])
        intent = state.get("intent", "search")
        # Per-message toggle from the frontend; falls back to the global env flag.
        reranking_opt = state.get("optimizations", {}).get("reranking", True)

        if (
            not ENABLE_RERANKING
            or not reranking_opt
            or not self.reranker
            or not retrieved_documents
        ):
            logger.debug(
                f"Reranker: skipped (toggle={reranking_opt}, intent={intent}, "
                f"docs={len(retrieved_documents)})"
            )
            # When reranking is intentionally off we mark the quality gate as
            # already retried so it doesn't loop trying to "rescue" a missing
            # score. Documents pass through in their retriever-determined order.
            return {
                "retrieved_documents": retrieved_documents,
                "reranker_max_score": 1.0 if not reranking_opt else 0.0,
                "reranker_latency_ms": 0.0,
                "quality_gate_retried": (
                    True if not reranking_opt else state.get("quality_gate_retried", False)
                ),
                "intent": intent,
            }

        # Extract query for reranking
        query = state.get("user_query", "")
        if not query:
            messages = state["messages"]
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    query = _flatten_llm_content(msg)
                    break

        # Emit reranker start event
        if RerankerStartEvent:
            try:
                self._emit_event_from_sync(
                    RerankerStartEvent(
                        model=RERANKER_MODEL,
                        candidate_count=len(retrieved_documents),
                    )
                )
            except Exception as e:
                logger.debug(f"Could not emit reranker start event: {e}")

        # Store original ranks
        original_sources = [doc.metadata.get("source", "unknown") for doc in retrieved_documents]
        for i, doc in enumerate(retrieved_documents, 1):
            doc.metadata["original_rank"] = i

        # Calculate total content size for throughput metrics
        total_content_chars = sum(len(doc.page_content) for doc in retrieved_documents)
        batch_size = self.reranker.batch_size

        rerank_start = time.time()
        logger.info(
            f"Reranker: processing {len(retrieved_documents)} candidates, batch_size={batch_size}, device={self.reranker.device}"
        )

        # Emit initial progress
        if RerankerProgressEvent:
            try:
                self._emit_event_from_sync(
                    RerankerProgressEvent(
                        stage="scoring",
                        progress=0.0,
                        message=f"Scoring {len(retrieved_documents)} documents...",
                    )
                )
            except Exception as e:
                logger.debug(f"Could not emit reranker progress event: {e}")

        # Score every retrieved candidate so the observability panel can show
        # the full cross-encoder ranking (not just the top-K cut sent to the
        # agent). The agent still gets only the top-K to keep its context
        # focused; everything below is exposed via ``all_reranked_documents``.
        all_scored = self.reranker.score_documents(query, retrieved_documents)
        reranked_results = all_scored[:RERANKER_TOP_K]
        rerank_elapsed = time.time() - rerank_start

        # Emit completion progress
        if RerankerProgressEvent:
            try:
                self._emit_event_from_sync(
                    RerankerProgressEvent(
                        stage="ranking",
                        progress=1.0,
                        message=f"Ranking complete - {len(retrieved_documents)} documents scored",
                    )
                )
            except Exception as e:
                logger.debug(f"Could not emit reranker completion event: {e}")

        # Extract documents with scores
        results_with_scores = [(doc, score) for doc, score in reranked_results]
        results = [doc for doc, score in results_with_scores]

        # Store reranker scores in metadata
        for i, (doc, score) in enumerate(results_with_scores, 1):
            doc.metadata["reranker_score"] = score

        # Calculate throughput metrics
        docs_per_sec = len(results) / rerank_elapsed if rerank_elapsed > 0 else 0
        chars_per_sec = total_content_chars / rerank_elapsed if rerank_elapsed > 0 else 0
        ms_per_doc = (rerank_elapsed * 1000) / len(results) if results else 0

        # Log reranking results with detailed timing
        avg_score = (
            sum(score for _, score in results_with_scores) / len(results_with_scores)
            if results_with_scores
            else 0
        )
        max_score = max((score for _, score in results_with_scores), default=0.0)

        # Intent-specific result logging
        result_summary = f"Complete in {rerank_elapsed:.3f}s, top {len(results)} selected, avg_score={avg_score:.4f}, max_score={max_score:.4f}"
        if intent == "comparison":
            logger.info(
                f"Reranker (comparison): {result_summary} - prioritizing feature/quality differences"
            )
        elif intent == "attribute_filter":
            logger.info(
                f"Reranker (attribute_filter): {result_summary} - prioritizing attribute accuracy"
            )
        elif intent == "refinement":
            logger.info(
                f"Reranker (refinement): {result_summary} - from prior search with new constraint"
            )
        elif intent == "follow_up":
            logger.info(f"Reranker (follow_up): {result_summary} - refining previous results")
        else:  # search
            logger.info(f"Reranker (search): {result_summary}")

        logger.debug(
            f"Reranker throughput: {docs_per_sec:.1f} docs/s, {chars_per_sec:.0f} chars/s, {ms_per_doc:.1f} ms/doc"
        )

        # Log individual scores at debug level
        for i, (doc, score) in enumerate(results_with_scores, 1):
            source = doc.metadata.get("source", "unknown")
            logger.debug(f"  {i}. score={score:.4f} [{source}]")

        # Log order changes
        reranked_sources = [doc.metadata.get("source", "unknown") for doc in results]
        if original_sources[: len(reranked_sources)] != reranked_sources:
            logger.debug("Reranker: order changed (reranking improved relevance)")
        else:
            logger.debug("Reranker: order unchanged (already optimally ranked)")

        # Stash reranker scores on every scored doc so the UI can render the
        # full ranking. The top-K subset shares Document instances with the
        # agent's ``retrieved_documents`` so scores set above carry over.
        for doc, score in all_scored:
            doc.metadata["reranker_score"] = score
        all_reranked_results = [doc for doc, _ in all_scored]

        return {
            "retrieved_documents": results,
            "all_reranked_documents": all_reranked_results,
            "reranker_max_score": max_score,
            "reranker_latency_ms": rerank_elapsed * 1000.0,
            "intent": intent,  # Pass intent to quality gate
        }

    def quality_gate_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """
        Adaptive quality gate — checks reranker scores and triggers retry if results are low-quality.

        Prevents passing poor-quality search results to the agent. If the highest reranker score
        is below the intent-specific threshold, adjusts alpha in the opposite direction and retries
        the retriever once to try a different search strategy.

        Decision Logic:
        - **PASS**: `reranker_max_score >= threshold` → continue to agent with current results
        - **RETRY**: `reranker_max_score < threshold` AND not yet retried → adjust alpha, loop back to retriever
        - **ACCEPT**: already retried once → continue to agent regardless of score (accept best-effort results)

        Intent-Specific Thresholds:
        - `comparison`: 0.55 (highest — comparison needs quality feature analysis)
        - `attribute_filter`: 0.45 (attribute matches can be fuzzy)
        - `refinement`: 0.45 (feature keyword matching is specific)
        - `search`, `follow_up`: 0.50 (standard quality bar)

        Alpha Adjustment (retry strategy):
        - If current alpha >= 0.5: lower by 0.3 (shift to more lexical matching)
        - If current alpha < 0.5: raise by 0.3 (shift to more semantic matching)

        Args:
            state: CustomAgentState with:
                - reranker_max_score: float, highest relevance score from reranker (0.0–1.0)
                - alpha: float, current search weight
                - quality_gate_retried: bool, whether already retried once
                - intent: str, for threshold selection
                - retrieved_documents: list, documents to evaluate

        Returns:
            Dict with keys:
            - quality_gate_status: str, "pass" | "retry" (only when retrying)
            - quality_gate_retried: bool, True if retry triggered
            - quality_gate_reason: str, explanation of decision
            - alpha: float, NEW alpha if retrying, otherwise omitted
            - reranker_max_score: float, the score that was evaluated

        Examples:
            Scenario 1 (PASS):
            Input: max_score=0.72, threshold=0.50, intent="search"
            Output: {
                "quality_gate_status": "pass",
                "quality_gate_reason": "PASS: max_score 0.72 >= threshold 0.50",
                "quality_gate_retried": False
            }
            → Continues to agent_node

            Scenario 2 (RETRY):
            Input: max_score=0.35, threshold=0.50, intent="search", alpha=0.65 (semantic-heavy)
            Output: {
                "quality_gate_status": "retry",
                "quality_gate_reason": "RETRY (search): score 0.35 < 0.50, alpha → 0.35",
                "quality_gate_retried": True,
                "alpha": 0.35  # Shift to more lexical search
            }
            → Loops back to retriever_node with adjusted alpha

            Scenario 3 (ACCEPT — already retried):
            Input: quality_gate_retried=True (from prior attempt)
            Output: {
                "quality_gate_reason": "Accepted after retry (max_score=0.42)",
                "quality_gate_retried": False  # No further retries
            }
            → Continues to agent_node with current best results
        """
        from config import ENABLE_QUALITY_GATE, QUALITY_GATE_THRESHOLD

        current_alpha = state.get("alpha", DEFAULT_ALPHA)
        max_score = state.get("reranker_max_score", 0.0)
        intent = state.get("intent", "search")

        # Intent-aware thresholds
        intent_thresholds = {
            "comparison": 0.55,  # Higher threshold for quality comparisons
            "attribute_filter": 0.45,  # Standard threshold
            "refinement": 0.45,  # Same as attribute_filter — feature keyword matching is specific
            "search": 0.50,  # Standard threshold
            "follow_up": 0.50,  # Standard threshold
        }
        quality_threshold = intent_thresholds.get(intent, QUALITY_GATE_THRESHOLD)

        # Early return if quality gate disabled
        if not ENABLE_QUALITY_GATE:
            return {
                "quality_gate_retried": False,
                "quality_gate_reason": "Quality gate disabled in config",
                "quality_gate_threshold_used": quality_threshold,
                "reranker_max_score": max_score,
            }

        # Already retried once - accept results
        if state.get("quality_gate_retried", False):
            logger.info(
                f"QualityGate: already retried, accepting results (max_score={max_score:.3f})"
            )
            return {
                "quality_gate_reason": f"Accepted after retry (max_score={max_score:.3f})",
                "quality_gate_threshold_used": quality_threshold,
                "reranker_max_score": max_score,
            }

        # No documents to evaluate
        if not state.get("retrieved_documents", []):
            return {
                "quality_gate_retried": False,
                "quality_gate_reason": "No documents to evaluate",
                "quality_gate_threshold_used": quality_threshold,
                "reranker_max_score": max_score,
            }

        # Score above threshold - good results, continue
        if max_score >= quality_threshold:
            logger.info(
                f"QualityGate ({intent}): PASS - score {max_score:.3f} above threshold {quality_threshold:.2f}"
            )
            return {
                "quality_gate_retried": False,
                "quality_gate_reason": f"PASS: max_score {max_score:.3f} >= threshold {quality_threshold:.2f}",
                "quality_gate_status": "pass",
                "quality_gate_threshold_used": quality_threshold,
                "reranker_max_score": max_score,
            }

        # Score below threshold - adjust alpha and retry
        if current_alpha >= 0.5:
            new_alpha = max(0.0, current_alpha - 0.3)
            direction = "lexical"
        else:
            new_alpha = min(1.0, current_alpha + 0.3)
            direction = "semantic"

        logger.info(
            f"QualityGate ({intent}): RETRY - score {max_score:.3f} below threshold {quality_threshold:.2f}, alpha {current_alpha:.2f} → {new_alpha:.2f} ({direction}-boost)"
        )

        return {
            "alpha": new_alpha,
            "quality_gate_retried": True,
            "quality_gate_reason": f"RETRY ({intent}): score {max_score:.3f} < {quality_threshold:.2f}, alpha → {new_alpha:.2f}",
            "quality_gate_status": "retry",
            "quality_gate_threshold_used": quality_threshold,
            "reranker_max_score": max_score,
        }

    def _route_after_intent(self, state: CustomAgentState) -> str:
        """Route based on detected intent for e-commerce product search.

        Returns the route key from intent_routes mapping, not the node name.
        Intent routes mapping:
        - "clarify" → agent node (direct clarification response)
        - "summary" → summary node (skip retrieval)
        - "search", "comparison", "attribute_filter", "follow_up" → query_evaluator node (standard Q&A pipeline)
        """
        intent = state.get("intent", "search")

        # Route based on intent
        if intent == "clarify":
            return "clarify"  # Maps to "agent" node
        if intent == "summary":
            return "summary"  # Maps to "summary" node

        # All product search intents go through standard pipeline
        # (search, comparison, attribute_filter, follow_up)
        return "other"  # Maps to "query_evaluator" node

    def _route_after_query_evaluator(self, state: CustomAgentState) -> str:
        """Route after query evaluator to retriever.

        Query evaluator only runs for intents that need search (question, follow_up, task).
        Summary intents skip query_evaluator entirely (routed directly to summary node).
        Clarify intents skip both query_evaluator and go straight to agent.
        Config/doc requests skip query_evaluator entirely.
        """
        return "retriever"

    def _route_after_summary(self, state: CustomAgentState) -> str:
        """Route after summary node.

        If intent was summary, go directly to agent (skip retrieval).
        Otherwise continue to retriever.
        """
        intent = state.get("intent", "question")
        if intent == "summary":
            return "done"
        return "continue"

    def _quality_gate_route(self, state: CustomAgentState) -> str:
        """Route after quality gate: retry retrieval or continue to agent."""
        # If quality_gate_retried just became True AND the current alpha was just changed,
        # we need to retry. Check if retried flag was set AND we haven't been through
        # the quality gate a second time yet.
        reason = state.get("quality_gate_reason", "")
        if "Retry triggered" in reason and state.get("quality_gate_retried", False):
            # Only retry if this is the first time (reason contains "Retry triggered")
            # After retry, quality_gate will set a different reason
            return "retry"
        return "continue"

    def create_agent_graph(self):
        """Create custom StateGraph with automatic retrieval pipeline.

        Flow: intent_classifier → query_evaluator → retriever → reranker → quality_gate → agent → END

        The quality_gate can route back to retriever for a single retry with adjusted alpha.
        """
        logger.info("Creating agent graph with automatic retrieval")

        # Build the graph
        workflow = StateGraph(CustomAgentState)

        # Add core nodes
        workflow.add_node("intent_classifier", self.intent_classifier_node)
        workflow.add_node("query_evaluator", self.query_evaluator_node)
        workflow.add_node("summary", self.summary_node)
        workflow.add_node("retriever", self.retriever_node)
        workflow.add_node("reranker", self.reranker_node)
        workflow.add_node("quality_gate", self.quality_gate_node)
        workflow.add_node("agent", self.agent_node)
        workflow.add_node("llm_judge", self.llm_judge_node)

        # Set entry point
        workflow.set_entry_point("intent_classifier")

        # Intent classifier routing
        intent_routes = {
            "summary": "summary",
            "clarify": "agent",
            "other": "query_evaluator",
        }
        workflow.add_conditional_edges(
            "intent_classifier",
            self._route_after_intent,
            intent_routes,
        )

        # Core pipeline edges
        workflow.add_edge("query_evaluator", "retriever")
        workflow.add_conditional_edges(
            "summary",
            self._route_after_summary,
            {"done": "agent", "continue": "retriever"},
        )
        workflow.add_edge("retriever", "reranker")
        workflow.add_edge("reranker", "quality_gate")

        # Quality gate routing: retry retrieval or continue to agent
        workflow.add_conditional_edges(
            "quality_gate",
            self._quality_gate_route,
            {"retry": "retriever", "continue": "agent"},
        )

        # Agent is the final step
        workflow.add_edge("agent", "llm_judge")
        workflow.add_edge("llm_judge", END)

        # Compile with checkpointer
        self.app = workflow.compile(checkpointer=self.checkpointer)

        logger.info(
            "Agent graph created: intent_classifier → query_evaluator → retriever → reranker → quality_gate → agent → llm_judge"
        )

    def generate_thread_id(self):
        """Generate a unique thread ID for conversation persistence"""
        self.thread_id = f"conversation_{uuid.uuid4().hex[:8]}"

    def set_thread_id(self, thread_id: str):
        """Set a specific thread ID to resume a conversation"""
        self.thread_id = thread_id

    def _ensure_metadata_table(self):
        """Ensure the conversation_metadata table exists.

        Creates the conversation_metadata table if it doesn't already exist.
        This table stores conversation titles and timestamps for the conversation list.

        Raises:
            Does not raise exceptions - logs warnings if table creation fails.
        """
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversation_metadata (
                            thread_id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Could not create conversation_metadata table: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating conversation_metadata table: {e}")

    def list_conversations(self):
        """List available previous conversations from PostgreSQL with titles"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Query the metadata table for conversations with titles
                    cur.execute("""
                        SELECT thread_id, title, created_at
                        FROM conversation_metadata
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                    conversations = cur.fetchall()
                    return conversations
        except Exception as e:
            print(f"Error listing conversations: {e}")
            return []

    def clear_all_conversations(self):
        """Clear all previous conversations from the database"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    # Delete all conversation metadata
                    cur.execute("DELETE FROM conversation_metadata")
                    metadata_count = cur.rowcount

                    # Delete all checkpoints (conversation history)
                    cur.execute("DELETE FROM checkpoints")
                    checkpoint_count = cur.rowcount

                    # Delete checkpoint blobs if they exist
                    try:
                        cur.execute("DELETE FROM checkpoint_blobs")
                    except psycopg.Error:
                        pass  # Table may not exist, which is acceptable

                    return metadata_count, checkpoint_count
        except Exception as e:
            print(f"Error clearing conversations: {e}")
            return 0, 0

    def generate_conversation_title(self, messages: List[BaseMessage]) -> str:
        """Use the LLM to generate a concise title for the conversation.

        Analyzes the conversation messages and generates a descriptive title
        that captures the main topic being discussed.

        Args:
            messages: List of conversation messages to analyze.

        Returns:
            A concise title (max 50 characters). Returns a default title if
            generation fails or no suitable messages are found.

        Raises:
            Does not raise exceptions - returns fallback titles on error.
        """
        try:
            # Build a summary of the conversation for title generation
            conversation_summary = []
            for msg in messages[-6:]:  # Use last 6 messages for context
                if hasattr(msg, "content") and msg.content:
                    # Safely get message type
                    role = "User" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                    content = str(msg.content)[:200]  # Truncate long messages
                    conversation_summary.append(f"{role}: {content}")

            if not conversation_summary:
                return "New Conversation"

            prompt = f"""Generate a very short title (max 50 chars) for this conversation.
The title should capture the main topic or question being discussed.
Return ONLY the title, nothing else.

Conversation:
{chr(10).join(conversation_summary)}

Title:"""

            response = self.llm.invoke(prompt)
            title = _flatten_llm_content(response).strip().strip("\"'")[:50]
            return title if title else "Untitled Conversation"
        except Exception as e:
            logger.debug(f"Title generation failed, using fallback: {e}")
            # Fallback: use first user message
            for msg in messages:
                if (
                    hasattr(msg, "type")
                    and msg.type == "human"
                    and hasattr(msg, "content")
                    and msg.content
                ):
                    return str(msg.content)[:50].strip()
            return "Untitled Conversation"

    def update_conversation_title(self):
        """Generate and save a title for the current conversation based on its content.

        Retrieves the current conversation messages from the checkpoint, generates
        a descriptive title using the LLM, and stores it in the conversation_metadata table.

        This method is called after each agent response to keep the title up-to-date
        with the conversation content.

        Raises:
            Does not raise exceptions - logs warnings if title update fails.
        """
        try:
            # Get current conversation messages from checkpoint
            checkpoint = self.checkpointer.get({"configurable": {"thread_id": self.thread_id}})
            if not checkpoint:
                logger.debug("No checkpoint found for title update")
                return

            # Access messages from channel_values (checkpoint is a dict)
            channel_values = checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                logger.debug("No messages in checkpoint for title update")
                return

            # Generate title from conversation
            title = self.generate_conversation_title(messages)

            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Insert or update conversation metadata with new title
                    cur.execute(
                        """
                        INSERT INTO conversation_metadata (thread_id, title)
                        VALUES (%s, %s)
                        ON CONFLICT (thread_id)
                        DO UPDATE SET title = EXCLUDED.title, updated_at = CURRENT_TIMESTAMP
                    """,
                        (self.thread_id, title),
                    )
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Database error updating conversation title: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating conversation title: {e}")

    def estimate_token_count(self, messages: Sequence[BaseMessage]) -> int:
        """
        Estimate token count for a list of messages.
        Uses 1 token ≈ 4 characters heuristic (conservative for English).

        Args:
            messages: Sequence of BaseMessage objects to estimate token count for.

        Returns:
            Estimated token count based on character length.
        """
        try:
            total_chars = 0
            for msg in messages:
                if hasattr(msg, "content") and msg.content:
                    total_chars += len(str(msg.content))
            return total_chars // TOKEN_CHAR_RATIO
        except Exception:
            return 0

    def _fallback_summarize(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Create a simple fallback summary when LLM summarization fails.
        Uses basic heuristics to extract key information without LLM.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A simple summary of the conversation.
        """
        if not messages_to_summarize:
            return "No earlier context"

        # Extract user questions and assistant topics
        user_topics = []
        assistant_topics = []

        for msg in messages_to_summarize:
            if hasattr(msg, "content") and msg.content:
                content_preview = str(msg.content)[:100].strip()
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)
                else:
                    if "human" in str(type(msg)).lower():
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)

        # Build simple summary
        summary_parts = [f"Earlier conversation ({len(messages_to_summarize)} messages):"]

        if user_topics:
            summary_parts.append(f"User asked about: {', '.join(user_topics[:3])}")
            if len(user_topics) > 3:
                summary_parts.append(f"(and {len(user_topics) - 3} more topics)")

        if assistant_topics:
            summary_parts.append(f"Assistant discussed: {', '.join(assistant_topics[:3])}")
            if len(assistant_topics) > 3:
                summary_parts.append(f"(and {len(assistant_topics) - 3} more topics)")

        return ". ".join(summary_parts)

    def summarize_messages(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Use LLM to create a concise summary of older messages.
        Preserves key facts and context while being brief.
        Falls back to simple summaries if LLM fails.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A concise summary of the message content.
        """
        if not messages_to_summarize:
            return "No earlier context"

        try:
            # Build context of messages to summarize
            context = ""
            for msg in messages_to_summarize:
                if hasattr(msg, "content") and msg.content:
                    # Determine role from message type
                    if hasattr(msg, "type"):
                        role = "User" if msg.type == "human" else "Assistant"
                    else:
                        role = "Assistant" if "assistant" in str(type(msg)).lower() else "User"
                    context += f"{role}: {msg.content}\n\n"

            if not context.strip():
                return "No earlier context"

            # Prompt LLM to summarize
            summary_prompt = f"""Summarize the following conversation concisely in 1-2 paragraphs, preserving key facts and context.
Focus on what the user asked, what the assistant already provided, and whether any next steps remain.
Mention any uncertainties or missing pieces so the user knows what's incomplete.

Conversation:
{context}

Summary:"""

            # Invoke LLM for summary (direct, not through agent). Gemini may
            # return content as a list of content blocks; flatten so the
            # SummaryEvent's `summary_text: str` field accepts it.
            response = self.llm.invoke(summary_prompt)
            return _flatten_llm_content(response)

        except httpx.ConnectError as e:
            logger.error(
                f"Connection error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to simple concatenation summary")
            return self._fallback_summarize(messages_to_summarize)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"JSON/parsing error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to word count summary")
            return self._fallback_summarize(messages_to_summarize)

        except TimeoutError as e:
            logger.error(
                f"Timeout while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to first/last message summary")
            # Get first and last messages
            first_msg = ""
            last_msg = ""
            if messages_to_summarize:
                if hasattr(messages_to_summarize[0], "content"):
                    first_msg = str(messages_to_summarize[0].content)[:80]
                if hasattr(messages_to_summarize[-1], "content"):
                    last_msg = str(messages_to_summarize[-1].content)[:80]
            summary = f"Earlier conversation ({len(messages_to_summarize)} messages): "
            if first_msg:
                summary += f"Started with: {first_msg}. "
            if last_msg:
                summary += f"Ended with: {last_msg}"
            return summary

        except Exception as e:
            logger.error(
                f"Unexpected error while summarizing {len(messages_to_summarize)} messages: {type(e).__name__}: {e}",
                exc_info=True,
            )
            logger.info("Falling back to basic summary")
            return self._fallback_summarize(messages_to_summarize)

    def compact_conversation_if_needed(
        self, messages: Sequence[BaseMessage]
    ) -> Tuple[Sequence[BaseMessage], bool, int]:
        """
        Check if conversation needs compaction and compact if necessary.

        Args:
            messages: Sequence of messages to check for compaction.

        Returns:
            Tuple of (compacted_messages, was_compacted, num_compacted) where:
            - compacted_messages: The potentially compacted message sequence
            - was_compacted: Boolean indicating if compaction occurred
            - num_compacted: Number of messages that were compacted
        """
        if not ENABLE_COMPACTION or not messages:
            return messages, False, 0

        if len(messages) < MIN_MESSAGES_FOR_COMPACTION:
            return messages, False, 0

        # Estimate token count
        token_count = self.estimate_token_count(messages)
        threshold = int(MAX_CONTEXT_TOKENS * COMPACTION_THRESHOLD_PCT)

        if token_count < threshold:
            return messages, False, 0  # No compaction needed

        # Perform compaction
        messages_to_keep = messages[-MESSAGES_TO_KEEP_FULL:]
        messages_to_compact = messages[:-MESSAGES_TO_KEEP_FULL]

        # Generate summary
        summary_text = self.summarize_messages(messages_to_compact)

        # Create summary message
        summary_msg = SystemMessage(content=f"[Earlier conversation summary]: {summary_text}")

        # Return compacted messages
        compacted = [summary_msg] + messages_to_keep
        num_compacted = len(messages_to_compact)

        # Log compaction completion with token counts
        compacted_token_count = self.estimate_token_count(compacted)
        logger.info(
            f"Compacted {num_compacted} messages "
            f"(token count: {compacted_token_count}/{MAX_CONTEXT_TOKENS})"
        )

        return compacted, True, num_compacted

    def run_conversation(self):
        """Run the interactive conversation loop"""
        print("=" * 70)
        print("E-Commerce Search Agent - Product Knowledge Base & Memory")
        print("=" * 70)
        print()
        print("Agent is ready! You can search for:")
        print("  - Products by brand or type")
        print("  - Products by color or attributes")
        print("  - Product comparisons and details")
        print()
        print("Commands:")
        print("  - Type your question and press Enter")
        print("  - Type 'new' to start a new conversation")
        print("  - Type 'list' to see previous conversations")
        print("  - Type 'load <id>' to resume a conversation")
        print("  - Type 'clear' to delete all conversations")
        print("  - Type 'quit' or 'exit' to stop")
        print()
        print("=" * 70)
        print()

        self.generate_thread_id()
        print(f"Conversation ID: {self.thread_id}")
        print("(Title will be updated after each message)")
        print()

        while True:
            try:
                # Get user input
                user_input = input("You: ").strip()

                if not user_input:
                    continue

                # Handle special commands
                if user_input.lower() == "quit" or user_input.lower() == "exit":
                    print("\nGoodbye!")
                    break

                if user_input.lower() == "new":
                    self.generate_thread_id()
                    print(f"\n✓ New conversation started")
                    print(f"Conversation ID: {self.thread_id}")
                    print()
                    continue

                if user_input.lower() == "list":
                    print("\n📋 Previous Conversations:")
                    conversations = self.list_conversations()
                    if conversations:
                        for i, (thread_id, title, created_at) in enumerate(conversations, 1):
                            # Format the date nicely
                            date_str = (
                                created_at.strftime("%Y-%m-%d %H:%M") if created_at else "Unknown"
                            )
                            print(f"  {i}. {title}")
                            print(f"     ID: {thread_id} | {date_str}")
                        print("\nUse 'load <id>' to resume a conversation")
                    else:
                        print("  No previous conversations found")
                    print()
                    continue

                if user_input.lower().startswith("load "):
                    thread_id = user_input[5:].strip()
                    if thread_id:
                        self.set_thread_id(thread_id)
                        print(f"\n✓ Loaded conversation: {thread_id}")
                        print()
                    else:
                        print("\n✗ Please provide a conversation ID: load <id>")
                        print()
                    continue

                if user_input.lower() == "clear":
                    # Confirm before clearing
                    confirm = (
                        input(
                            "\n⚠️  This will delete ALL conversations and history. Continue? (yes/no): "
                        )
                        .strip()
                        .lower()
                    )
                    if confirm == "yes":
                        metadata_count, checkpoint_count = self.clear_all_conversations()
                        print(
                            f"\n✓ Cleared {metadata_count} conversation(s) and {checkpoint_count} checkpoint record(s)"
                        )
                    else:
                        print("✗ Clear cancelled")
                    print()
                    continue

                # Process the input through the agent
                print()
                self._invoke_agent(user_input)
                print()

            except KeyboardInterrupt:
                print("\n\nInterrupted. Goodbye!")
                break
            except Exception as e:
                print(f"\n✗ Error: {e}")
                print("Try again or type 'quit' to exit\n")

    def _invoke_agent(self, user_input: str):
        """
        Invoke the agent with user input and stream intermediate reasoning steps.

        This method uses modern LangGraph streaming to show:
        1. Agent reasoning and decision-making steps
        2. Tool calls to the knowledge base with intermediate results
        3. Final response streamed character-by-character for real-time feedback

        Args:
            user_input: The user's question or command
        """
        try:
            # Prepare input for the agent with new state schema
            input_data = {
                "messages": [],
                "alpha": SEARCH_DEFAULTS.get(VECTOR_COLLECTION_NAME, {}).get(
                    "alpha", DEFAULT_ALPHA
                ),  # Collection-aware default
                "query_analysis": "",
                "intent": "question",
                "summary_text": None,
            }

            # Try to apply compaction to conversation if needed
            compacted_messages: List[BaseMessage] = []
            current_messages: Sequence[BaseMessage] = []
            try:
                checkpoint_state = self.checkpointer.get(
                    {"configurable": {"thread_id": self.thread_id}}
                )
                if checkpoint_state and "messages" in checkpoint_state:
                    current_messages = checkpoint_state["messages"]
                    compacted_msgs, was_compacted, num_compacted = (
                        self.compact_conversation_if_needed(current_messages)
                    )
                    compacted_messages = list(compacted_msgs)
                    if was_compacted:
                        print(f"[🗜️  Compacted {num_compacted} older messages to maintain context]")
            except Exception:
                # If compaction fails, just continue without it
                compacted_messages = []

            if not compacted_messages:
                compacted_messages = list(current_messages) if current_messages else []

            # Include compaction summary + history before the new user message
            history_messages = compacted_messages + [HumanMessage(content=user_input)]
            input_data["messages"] = history_messages

            final_response = ""

            # Get the current message count before invoking
            try:
                checkpoint_before = self.checkpointer.get(
                    {"configurable": {"thread_id": self.thread_id}}
                )
                messages_before_count = (
                    len(checkpoint_before.get("messages", [])) if checkpoint_before else 0
                )
            except Exception:
                messages_before_count = 0

            # Invoke the agent to get the complete response
            result = self.app.invoke(
                input_data,
                config={"configurable": {"thread_id": self.thread_id}},
            )

            # Log query analysis for debugging (optional)
            if "query_analysis" in result and result["query_analysis"]:
                print(f"[Debug] Query Analysis: {result['query_analysis']}")
            if "alpha" in result:
                print(f"[Debug] Lambda used: {result.get('alpha', 'N/A'):.2f}")

            # Extract final response and reasoning from result
            if "messages" in result:
                messages = result["messages"]
                # Only look at messages added in this turn (after the user message)
                # We need to find the assistant message that came after the last user input
                new_messages = (
                    messages[messages_before_count:]
                    if messages_before_count < len(messages)
                    else []
                )

                # Find the last assistant message in the new messages (final response)
                for msg in reversed(new_messages):
                    if hasattr(msg, "content") and msg.content:
                        content = str(msg.content)
                        # Skip messages that are tool calls
                        if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                            final_response = content
                            break

            # Display the final response with streaming
            if final_response:
                print("Agent (response):")
                self._stream_text(final_response)
            else:
                print("Agent: Processing complete")

            # Update conversation title after each turn
            self.update_conversation_title()

        except httpx.ConnectError as e:
            print(f"✗ Cannot connect to Google AI API")
            print(f"  Error: {e}")
            print(f"\n  To fix:")
            print(f"  1. Check that GOOGLE_API_KEY is set correctly")
            print(f"  2. Verify internet connectivity")
        except Exception as e:
            print(f"✗ Error invoking agent: {e}")
            import traceback

            traceback.print_exc()

    def _stream_text(self, text: str, chunk_size: int = 1) -> None:
        """
        Display text output from LLM response without artificial delays.

        Previously used character-by-character delays for simulated streaming.
        Now displays text immediately as it's received from true LLM streaming.

        Args:
            text: The text to display to the console.
            chunk_size: Not used in current implementation (kept for compatibility).
        """
        # Display text immediately without artificial delays
        # True streaming happens via _stream_llm_response and LLM chunk events
        print(text)
        print()  # Final newline

    def run(self):
        """Main entry point for the agent"""
        try:
            self.verify_prerequisites()
            self.initialize_components()
            self.create_agent_graph()
            self.run_conversation()
        except KeyboardInterrupt:
            print("\n\nShutdown requested.")
        except Exception as e:
            print(f"\n✗ Fatal error: {e}")
            sys.exit(1)
        finally:
            self.cleanup()

    async def ensure_async_pool_open(self):
        """Ensure the async pool is open and checkpointer is created. Call this before using astream_events."""
        if self.async_pool:
            try:
                # Open the pool if not already open
                # The pool's open() method is idempotent, so calling it twice is safe
                await self.async_pool.open()
            except Exception as e:
                logger.warning(f"Error opening async pool: {e}")

        # Create checkpointer if not already created (must be done in async context)
        if self.checkpointer is None:
            from config import CHECKPOINT_SELECTIVE_SERIALIZATION

            if CHECKPOINT_SELECTIVE_SERIALIZATION:
                from checkpoint_optimizer import SelectiveJsonPlusSerializer

                self.checkpointer = AsyncPostgresSaver(
                    self.async_pool, serde=SelectiveJsonPlusSerializer()
                )
            else:
                self.checkpointer = AsyncPostgresSaver(self.async_pool)

            # Recompile the graph with the new checkpointer
            if self.app is not None:
                self._recompile_with_checkpointer()

    def _recompile_with_checkpointer(self):
        """Recompile the agent graph with the async checkpointer.

        This rebuilds the LangGraph workflow and compiles it with the checkpointer
        that was created asynchronously. Must be called after self.checkpointer is set.
        """
        # Reuse create_agent_graph which already handles all node/edge setup
        # and compiles with self.checkpointer
        self.create_agent_graph()
        logger.info("Graph recompiled with async checkpointer")

    async def close_async_pool(self):
        """Close the async pool."""
        if self.async_pool:
            await self.async_pool.close()

    def cleanup(self):
        """Clean up resources"""
        # Clear reranker from memory if loaded
        if self.reranker:
            del self.reranker

        if self.pool:
            self.pool.close()

        # Note: async_pool should be closed via close_async_pool() in async context


def main():
    """Main function"""
    agent = EcommerceSearchAgent()
    agent.run()


if __name__ == "__main__":
    main()
