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

import logging
import os
import sys
import uuid
import warnings
from typing import Optional

import psycopg
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.utils.runnable import RunnableCallable
from psycopg_pool import AsyncConnectionPool, ConnectionPool

# Import extracted modules
from core.agent_state import CustomAgentState
from pipeline.conversation_management import ConversationManagementMixin
from pipeline.pipeline_nodes import AlphaEstimation, IntentClassification, PipelineNodesMixin
from quality.enrichment_value_judge import EnrichmentValueJudge
from quality.judge import LLMJudge
from retrieval.doc_replacer import DocumentReplacer
from retrieval.link_verifier import LinkVerifier
from retrieval.reranker import CrossEncoderReranker, GeminiReranker
from retrieval.vector_store import OpenSearchVectorStore

# Setup logging
logger = logging.getLogger(__name__)


# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)


# ============================================================================
# LANGSMITH TRACING (Optional - enable with LANGSMITH_API_KEY env var)
# ============================================================================

if os.getenv("LANGSMITH_API_KEY"):
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_PROJECT"] = os.getenv("LANGSMITH_PROJECT", "agentic-hybrid-search")


from core.config import (
    CROSS_ENCODER_MODEL,
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    EMBEDDINGS_MODEL,
    ENABLE_QUERY_EVALUATION,
    ENABLE_RERANKING,
    GOOGLE_API_KEY,
    LLM_MODEL,
    LLM_TEMPERATURE,
    QUERY_EVAL_MAX_TOKENS,
    QUERY_EVAL_MODEL,
    QUERY_EVAL_TEMPERATURE,
    RERANKER_FETCH_K,
    RERANKER_MODEL,
    RERANKER_TYPE,
    RETRIEVER_ALPHA,
    RETRIEVER_FETCH_K,
    RETRIEVER_K,
    VECTOR_COLLECTION_NAME,
    VECTOR_DIMENSION,
)


class EcommerceSearchAgent(PipelineNodesMixin, ConversationManagementMixin):
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
        from core.config import LINK_CACHE_TTL_MINUTES, LINK_VERIFICATION_TIMEOUT_MS

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
            from core.config import OPENSEARCH_INDEX_NAME

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

        # Lazy second-opinion judge for trigger_enrichment — only constructed
        # when the agent's own tool-call decision first fires (most users
        # never trigger enrichment at all).
        self.enrichment_value_judge: Optional[EnrichmentValueJudge] = None

        # Checkpointer will be created asynchronously via create_async_checkpointer()
        # This is required because AsyncPostgresSaver needs a running event loop
        self.checkpointer = None
        print("✓ Postgres checkpoint store will be initialized on first use (async)")

        # Ensure conversation metadata table exists
        self._ensure_metadata_table()

        print()

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
        # quality_gate_node sets quality_gate_status explicitly for this
        # purpose ("retry" / "pass" — see its docstring). Route on that
        # directly rather than substring-matching quality_gate_reason: a
        # prior version of this check looked for "Retry triggered" in the
        # reason text, but quality_gate_node has only ever produced reasons
        # shaped like "RETRY (search): score 0.35 < 0.50, alpha -> 0.35" —
        # that substring never matched, so this route always fell through to
        # "continue" and the single-retry loop never actually executed, even
        # when quality_gate_node genuinely decided to retry. Confirmed live
        # 2026-09-14 investigating why Part 4 of DEMO.md never showed a
        # second Knowledge Search/Reranker pass after "Retry Triggered".
        return "retry" if state.get("quality_gate_status") == "retry" else "continue"

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
        # The agent node is registered with BOTH faces on purpose. cli.py drives
        # the graph synchronously via app.invoke() and needs the sync func; the
        # API path drives it via astream_events and must get the async one, or
        # LangGraph runs the sync body on the event loop thread and a taxonomy
        # re-index blocks every WebSocket frame for ~20s (#103). name="agent"
        # is load-bearing: observable_agent branches on the traced node name,
        # which a hand-built RunnableCallable does not inherit from the key.
        workflow.add_node(
            "agent",
            RunnableCallable(self.agent_node, self.aagent_node, name="agent"),
        )
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
            from core.config import CHECKPOINT_SELECTIVE_SERIALIZATION

            if CHECKPOINT_SELECTIVE_SERIALIZATION:
                from checkpoints.checkpoint_optimizer import SelectiveJsonPlusSerializer

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


if __name__ == "__main__":
    from cli import main

    main()
