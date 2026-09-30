"""The LangGraph state schema shared by every pipeline node."""

from typing import Annotated, Dict, List, Optional, Sequence

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages
from typing_extensions import TypedDict


class CustomAgentState(TypedDict, total=False):
    """Graph state. `total=False`: only `messages` is guaranteed, so read every other
    field with `state.get(key, default)`, never `state[key]`. A field a node returns must
    be declared here."""

    # Core message state (required - managed by add_messages reducer)
    messages: Annotated[Sequence[BaseMessage], add_messages]

    # Intent classification state
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

    # The previous search turn's documents; refinement queries are constrained to them.
    prior_search_documents: List[Document]

    # Reranker output
    reranker_max_score: float  # Max reranker score (0.0-1.0), set by reranker_node

    # Quality gate state
    # Defaults: quality_gate_retried=False
    quality_gate_retried: bool
    quality_gate_reason: Optional[str]
    # Structured status used by main.py's _quality_gate_route to decide
    # whether to loop back to the retriever: "pass" | "retry". Every
    # quality_gate_node return branch must set this explicitly -- an unset
    # value lets a prior pass's "retry" leak forward through state.
    quality_gate_status: Optional[str]

    # ------------------------------------------------------------------
    # Pipeline Summary inputs (set by retriever_node / reranker_node)
    # ------------------------------------------------------------------
    # Pre-rerank hybrid result list (top fetch_k) — preserved before the
    # reranker overwrites retrieved_documents. Used to count rank changes for
    # the summary card's confidence proxy.
    pre_rerank_documents: List[Document]
    # Full reranker-scored list (all candidates from the retriever, sorted
    # descending by reranker score) — preserved before the top-K cut so the
    # observability panel can show every candidate the cross-encoder
    # evaluated, not just the top-K passed to the agent.
    all_reranked_documents: List[Document]
    # Per-stage wall-clock latency in milliseconds.
    retriever_latency_ms: float
    reranker_latency_ms: float

    # LLM-as-judge output (set by llm_judge_node). Stored as a plain dict so it
    # survives LangGraph checkpoint serialization without importing the
    # judge module here.
    judgment: Optional[Dict[str, object]]
    # Auto-correction. Populated when the judge flagged
    # hallucinations and the agent regenerated a clean response.
    original_judgment: Optional[Dict[str, object]]
    corrected_response: Optional[str]
    hallucination_retry_used: bool

    # Citations returned by agent_node alongside messages; every return path includes
    # the key (empty list if none).
    citations: List[Dict[str, str]]

    # True when agent_node already streamed its tokens to the client through
    # the sync emit bridge. observable_agent reads this to avoid re-sending the
    # finished text at node end, which would render the answer twice (#103).
    # MUST be declared here: LangGraph filters node output down to the declared
    # state channels, so an undeclared key never reaches astream_events.
    response_streamed: bool

    # Agentic enrichment flywheel (set by agent_node when the
    # trigger_enrichment tool fires on a detected search-quality gap).
    # Defaults: enrichment_triggered=False
    enrichment_triggered: bool
