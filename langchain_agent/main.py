"""EcommerceSearchAgent: a LangGraph RAG pipeline for Amazon ESCI product search.

Six-intent classifier, hybrid BM25 + kNN retrieval, cross-encoder reranking behind a
quality gate, an LLM judge, and Postgres-checkpointed conversation memory. All models run
locally through Ollama except the cross-encoder, which runs in-process.
"""

import logging
import warnings
from typing import Optional

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.graph import END, StateGraph
from langgraph.utils.runnable import RunnableCallable
from psycopg_pool import AsyncConnectionPool

from core.agent_state import CustomAgentState
from core.llm import build_chat_model
from pipeline.conversation_management import ConversationManagementMixin
from pipeline.pipeline_nodes import AlphaEstimation, IntentClassification, PipelineNodesMixin
from quality.enrichment_value_judge import EnrichmentValueJudge
from quality.judge import LLMJudge
from retrieval.embeddings import build_embeddings
from retrieval.reranker import CrossEncoderReranker
from retrieval.vector_store import OpenSearchVectorStore

logger = logging.getLogger(__name__)


# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)


from core.config import (
    CROSS_ENCODER_MODEL,
    DATABASE_URL,
    DB_CONNECTION_KWARGS,
    DB_POOL_MAX_SIZE,
    EMBEDDINGS_MODEL,
    LLM_MODEL,
    LLM_TEMPERATURE,
    QUERY_EVAL_MAX_TOKENS,
    QUERY_EVAL_MODEL,
    QUERY_EVAL_TEMPERATURE,
    VECTOR_COLLECTION_NAME,
)


class EcommerceSearchAgent(PipelineNodesMixin, ConversationManagementMixin):
    """Orchestrator: builds the components and the graph; the node bodies live in the mixins.

    intent_classifier -> summary | agent (clarify) | query_evaluator -> retriever -> reranker
    -> quality_gate (one retry to retriever) -> agent -> llm_judge. Node methods take a
    CustomAgentState and return a partial update; read state with `state.get(key, default)`.
    """

    def __init__(self):
        self.llm = None
        self.embeddings = None
        self.vector_store = None
        self.async_pool = None
        self.checkpointer = None
        self.app = None
        # Set per request by ObservableAgentService so sync nodes can emit events.
        self.emit_callback = None
        self.event_loop = None
        self.reranker = None
        self.alpha_estimator_llm = None

    def initialize_components(self):
        print("Initializing components...")
        print()

        print(f"Loading LLM: {LLM_MODEL}")
        self.llm = build_chat_model(LLM_MODEL, temperature=LLM_TEMPERATURE, max_tokens=8192)
        print("✓ LLM initialized")

        print(f"Loading query evaluator (alpha estimator): {QUERY_EVAL_MODEL}")
        self.alpha_estimator_llm = build_chat_model(
            QUERY_EVAL_MODEL,
            temperature=QUERY_EVAL_TEMPERATURE,
            max_tokens=QUERY_EVAL_MAX_TOKENS,
        )
        self.alpha_structured = self.alpha_estimator_llm.with_structured_output(AlphaEstimation)
        self.intent_structured = self.alpha_estimator_llm.with_structured_output(
            IntentClassification
        )
        print("✓ Query evaluator model initialized")

        print(f"Loading embeddings: {EMBEDDINGS_MODEL}")
        self.embeddings = build_embeddings()
        print("✓ Embeddings initialized")

        print("Connecting to Postgres checkpoint store...")
        # Async pool for the checkpointer; astream_events requires it. Opened later, in the loop.
        self.async_pool = AsyncConnectionPool(
            conninfo=DATABASE_URL,
            max_size=DB_POOL_MAX_SIZE,
            kwargs=DB_CONNECTION_KWARGS.copy(),
            open=False,
        )
        print("✓ Postgres connection pool initialized")

        print(f"Loading OpenSearch vector store: {VECTOR_COLLECTION_NAME}")
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        print("✓ Vector store initialized")

        print(f"Loading cross-encoder reranker: {CROSS_ENCODER_MODEL}")
        self.reranker = CrossEncoderReranker(model_name=CROSS_ENCODER_MODEL)
        print("✓ Reranker initialized")

        # Judges are built on first use.
        self.judge: Optional[LLMJudge] = None
        self.enrichment_value_judge: Optional[EnrichmentValueJudge] = None

        # AsyncPostgresSaver needs a running event loop, so ensure_async_pool_open creates it.
        self.checkpointer = None
        print("✓ Postgres checkpoint store will be initialized on first use (async)")

        print()

    def _route_after_intent(self, state: CustomAgentState) -> str:
        """Route key for intent_routes: clarify goes straight to agent, summary skips retrieval,
        every product-search intent goes through query_evaluator."""
        intent = state.get("intent", "search")
        if intent in ("clarify", "summary"):
            return intent
        return "other"

    def _quality_gate_route(self, state: CustomAgentState) -> str:
        """Route after quality gate: retry retrieval or continue to agent."""
        # quality_gate_node sets quality_gate_status explicitly for this decision; routing
        # on its reason text instead once never matched and silently disabled the retry.
        return "retry" if state.get("quality_gate_status") == "retry" else "continue"

    def create_agent_graph(self):
        """Build and compile the StateGraph (with the checkpointer, if one exists yet)."""
        workflow = StateGraph(CustomAgentState)

        workflow.add_node("intent_classifier", self.intent_classifier_node)
        workflow.add_node("query_evaluator", self.query_evaluator_node)
        workflow.add_node("summary", self.summary_node)
        workflow.add_node("retriever", self.retriever_node)
        workflow.add_node("reranker", self.reranker_node)
        workflow.add_node("quality_gate", self.quality_gate_node)
        # Registered with both faces on purpose: astream_events must get the async one, or the
        # sync body runs on the event loop thread and a taxonomy re-tag blocks every WebSocket
        # frame. name="agent" is load-bearing: observable_agent branches on the traced node name.
        workflow.add_node(
            "agent",
            RunnableCallable(self.agent_node, self.aagent_node, name="agent"),
        )
        workflow.add_node("llm_judge", self.llm_judge_node)

        workflow.set_entry_point("intent_classifier")
        workflow.add_conditional_edges(
            "intent_classifier",
            self._route_after_intent,
            {"summary": "summary", "clarify": "agent", "other": "query_evaluator"},
        )
        workflow.add_edge("query_evaluator", "retriever")
        workflow.add_edge("summary", "agent")
        workflow.add_edge("retriever", "reranker")
        workflow.add_edge("reranker", "quality_gate")

        workflow.add_conditional_edges(
            "quality_gate",
            self._quality_gate_route,
            {"retry": "retriever", "continue": "agent"},
        )

        workflow.add_edge("agent", "llm_judge")
        workflow.add_edge("llm_judge", END)

        self.app = workflow.compile(checkpointer=self.checkpointer)

    async def ensure_async_pool_open(self):
        """Open the async pool and create the checkpointer (needs a running loop), then
        recompile the graph with it. Call before astream_events."""
        if self.async_pool:
            try:
                await self.async_pool.open()  # idempotent
            except Exception as e:
                logger.warning(f"Error opening async pool: {e}")

        if self.checkpointer is None:
            self.checkpointer = AsyncPostgresSaver(self.async_pool)
            if self.app is not None:
                self.create_agent_graph()

    async def close_async_pool(self):
        """Close the async pool."""
        if self.async_pool:
            await self.async_pool.close()

    def cleanup(self):
        """Release the reranker model; the async pool is closed via close_async_pool()."""
        if self.reranker:
            del self.reranker
