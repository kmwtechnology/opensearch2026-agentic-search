"""
Pydantic models for WebSocket events.

These events are streamed in real-time as the agent executes,
providing full observability into every step and decision.
"""

from datetime import datetime, timezone
from typing import Annotated, Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ============================================================================
# TYPE ALIASES FOR BOUNDED SCORES
# ============================================================================

# Score bounded to [0.0, 1.0] - represents confidence/relevance
ConfidenceScore = Annotated[float, Field(ge=0.0, le=1.0, description="Score in range [0.0, 1.0]")]

# Alpha bounded to [0.0, 1.0] - represents lexical vs semantic weight
AlphaWeight = Annotated[
    float, Field(ge=0.0, le=1.0, description="Alpha weight: 0.0=lexical, 1.0=semantic")
]

# Progress bounded to [0.0, 1.0]
ProgressPercent = Annotated[
    float, Field(ge=0.0, le=1.0, description="Progress percentage [0.0, 1.0]")
]


# ============================================================================
# BASE EVENT
# ============================================================================


class BaseEvent(BaseModel):
    """Base class for all WebSocket events.

    Fields:
        type: Discriminator used by the frontend to deserialize the correct event subclass.
        timestamp: UTC emission time; frontend uses this for ordering within a turn.
        node: Graph node that produced the event. Frontend routes the event to the
              correct pipeline step card regardless of emission order (e.g., an
              OpenSearchQueryEvent with node="retriever" always lands in the retriever
              step even if emitted after a later node starts).
    """

    type: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    node: Optional[str] = None  # Current graph node name


# ============================================================================
# CONNECTION EVENTS
# ============================================================================


class ConnectionEstablished(BaseEvent):
    """Sent when WebSocket connection is established."""

    type: Literal["connection_established"] = "connection_established"
    thread_id: str
    existing_messages: int = 0


# ============================================================================
# NODE LIFECYCLE EVENTS
# ============================================================================


class NodeStartEvent(BaseEvent):
    """Emitted when a graph node starts execution."""

    type: Literal["node_start"] = "node_start"
    node: str
    input_summary: Optional[str] = None


class NodeEndEvent(BaseEvent):
    """Emitted when a graph node completes execution."""

    type: Literal["node_end"] = "node_end"
    node: str
    duration_ms: float
    output_summary: Optional[str] = None


# ============================================================================
# CONVERSATION CONTEXT EVENTS
# ============================================================================


class ConversationContextEvent(BaseEvent):
    """Emitted when conversation context is loaded from checkpoint."""

    type: Literal["conversation_context"] = "conversation_context"
    previous_message_count: int
    is_new_conversation: bool
    summary: Optional[str] = None  # e.g., "Loaded 6 previous messages"


# ============================================================================
# QUERY EVALUATOR EVENTS
# ============================================================================


class QueryEvaluationEvent(BaseEvent):
    """Emitted when query is evaluated for search strategy."""

    type: Literal["query_evaluation"] = "query_evaluation"
    node: Literal["query_evaluator"] = "query_evaluator"
    query: str
    alpha: AlphaWeight  # 0.0 (lexical) to 1.0 (semantic), validated at construction
    query_analysis: str  # LLM's reasoning
    search_strategy: Literal[
        "lexical-heavy", "balanced", "semantic-heavy"
    ]  # Validated set of strategies

    @field_validator("search_strategy", mode="after")
    @classmethod
    def validate_strategy_matches_alpha(cls, strategy: str, info) -> str:
        """Ensure search strategy is consistent with alpha value."""
        alpha = info.data.get("alpha", 0.5)
        # Lexical-heavy for alpha < 0.3, balanced for 0.3-0.7, semantic-heavy for > 0.7
        if alpha < 0.3 and strategy != "lexical-heavy":
            raise ValueError(f"alpha={alpha} suggests lexical-heavy search, not '{strategy}'")
        if 0.3 <= alpha < 0.7 and strategy != "balanced":
            raise ValueError(f"alpha={alpha} suggests balanced search, not '{strategy}'")
        if alpha >= 0.7 and strategy != "semantic-heavy":
            raise ValueError(f"alpha={alpha} suggests semantic-heavy search, not '{strategy}'")
        return strategy


class IntentClassificationEvent(BaseEvent):
    """Emitted when the intent classifier determines the user goal."""

    type: Literal["intent_classification"] = "intent_classification"
    node: Literal["intent_classifier"] = "intent_classifier"
    intent: str
    user_query: str
    reasoning: str
    confidence: Optional[ConfidenceScore] = None  # 0.0-1.0 confidence score, validated


class QueryExpansionEvent(BaseEvent):
    """Emitted when a vague query is expanded using conversation context."""

    type: Literal["query_expansion"] = "query_expansion"
    node: Literal["retriever"] = "retriever"
    original_query: str
    expanded_query: str
    expansion_reason: str


class OpenSearchQueryEvent(BaseEvent):
    """Emitted when OpenSearch query is prepared with filters/modifications."""

    type: Literal["opensearch_query"] = "opensearch_query"
    node: Literal["retriever"] = "retriever"
    query: str
    alpha: AlphaWeight  # 0.0=lexical, 1.0=semantic
    filters: Optional[List[Dict[str, Any]]] = None  # Applied attribute filters
    filter_summary: Optional[str] = (
        None  # Human-readable summary (e.g., "brand: Sony, color: blue")
    )
    intent: str  # intent that triggered the search
    # Per-feature optimization toggles applied to this search (frontend-controlled).
    # Echoed back so the observability panel can show what was actually used.
    optimizations: Optional[Dict[str, bool]] = None
    # Which kind of query this event represents. The retriever node emits one
    # `hybrid` and one `bm25_baseline` event per request, plus a
    # `quality_gate_retry` if the gate triggers a re-run.
    query_type: Literal["hybrid", "bm25_baseline", "quality_gate_retry"] = "hybrid"
    # Full DSL body sent to OpenSearch (with embedding vectors scrubbed to a
    # placeholder). Pure DSL — paste-able into OpenSearch's Dev Tools or any REST client.
    body: Optional[Dict[str, Any]] = None
    # Index the search ran against (e.g. ``agentic_hybrid_search_docs``).
    index: Optional[str] = None
    # Query-string params (e.g. ``{"search_pipeline": "hybrid_search_pipeline"}``).
    # Rendered above the body in the DSL viewer so users can reproduce the
    # exact request line.
    params: Optional[Dict[str, str]] = None


class QualityGateEvent(BaseEvent):
    """Emitted when quality gate evaluates reranker scores and decides whether to retry."""

    type: Literal["quality_gate"] = "quality_gate"
    node: Literal["quality_gate"] = "quality_gate"
    triggered: bool
    original_alpha: AlphaWeight  # Validated to [0.0, 1.0]
    new_alpha: Optional[AlphaWeight] = None  # Validated to [0.0, 1.0] if set
    max_score: ConfidenceScore  # Validated to [0.0, 1.0]
    threshold: ConfidenceScore  # Validated to [0.0, 1.0]
    reason: str


class SummaryEvent(BaseEvent):
    """Emitted when a summary is generated (or skipped) for conversational history."""

    type: Literal["summary_generated"] = "summary_generated"
    node: Literal["summary"] = "summary"
    summary_text: Optional[str]
    message_count: int


# ============================================================================
# HYBRID SEARCH EVENTS
# ============================================================================


class HybridSearchStartEvent(BaseEvent):
    """Emitted when hybrid search begins."""

    type: Literal["hybrid_search_start"] = "hybrid_search_start"
    node: Literal["retriever"] = "retriever"
    query: str
    alpha: AlphaWeight  # Validated to [0.0, 1.0]
    fetch_k: Annotated[int, Field(gt=0, description="Number of documents to fetch (must be > 0)")]


class SearchCandidate(BaseModel):
    """A single search candidate before reranking."""

    source: str
    snippet: str
    full_content: Optional[str] = None
    vector_score: Optional[float] = None
    text_score: Optional[float] = None
    rrf_score: Optional[float] = None
    url: Optional[str] = None


class HybridSearchResultEvent(BaseEvent):
    """Emitted when hybrid search completes with candidates."""

    type: Literal["hybrid_search_result"] = "hybrid_search_result"
    node: Literal["retriever"] = "retriever"
    candidate_count: int
    candidates: List[SearchCandidate]


# ============================================================================
# RERANKER EVENTS
# ============================================================================


class RerankerStartEvent(BaseEvent):
    """Emitted when reranking begins."""

    type: Literal["reranker_start"] = "reranker_start"
    node: Literal["reranker"] = "reranker"
    model: str
    candidate_count: int


class RerankedDocument(BaseModel):
    """A document after reranking with its new score and rank."""

    source: str
    score: ConfidenceScore  # Cross-encoder score (0.0-1.0), validated
    rank: Annotated[
        int, Field(gt=0, description="New rank after reranking (1-indexed, must be > 0)")
    ]
    original_rank: Annotated[
        int, Field(gt=0, description="Rank before reranking (1-indexed, must be > 0)")
    ]
    snippet: str
    rank_change: int = 0  # How much the rank changed (computed: rank - original_rank)
    url: Optional[str] = None

    @field_validator("rank_change", mode="after")
    @classmethod
    def validate_rank_change(cls, rank_change: int, info) -> int:
        """Ensure rank_change is consistent with rank and original_rank."""
        rank = info.data.get("rank")
        original_rank = info.data.get("original_rank")
        if rank is not None and original_rank is not None:
            expected = rank - original_rank
            if rank_change != expected:
                raise ValueError(f"rank_change={rank_change} but rank - original_rank = {expected}")
        return rank_change


class RerankerResultEvent(BaseEvent):
    """Emitted when reranking completes with scored documents."""

    type: Literal["reranker_result"] = "reranker_result"
    node: Literal["reranker"] = "reranker"
    results: List[RerankedDocument]
    reranking_changed_order: bool = False
    # The actually configured RERANKER_TYPE ("cross-encoder" or "gemini") —
    # lets the UI describe the real reranker instead of assuming one (#87).
    reranker_type: str = "cross-encoder"


# ============================================================================
# SEARCH PROGRESS EVENTS
# ============================================================================


class SearchProgressEvent(BaseEvent):
    """Emitted during search to show real-time progress."""

    type: Literal["search_progress"] = "search_progress"
    node: Literal["retriever"] = "retriever"
    stage: Literal[
        "attribute_extraction", "embedding", "vector_search", "text_search", "fusion"
    ] = "embedding"
    message: str  # e.g., "Embedding query...", "Searching vector index..."


class RerankerProgressEvent(BaseEvent):
    """Emitted during reranking to show real-time progress."""

    type: Literal["reranker_progress"] = "reranker_progress"
    node: Literal["reranker"] = "reranker"
    stage: Literal["scoring", "ranking"] = "scoring"
    progress: ProgressPercent = 0.0  # 0.0-1.0, validated
    message: str  # e.g., "Scoring document 20/40..."


# ============================================================================
# LLM RESPONSE EVENTS
# ============================================================================


class LLMReasoningStartEvent(BaseEvent):
    """Emitted when LLM starts generating reasoning."""

    type: Literal["llm_reasoning_start"] = "llm_reasoning_start"
    node: Literal["agent"] = "agent"


class LLMReasoningChunkEvent(BaseEvent):
    """Emitted for each chunk of LLM reasoning (streamed)."""

    type: Literal["llm_reasoning_chunk"] = "llm_reasoning_chunk"
    node: Literal["agent"] = "agent"
    content: str
    is_complete: bool = False


class LLMResponseStartEvent(BaseEvent):
    """Emitted when LLM starts generating response."""

    type: Literal["llm_response_start"] = "llm_response_start"
    node: Literal["agent"] = "agent"


class LLMResponseChunkEvent(BaseEvent):
    """Emitted for each chunk of LLM response (streamed)."""

    type: Literal["llm_response_chunk"] = "llm_response_chunk"
    node: Literal["agent"] = "agent"
    content: str
    is_complete: bool = False


class LLMResponseCorrectedEvent(BaseEvent):
    """Emitted when LLM judge auto-corrects the streamed response (fabrication/cross-product-bleed)."""

    type: Literal["llm_response_corrected"] = "llm_response_corrected"
    node: Literal["llm_judge"] = "llm_judge"
    corrected_content: str
    original_faithfulness: float
    corrected_faithfulness: float


class ToolCallEvent(BaseEvent):
    """Emitted when agent decides to call a tool."""

    type: Literal["tool_call"] = "tool_call"
    node: Literal["agent"] = "agent"
    tool_name: str
    tool_args: Dict[str, Any]


# ============================================================================
# COMPLETION EVENTS
# ============================================================================


class AgentCompleteEvent(BaseEvent):
    """Emitted when agent execution completes successfully."""

    type: Literal["agent_complete"] = "agent_complete"
    thread_id: str
    total_duration_ms: float
    final_response: str
    iterations: int = 0  # Number of retrieval iterations
    response_retries: int = 0  # Number of response retries
    documents_used: int = 0
    citations: Optional[List[Dict[str, str]]] = None
    title: Optional[str] = None  # Generated conversation title


class AgentErrorEvent(BaseEvent):
    """Emitted when agent execution fails."""

    type: Literal["agent_error"] = "agent_error"
    error: str
    node: Optional[str] = None
    recoverable: bool = False


# ============================================================================
# PIPELINE QUALITY SUMMARY (offline IR metrics + cost-benefit framing)
# ============================================================================


class StageMetrics(BaseModel):
    """Offline IR metrics for a single retrieval stage."""

    ndcg10: float
    mrr: float
    recall20: float
    precision10: float
    judged_count: int  # how many returned items had a ground-truth judgment


class LatencyStage(BaseModel):
    """One row of the per-stage latency / lift table."""

    stage: Literal["stock_bm25", "bm25", "hybrid", "reranked"]
    latency_ms: float
    ndcg: Optional[float] = None
    ndcg_lift_per_100ms: Optional[float] = None


class ConfidenceProxy(BaseModel):
    """Self-referential signal used when no ESCI ground truth exists."""

    top1_score: float
    score_gap: float
    score_variance: float
    rank_changes_count: int
    confidence_label: Literal["high", "medium", "low"]


HallucinationCategoryT = Literal["fabrication", "cross_product_bleed", "inference", "overreach"]


class FlaggedClaim(BaseModel):
    """One flagged claim from the LLM-as-judge, tiered by severity.

    Mirrors ``judge.FlaggedClaim``. ``fabrication`` and ``cross_product_bleed``
    are retry-worthy; ``inference`` and ``overreach`` are surface-only.
    """

    claim: str
    category: HallucinationCategoryT
    reasoning: str = ""


class GenerationJudgment(BaseModel):
    """LLM-as-judge result for the agent's synthesized response.

    Mirrors ``judge.JudgmentResult`` in shape. Polarity is normalized so
    ``verdict="llm_better"`` always means the synthesized response wins
    against the deterministic raw-list baseline.
    """

    verdict: Literal["llm_better", "tied", "llm_worse"]
    pairwise_justification: str
    faithfulness: float
    answer_relevance: float
    citation_accuracy: float
    context_utilization: float
    hallucinations: List[FlaggedClaim] = []


class PipelineSummaryEvent(BaseEvent):
    """End-of-pipeline retrieval-quality summary.

    Emits two layouts:

      * ``has_ground_truth=True``: ``bm25``/``hybrid``/``reranked`` are
        populated with offline IR metrics (NDCG@10, MRR, Recall@20,
        Precision@10) computed against ESCI judgments. The frontend
        renders the BM25→Hybrid→Reranked progression to make the value
        of each pipeline stage visible at a glance.
      * ``has_ground_truth=False``: ``confidence`` carries a self-
        referential proxy (top-1 reranker score, gap, variance, rank
        churn, label). The card calls out that the metrics are not
        offline-truth, so users don't conflate the two.

    ``latency`` is always populated; ``ndcg_lift_per_100ms`` is only
    filled for stages where ground truth was available.
    """

    type: Literal["pipeline_summary"] = "pipeline_summary"
    has_ground_truth: bool
    query: str
    optimizations: Dict[str, bool] = {}

    # Ground-truth layout. Up to four rows:
    #   * stock_bm25 — vanilla BM25 reference (always present, ignores toggles)
    #   * bm25      — BM25 with the user's optimization toggles applied
    #   * hybrid    — vector + BM25 (omitted when ``hybrid:false`` toggle)
    #   * reranked  — reranker output (omitted when ``reranking:false`` toggle)
    stock_bm25: Optional[StageMetrics] = None
    bm25: Optional[StageMetrics] = None
    hybrid: Optional[StageMetrics] = None
    reranked: Optional[StageMetrics] = None

    # Fallback layout
    confidence: Optional[ConfidenceProxy] = None

    # LLM-as-judge result (only when both ``optimizations.llm`` and
    # ``optimizations.llm_judge`` are on). Adds the "Generation" row to
    # the card with a pairwise verdict + 4 absolute scores + hallucinations.
    generation: Optional[GenerationJudgment] = None
    # When auto-correction (Layer 3a) fires, ``generation`` carries the
    # post-retry judgment and these fields carry the original (flagged)
    # judgment + corrected response text so the UI can show before/after.
    original_generation: Optional[GenerationJudgment] = None
    hallucination_retry_used: bool = False
    corrected_response: Optional[str] = None

    # Latency cost/benefit framing — always present
    latency: List[LatencyStage] = []


# ============================================================================
# METRICS EVENT
# ============================================================================


class MetricsEvent(BaseEvent):
    """Emitted with timing and performance metrics."""

    type: Literal["metrics"] = "metrics"
    query_evaluation_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    reranking_ms: Optional[float] = None
    document_grading_ms: Optional[float] = None
    llm_generation_ms: Optional[float] = None
    response_grading_ms: Optional[float] = None
    total_ms: float


# ============================================================================
# LINK VERIFICATION EVENTS
# ============================================================================


class LinkVerificationEvent(BaseEvent):
    """Emitted when citation links are verified."""

    type: Literal["link_verification"] = "link_verification"
    node: Literal["agent"] = "agent"
    total_links_checked: int
    valid_links: int
    broken_links: int
    broken_link_sources: List[str] = []  # Sources with broken links
    cache_hits: int = 0


class DocumentReplacementEvent(BaseEvent):
    """Emitted when documents with broken links are replaced."""

    type: Literal["document_replacement"] = "document_replacement"
    node: Literal["agent"] = "agent"
    replacements_made: int
    replacement_details: List[Dict[str, str]] = []  # {old_source, new_source, reason}
    documents_after_replacement: int


# ============================================================================
# AGENTIC ENRICHMENT FLYWHEEL EVENTS
# ============================================================================


class EnrichmentTriggeredEvent(BaseEvent):
    """Emitted when the agent's trigger_enrichment tool fires — a color or
    material taxonomy gap was detected and a real Lucille reindex was
    triggered live. Richer than the generic ToolCallEvent (which this
    doesn't fire, since the enrichment tool loop is a manual two-call
    binding inside agent_node, not a ToolNode-executed call the standard
    astream_events tool-start/tool-call machinery would see)."""

    type: Literal["enrichment_triggered"] = "enrichment_triggered"
    node: Literal["agent"] = "agent"
    attribute_type: str  # "color" or "material"
    variant: str  # the raw term the agent recognized, e.g. "chrome"
    canonical: Optional[str] = None  # the canonical bucket it resolved to, e.g. "metal"
    # Lifecycle phase (#103). This event is emitted MORE THAN ONCE per
    # enrichment: "started" immediately before the reindex is kicked off, then
    # exactly one terminal event ("complete" / "failed" / "declined"). Before
    # #103 only the terminal event existed, which meant the ~20s reindex window
    # was invisible to the UI and the value judge's rejection was silent.
    status: Literal["started", "complete", "failed", "declined"] = "complete"
    # Set when this replaced an EXISTING wrong mapping rather than adding a new
    # one — the difference between "learned tan → brown" and "corrected tan
    # from yellow to brown", which is the whole point of the correction demo.
    corrected_from: Optional[str] = None
    # Why a "failed" or "declined" event happened, in presentable prose.
    error: Optional[str] = None
    # "local" (blocking subprocess, real completion signal) or "github"
    # (fire-and-forget workflow dispatch — no completion signal ever arrives,
    # so a "started" event is followed by a terminal event carrying only the
    # run URL).
    reindex_mode: Optional[str] = None
    reindex_run_url: Optional[str] = None
    # Measured, real numbers from the completed reindex — None on every
    # non-"complete" status, and on a "complete" from a github-mode dispatch
    # which never learns them (#80).
    duration_seconds: Optional[float] = None
    docs_processed: Optional[int] = None


# ============================================================================
# UNION TYPE FOR ALL EVENTS
# ============================================================================

AgentEvent = (
    ConnectionEstablished
    | ConversationContextEvent
    | NodeStartEvent
    | NodeEndEvent
    | EnrichmentTriggeredEvent
    | QueryEvaluationEvent
    | IntentClassificationEvent
    | SummaryEvent
    | HybridSearchStartEvent
    | HybridSearchResultEvent
    | SearchProgressEvent
    | RerankerProgressEvent
    | RerankerStartEvent
    | RerankerResultEvent
    | QueryExpansionEvent
    | OpenSearchQueryEvent
    | QualityGateEvent
    | LLMReasoningStartEvent
    | LLMReasoningChunkEvent
    | LLMResponseStartEvent
    | LLMResponseChunkEvent
    | LLMResponseCorrectedEvent
    | ToolCallEvent
    | AgentCompleteEvent
    | AgentErrorEvent
    | PipelineSummaryEvent
    | MetricsEvent
    | LinkVerificationEvent
    | DocumentReplacementEvent
)
