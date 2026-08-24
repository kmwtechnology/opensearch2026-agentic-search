"""
Agent state types for LangGraph custom agent.

Contains TypedDict definitions for the simplified agent state schema.

IMPORTANT: State fields may not be initialized. Always use state.get(key, default)
to access optional fields safely. Only 'messages' is guaranteed to exist.
"""

from typing import Annotated, Dict, List, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class CustomAgentState(TypedDict, total=False):
    """
    State schema for LangGraph agent with dynamic alpha weighting.

    Uses a custom TypedDict instead of MessagesState to enable independent
    control of vector/full-text search weighting (alpha) based on query intent.
    This allows the Query Evaluator to set optimal α (0.0–1.0) per query type:
    - 0.0 (pure lexical): exact product IDs, model numbers, UPCs
    - 0.25 (lexical-heavy): brand + category, specific attributes
    - 0.5 (balanced): feature combinations, activity-based queries
    - 0.75 (semantic-heavy): conceptual needs, occasion-based
    - 1.0 (pure semantic): gift ideas, mood/style, open-ended

    ## Pipeline Flow

        intent_classifier → query_evaluator → retriever → reranker → quality_gate → agent

    Each node reads certain fields and writes others. For example:
    - intent_classifier: reads messages, writes intent, intent_confidence, user_query
    - query_evaluator: reads user_query, writes alpha, query_analysis
    - retriever: reads alpha, user_query, writes retrieved_documents
    - reranker: reads retrieved_documents, user_query, writes reranker_max_score
    - quality_gate: reads reranker_max_score, optionally retries with adjusted alpha

    ## Field Lifetime

    **Required** (always exist after first node):
    - `messages`: Conversation history (BaseMessage list)

    **Optional** (may not exist until set by respective node):
    - Intent Classifier sets: intent, intent_confidence, user_query, reasoning
    - Query Evaluator sets: alpha, query_analysis
    - Retriever sets: retrieved_documents
    - Reranker sets: reranker_max_score
    - Quality Gate sets: quality_gate_retried, quality_gate_reason

    ## Safe Access Pattern

    IMPORTANT: Since `total=False`, optional fields are not guaranteed to exist at runtime.
    Always use `state.get(key, default)` instead of direct indexing:

        # ✓ CORRECT — safe default fallback
        alpha = state.get("alpha", 0.25)
        intent = state.get("intent", "question")
        retried = state.get("quality_gate_retried", False)

        # ✗ WRONG — raises KeyError if field not yet set
        alpha = state["alpha"]  # KeyError before query_evaluator runs
        retried = state["quality_gate_retried"]  # KeyError before quality_gate runs

    Exception: `messages` is guaranteed to exist from the start, but you can still
    use `.get("messages", [])` for defensive programming.

    ## Example: Implementing a Custom Node

        def my_custom_node(state: CustomAgentState) -> Dict[str, Any]:
            # Safe field access
            user_query = state.get("user_query", "")
            alpha = state.get("alpha", 0.5)
            prior_docs = state.get("retrieved_documents", [])

            # Process without KeyError risk
            if alpha > 0.6:
                # Favor semantic search
                ...
            else:
                # Favor lexical search
                ...

            # Return updates (only modified fields)
            return {"custom_field": value}
    """

    # Core message state (required - managed by add_messages reducer)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Intent classification state
    # Defaults: intent="question", intent_confidence=1.0
    intent: str
    intent_confidence: float  # 0.0-1.0, triggers clarify if < 0.7
    reasoning: str  # Explanation for classification
    user_query: str  # Extracted user query
    clarifying_questions: List[str]  # Questions to ask if confidence is low

    # Query evaluation state - alpha controls hybrid search balance
    # Defaults: alpha=0.25 (DEFAULT_ALPHA), query_analysis=""
    alpha: float
    query_analysis: str
    summary_text: Optional[str]

    # Retrieved documents from automatic retrieval
    # Default: empty list
    retrieved_documents: List[Document]

    # Prior search context for refinement intents
    # Tracks documents and intent from the previous search turn
    # Used to constrain refinement queries to prior results
    prior_search_documents: List[Document]
    prior_search_intent: Optional[str]

    # Reranker output
    reranker_max_score: float  # Max reranker score (0.0-1.0), set by reranker_node

    # Quality gate state (replaces alpha_refiner)
    # Defaults: quality_gate_retried=False
    quality_gate_retried: bool
    quality_gate_reason: Optional[str]

    # Per-message search optimization toggles (frontend-controlled).
    # Recognized keys: hybrid, fuzzy, synonyms, phonetic, phrase_boost,
    # field_boost, typeahead, reranking, llm. Missing keys default to True.
    optimizations: Dict[str, bool]

    # ------------------------------------------------------------------
    # Pipeline Quality Summary inputs (set by retriever_node / reranker_node)
    # ------------------------------------------------------------------
    # Pre-rerank hybrid result list (top fetch_k) — preserved before the
    # reranker overwrites retrieved_documents. Used to compute hybrid-stage
    # NDCG@10/MRR/Recall@20/Precision@10 in the summary card.
    pre_rerank_documents: List[Document]
    # Full reranker-scored list (all candidates from the retriever, sorted
    # descending by reranker score) — preserved before the top-K cut so the
    # observability panel can show every candidate the cross-encoder
    # evaluated, not just the top-K passed to the agent.
    all_reranked_documents: List[Document]
    # Pure BM25 baseline ranking (top fetch_k). Same query, same filters,
    # but no vector search — used as the apples-to-apples baseline.
    bm25_documents: List[Document]
    # Stock/vanilla BM25 reference. Ignores all optimization toggles —
    # standard analyzer, title + chunk_text only. Always present, gives
    # the Pipeline Quality Summary card a fixed anchor for measuring the
    # value of fuzzy/synonyms/phonetic/etc.
    stock_bm25_documents: List[Document]
    # ESCI ground-truth judgments for the user's query, looked up from
    # the esci_judgments index. None when the query is novel; the UI
    # falls back to the confidence proxy in that case.
    judgments: Optional[Dict[str, float]]
    # Per-stage wall-clock latency in milliseconds.
    bm25_latency_ms: float
    stock_bm25_latency_ms: float
    retriever_latency_ms: float
    reranker_latency_ms: float
    # LLM-as-judge output (set by llm_judge_node when both ``llm:on`` and
    # ``llm_judge:on`` toggles are active). Stored as a plain dict so it
    # survives LangGraph checkpoint serialization without importing the
    # judge module here.
    judgment: Optional[Dict[str, object]]
    judge_latency_ms: float
    # Auto-correction (Layer 3a). Populated when the judge flagged
    # hallucinations and the agent regenerated a clean response.
    original_judgment: Optional[Dict[str, object]]
    corrected_response: Optional[str]
    hallucination_retry_used: bool
