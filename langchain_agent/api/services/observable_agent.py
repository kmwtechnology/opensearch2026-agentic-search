"""
Observable Agent Service - Wrapper for EcommerceSearchAgent with event emission.

This service wraps the existing EcommerceSearchAgent and emits WebSocket events
during execution, providing full observability into the agent's workflow.
"""

import warnings

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

import asyncio
import logging
import sys
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from langchain_core.messages import AIMessage, HumanMessage

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# pylint: disable=wrong-import-position  # sys.path tweak above is required first
from api.schemas.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    BaseEvent,
    ConfidenceProxy,
    ConversationContextEvent,
    GenerationJudgment,
    HybridSearchStartEvent,
    IntentClassificationEvent,
    LatencyStage,
    LLMReasoningChunkEvent,
    LLMReasoningStartEvent,
    LLMResponseChunkEvent,
    LLMResponseCorrectedEvent,
    LLMResponseStartEvent,
    MetricsEvent,
    NodeEndEvent,
    NodeStartEvent,
    PipelineSummaryEvent,
    QualityGateEvent,
    QueryEvaluationEvent,
    RerankedDocument,
    RerankerResultEvent,
    StageMetrics,
    SummaryEvent,
    ToolCallEvent,
)

# Convenience aliases — match the names used in our local helper to avoid
# colliding with the relevancy_metrics dataclasses we also import below.
ConfidenceProxyModel = ConfidenceProxy
StageMetricsModel = StageMetrics
from config import (
    ENABLE_RERANKING,
    RETRIEVER_FETCH_K,
)
from main import EcommerceSearchAgent
from relevancy_metrics import (
    compute_stage_metrics,
    confidence_from_scores,
    count_rank_changes,
    latency_cost_benefit,
)

logger = logging.getLogger(__name__)

# Type alias for emit callback
EmitCallback = Callable[[BaseEvent], Coroutine[Any, Any, None]]


class ObservableAgentService:
    """
    Observable wrapper for EcommerceSearchAgent that emits events during execution.

    This service provides the same functionality as EcommerceSearchAgent but emits
    structured events at each step, enabling real-time observability in the UI.
    """

    def __init__(self):
        """Initialize the observable agent service (lazy loading)."""
        self._agent: Optional[EcommerceSearchAgent] = None
        self._initialized = False
        self._lock = asyncio.Lock()
        self._warmup_complete = False
        self._warmup_lock = asyncio.Lock()

    async def ensure_initialized(self):
        """Initialize the agent if not already done."""
        async with self._lock:
            if not self._initialized:
                await self._initialize_agent()
                await self._open_async_pool()
                self._initialized = True
                # Warmup reranker in background (non-blocking)
                asyncio.create_task(self._warmup_reranker())

    async def _initialize_agent(self):
        """Initialize the underlying EcommerceSearchAgent."""
        # Run synchronous initialization in thread pool
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._sync_init_agent)

    def _sync_init_agent(self):
        """Synchronous agent initialization."""
        self._agent = EcommerceSearchAgent()
        # Skip prerequisite verification in API mode
        # (health endpoint handles this)
        self._agent.initialize_components()
        self._agent.create_agent_graph()

    async def _open_async_pool(self):
        """Open the async pool for astream_events support."""
        if self._agent:
            await self._agent.ensure_async_pool_open()

    async def _warmup_reranker(self) -> None:
        """Warm up reranker in background (non-blocking)."""
        from config import ENABLE_RERANKING, RERANKER_WARMUP_ENABLED

        if not (ENABLE_RERANKING and RERANKER_WARMUP_ENABLED):
            async with self._warmup_lock:
                self._warmup_complete = True
            return

        if not self._agent or not self._agent.reranker:
            async with self._warmup_lock:
                self._warmup_complete = True
            return

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, self._agent.reranker.warmup)
            logger.info("Reranker warmup completed in background")
        except Exception as e:
            logger.warning(f"Reranker warmup failed (will lazy-init on first request): {e}")
        finally:
            async with self._warmup_lock:
                self._warmup_complete = True

    async def _wait_for_warmup(self) -> None:
        """Poll until warmup is complete (up to caller's timeout)."""
        while not self._warmup_complete:
            await asyncio.sleep(0.1)

    async def _load_conversation_context(self, thread_id: str) -> int:
        """
        Load previous message count from checkpoint.

        Args:
            thread_id: The conversation thread ID

        Returns:
            Number of previous human/AI messages in the conversation
        """
        try:
            pool = self._agent.async_pool
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """
                        SELECT blob, type FROM checkpoint_blobs
                        WHERE thread_id = %s AND channel = 'messages'
                        ORDER BY version DESC LIMIT 1
                    """,
                        (thread_id,),
                    )
                    blob_row = await cur.fetchone()
                    if blob_row and blob_row[0]:
                        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

                        serializer = JsonPlusSerializer()
                        messages = serializer.loads_typed((blob_row[1], blob_row[0]))
                        # Count human and AI messages
                        return len(
                            [
                                m
                                for m in messages
                                if hasattr(m, "type") and m.type in ("human", "ai")
                            ]
                        )
            return 0
        except Exception:
            return 0

    async def process_message(
        self,
        message: str,
        thread_id: str,
        emit: EmitCallback,
        optimizations: Optional[Dict[str, bool]] = None,
    ) -> Optional[str]:
        """
        Process a user message through the agent with observability.

        Args:
            message: The user's message
            thread_id: Conversation thread ID for persistence
            emit: Callback to emit events to the WebSocket

        Returns:
            The agent's final response text, or None if failed.
        """
        start_time = time.time()
        metrics: Dict[str, float] = {}

        try:
            # Wait for warmup to complete (poll without holding lock to avoid
            # deadlock with _warmup_reranker which needs the lock to set the flag)
            if not self._warmup_complete:
                logger.info("Waiting for reranker warmup to complete...")
                try:
                    await asyncio.wait_for(self._wait_for_warmup(), timeout=60.0)
                except asyncio.TimeoutError:
                    logger.warning(
                        "Reranker warmup did not complete in time; proceeding with lazy init"
                    )

            # Set thread for conversation persistence
            self._agent.set_thread_id(thread_id)

            # Set emit callback for intermediate events from retriever_node
            # Also store the current event loop so retriever_node can use it
            self._agent.emit_callback = emit
            try:
                self._agent.event_loop = asyncio.get_running_loop()
            except RuntimeError:
                pass  # No running loop, will fallback to queueing

            # Load and emit conversation context
            previous_count = await self._load_conversation_context(thread_id)
            is_new = previous_count == 0
            await emit(
                ConversationContextEvent(
                    previous_message_count=previous_count,
                    is_new_conversation=is_new,
                    summary=(
                        "New conversation"
                        if is_new
                        else f"Loaded {previous_count} previous messages"
                    ),
                )
            )

            # Build initial state
            # Reset per-query state while preserving conversation history via checkpoint
            from config import DEFAULT_ALPHA

            initial_state = {
                "messages": [HumanMessage(content=message)],
                "alpha": DEFAULT_ALPHA,
                "query_analysis": "",
                "quality_gate_retried": False,  # Reset for each new message
                "optimizations": optimizations or {},
            }

            config = {"configurable": {"thread_id": thread_id}}

            # Track metrics timing
            node_start_times: Dict[str, float] = {}
            final_response: Optional[str] = None
            documents_used = 0
            citations: List[Dict[str, str]] = []

            # Pipeline-summary state — accumulated as state updates flow past us.
            # Last-write-wins for each key: retriever_node sets pre_rerank/bm25/
            # judgments/latencies, reranker_node overwrites retrieved_documents
            # with the post-rerank list and adds reranker_latency_ms.
            pipeline_state: Dict[str, Any] = {
                "user_query": "",
                "pre_rerank_documents": [],
                "bm25_documents": [],
                "stock_bm25_documents": [],
                "post_rerank_documents": [],
                "judgments": None,
                "judgment": None,
                "original_judgment": None,
                "corrected_response": None,
                "hallucination_retry_used": False,
                "bm25_latency_ms": 0.0,
                "stock_bm25_latency_ms": 0.0,
                "retriever_latency_ms": 0.0,
                "reranker_latency_ms": 0.0,
            }

            # Stream through the graph (with 150s timeout to prevent hangs)
            async def stream_graph_with_timeout():
                nonlocal final_response, documents_used, citations
                async for event in self._astream_graph(
                    initial_state, config, emit, node_start_times, metrics
                ):
                    # Extract final response from agent completions
                    if isinstance(event, dict):
                        if "messages" in event:
                            for msg in event.get("messages", []):
                                if isinstance(msg, AIMessage) and msg.content:
                                    if not (hasattr(msg, "tool_calls") and msg.tool_calls):
                                        content = msg.content
                                        # Extract text if content is a list of content blocks (Gemini format)
                                        if isinstance(content, list):
                                            text_parts = []
                                            for block in content:
                                                if isinstance(block, dict) and "text" in block:
                                                    text_parts.append(block["text"])
                                            final_response = (
                                                "".join(text_parts) if text_parts else ""
                                            )
                                        else:
                                            final_response = content
                                        logger.debug(
                                            f"Extracted final_response: {len(final_response or '')} chars"
                                        )

                        if "retrieved_documents" in event:
                            documents_used = len(event["retrieved_documents"])
                            pipeline_state["post_rerank_documents"] = list(
                                event["retrieved_documents"]
                            )
                        for key in (
                            "user_query",
                            "pre_rerank_documents",
                            "bm25_documents",
                            "stock_bm25_documents",
                            "judgments",
                            "judgment",
                            "original_judgment",
                            "corrected_response",
                            "hallucination_retry_used",
                            "bm25_latency_ms",
                            "stock_bm25_latency_ms",
                            "retriever_latency_ms",
                            "reranker_latency_ms",
                        ):
                            if key in event and event[key] is not None:
                                pipeline_state[key] = event[key]
                        if "citations" in event and isinstance(event["citations"], list):
                            citations = event["citations"]

            try:
                await asyncio.wait_for(stream_graph_with_timeout(), timeout=150.0)
            except asyncio.TimeoutError:
                logger.warning("Graph execution timed out after 150s; proceeding with response")
                final_response = (
                    final_response or "Processing took longer than expected. Please try again."
                )

            logger.info(f"Graph execution completed. Preparing to emit completion event.")

            # Calculate total duration
            total_duration_ms = (time.time() - start_time) * 1000

            # Extract title from user message (don't wait for async title generation)
            title = message[:50].strip() if message else None

            # Emit completion event (don't block on title generation)
            logger.info(
                f"Emitting AgentCompleteEvent: {len(final_response or '')} chars, {total_duration_ms:.0f}ms"
            )
            await emit(
                AgentCompleteEvent(
                    thread_id=thread_id,
                    total_duration_ms=total_duration_ms,
                    final_response=final_response or "No response generated",
                    iterations=0,
                    response_retries=0,
                    documents_used=documents_used,
                    title=title,
                    citations=citations,
                )
            )
            logger.info("AgentCompleteEvent emitted successfully")

            # Generate and persist conversation title in background (non-blocking)
            asyncio.create_task(self._generate_title_async(thread_id, message, final_response))

            # Emit metrics
            await emit(
                MetricsEvent(
                    query_evaluation_ms=metrics.get("query_evaluator"),
                    retrieval_ms=metrics.get("retriever"),
                    reranking_ms=metrics.get("reranker"),
                    document_grading_ms=None,
                    llm_generation_ms=metrics.get("agent"),
                    response_grading_ms=None,
                    total_ms=total_duration_ms,
                )
            )

            # When the judge auto-corrected the response, tell the frontend to
            # replace the streamed message with the grounded version.
            if pipeline_state.get("hallucination_retry_used") and pipeline_state.get(
                "corrected_response"
            ):
                orig_faith = (pipeline_state.get("original_judgment") or {}).get(
                    "faithfulness", 0.0
                )
                corr_faith = (pipeline_state.get("judgment") or {}).get("faithfulness", 0.0)
                await emit(
                    LLMResponseCorrectedEvent(
                        corrected_content=pipeline_state["corrected_response"],
                        original_faithfulness=orig_faith,
                        corrected_faithfulness=corr_faith,
                    )
                )

            # Emit Pipeline Quality Summary — last card the UI renders.
            # Best-effort; never blocks the user response on metric failure.
            try:
                summary = self._build_pipeline_summary(pipeline_state, optimizations or {})
                if summary is not None:
                    await emit(summary)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Failed to build PipelineSummaryEvent: %s", exc, exc_info=True)

            return final_response

        except (TimeoutError, ConnectionError, RuntimeError) as e:
            await emit(
                AgentErrorEvent(
                    error=str(e),
                    recoverable=True,  # Transient failures may succeed on retry
                )
            )
            return None
        except Exception as e:
            logger.exception("Unexpected error in agent execution")
            await emit(
                AgentErrorEvent(
                    error=str(e),
                    recoverable=False,  # Logic errors, etc. are not retryable
                )
            )
            return None

    def _build_pipeline_summary(
        self,
        pipeline_state: Dict[str, Any],
        optimizations: Dict[str, bool],
    ) -> Optional[PipelineSummaryEvent]:
        """Build the end-of-pipeline retrieval-quality summary.

        Returns ``None`` when the request didn't trigger retrieval at all
        (e.g. summary intent), so the UI doesn't render an empty card.

        When ESCI ground truth is available, populates per-stage IR
        metrics (BM25 / hybrid / reranked) and computes the cost-benefit
        latency table. Otherwise emits the self-referential confidence
        proxy from the reranker score distribution.
        """
        pre_rerank = pipeline_state.get("pre_rerank_documents") or []
        bm25_docs = pipeline_state.get("bm25_documents") or []
        stock_bm25_docs = pipeline_state.get("stock_bm25_documents") or []
        post_rerank = pipeline_state.get("post_rerank_documents") or []
        if not pre_rerank and not bm25_docs and not post_rerank and not stock_bm25_docs:
            return None

        query = pipeline_state.get("user_query") or ""
        judgments = pipeline_state.get("judgments")

        # User toggles drive which rows we render. Hybrid row is redundant
        # when ``hybrid:false`` (the hybrid call routed to plain BM25 with
        # toggles, identical to the bm25 row). Reranked row only matters
        # when reranking actually ran (latency > 0).
        hybrid_on = optimizations.get("hybrid", True)
        rerank_latency = float(pipeline_state.get("reranker_latency_ms") or 0.0)
        show_hybrid = hybrid_on
        show_rerank = rerank_latency > 0

        bm25_latency = float(pipeline_state.get("bm25_latency_ms") or 0.0)
        stock_bm25_latency = float(pipeline_state.get("stock_bm25_latency_ms") or 0.0)
        # Hybrid stage's "incremental" latency is the part not already paid by
        # BM25 (they ran in parallel, so the wall-clock cost of hybrid was
        # max(hybrid, bm25)). Use the raw retriever_latency_ms — it represents
        # what the hybrid stage would cost on its own.
        hybrid_latency = float(pipeline_state.get("retriever_latency_ms") or 0.0)

        stock_bm25_ids = [doc.metadata.get("product_id", "") for doc in stock_bm25_docs]
        bm25_ids = [doc.metadata.get("product_id", "") for doc in bm25_docs]
        hybrid_ids = [doc.metadata.get("product_id", "") for doc in pre_rerank]
        rerank_ids = [doc.metadata.get("product_id", "") for doc in post_rerank]

        stock_bm25_metrics = bm25_metrics = hybrid_metrics = rerank_metrics = None
        stock_bm25_ndcg = bm25_ndcg = hybrid_ndcg = rerank_ndcg = None
        confidence = None

        if judgments:
            # Ground-truth layout: compute IR metrics for each visible stage.
            if stock_bm25_ids:
                stage = compute_stage_metrics(stock_bm25_ids, judgments)
                stock_bm25_metrics = StageMetricsModel(**stage.to_dict())
                stock_bm25_ndcg = stage.ndcg10
            if bm25_ids:
                stage = compute_stage_metrics(bm25_ids, judgments)
                bm25_metrics = StageMetricsModel(**stage.to_dict())
                bm25_ndcg = stage.ndcg10
            if hybrid_ids and show_hybrid:
                stage = compute_stage_metrics(hybrid_ids, judgments)
                hybrid_metrics = StageMetricsModel(**stage.to_dict())
                hybrid_ndcg = stage.ndcg10
            if rerank_ids and show_rerank:
                stage = compute_stage_metrics(rerank_ids, judgments)
                rerank_metrics = StageMetricsModel(**stage.to_dict())
                rerank_ndcg = stage.ndcg10
        else:
            # Fallback: confidence proxy from reranker scores (or retrieval
            # scores when reranker is off).
            scores: List[float] = []
            for doc in post_rerank:
                score = doc.metadata.get("reranker_score")
                if score is not None:
                    scores.append(float(score))
            if not scores:
                for doc in pre_rerank:
                    score = doc.metadata.get("retrieval_score")
                    if score is not None:
                        scores.append(float(score))
            rank_changes = count_rank_changes(hybrid_ids, rerank_ids, k=10)
            proxy = confidence_from_scores(scores, rank_changes_count=rank_changes)
            confidence = ConfidenceProxyModel(**proxy.to_dict())

        # Build latency table ordered by pipeline progression. Stages omitted
        # when they didn't run or when toggles hide them.
        latency_inputs: List[Dict[str, Any]] = [
            {"stage": "stock_bm25", "latency_ms": stock_bm25_latency, "ndcg": stock_bm25_ndcg},
            {"stage": "bm25", "latency_ms": bm25_latency, "ndcg": bm25_ndcg},
        ]
        if show_hybrid:
            latency_inputs.append(
                {"stage": "hybrid", "latency_ms": hybrid_latency, "ndcg": hybrid_ndcg}
            )
        if show_rerank:
            latency_inputs.append(
                {"stage": "reranked", "latency_ms": rerank_latency, "ndcg": rerank_ndcg}
            )
        latency_rows = latency_cost_benefit(latency_inputs)
        latency = [LatencyStage(**row) for row in latency_rows]

        # Generation row — built from llm_judge_node output (already a dict).
        generation: Optional[GenerationJudgment] = None
        original_generation: Optional[GenerationJudgment] = None
        judgment_dict = pipeline_state.get("judgment")
        if judgment_dict:
            try:
                generation = GenerationJudgment(**judgment_dict)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Failed to coerce judgment dict: %s", exc)
        original_judgment_dict = pipeline_state.get("original_judgment")
        if original_judgment_dict:
            try:
                original_generation = GenerationJudgment(**original_judgment_dict)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Failed to coerce original judgment dict: %s", exc)

        return PipelineSummaryEvent(
            has_ground_truth=judgments is not None,
            query=query,
            optimizations=optimizations,
            stock_bm25=stock_bm25_metrics,
            bm25=bm25_metrics,
            hybrid=hybrid_metrics,
            reranked=rerank_metrics,
            confidence=confidence,
            generation=generation,
            original_generation=original_generation,
            hallucination_retry_used=bool(pipeline_state.get("hallucination_retry_used")),
            corrected_response=pipeline_state.get("corrected_response"),
            latency=latency,
        )

    async def _emit_queued_events(self, emit: EmitCallback) -> None:
        """
        Process and emit any events queued by the retriever_node.

        The retriever_node runs synchronously and can't directly emit async events,
        so it queues them for later emission.
        """
        while self._agent.event_queue:
            event = self._agent.event_queue.pop(0)
            await emit(event)

    async def _astream_graph(
        self,
        initial_state: Dict[str, Any],
        config: Dict[str, Any],
        emit: EmitCallback,
        node_start_times: Dict[str, float],
        metrics: Dict[str, float],
    ):
        """
        Stream through the agent graph using LangGraph's astream_events v2 API.

        Provides responsive streaming by capturing:
        - on_chain_start/on_chain_end: Node lifecycle events
        - on_chat_model_stream: Individual LLM token chunks
        - on_tool_start/on_tool_end: Tool execution events

        Yields state updates as they occur.
        """
        # Known LangGraph nodes to track (filter out internal chains)
        tracked_nodes = {
            "intent_classifier",
            "query_evaluator",
            "summary",
            "retriever",
            "reranker",
            "quality_gate",
            "agent",
            "llm_judge",
        }
        current_node: Optional[str] = None
        accumulated_output: Dict[str, Any] = {}
        response_streaming_started = False  # Track if we've started streaming LLM response
        skipped_nodes: Set[str] = set()

        try:
            async for event in self._agent.app.astream_events(
                initial_state,
                config=config,
                version="v2",
            ):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Helper: read per-message optimization toggles off the input state.
                def _opts(event_data: Dict[str, Any]) -> Dict[str, bool]:
                    return (event_data.get("input") or {}).get("optimizations") or {}

                # Handle node lifecycle events
                if event_type == "on_chain_start":
                    if event_name == "retriever":
                        input_state = event_data.get("input", {})
                        if input_state.get("intent") == "summary":
                            skipped_nodes.add(event_name)
                            continue

                    # query_evaluator's only used output is `alpha`. With hybrid
                    # search forced off the retriever ignores alpha entirely,
                    # so the evaluator step is decorative — hide it.
                    if event_name == "query_evaluator":
                        opts = _opts(event_data)
                        if opts.get("hybrid", True) is False:
                            skipped_nodes.add(event_name)
                            continue

                    # Hide the reranker step from the observability panel when
                    # the user has toggled reranking off — the node still
                    # short-circuits internally but emits no UI events.
                    if event_name == "reranker":
                        opts = _opts(event_data)
                        if opts.get("reranking", True) is False:
                            skipped_nodes.add(event_name)
                            continue

                    # Quality gate is a no-op when its retry-with-different-alpha
                    # mechanism can't help: reranking off (no scores to judge),
                    # llm off (raw results don't need quality validation), or
                    # hybrid off (alpha is ignored so retry can't change ranking).
                    if event_name == "quality_gate":
                        opts = _opts(event_data)
                        if (
                            opts.get("reranking", True) is False
                            or opts.get("llm", True) is False
                            or opts.get("hybrid", True) is False
                        ):
                            skipped_nodes.add(event_name)
                            continue

                    # LLM-as-judge step is a no-op (and skipped from the panel)
                    # when the toggle is off or LLM Response Generation is off.
                    if event_name == "llm_judge":
                        opts = _opts(event_data)
                        if not opts.get("llm_judge", False) or opts.get("llm", True) is False:
                            skipped_nodes.add(event_name)
                            continue

                    if event_name in tracked_nodes:
                        current_node = event_name
                        node_start_times[event_name] = time.time()

                        await emit(
                            NodeStartEvent(
                                node=event_name,
                                input_summary=f"Starting {event_name}",
                            )
                        )

                        # Emit HybridSearchStartEvent immediately when retriever starts
                        if event_name == "retriever":
                            input_state = event_data.get("input", {})
                            query = ""
                            for msg in reversed(input_state.get("messages", [])):
                                if (
                                    hasattr(msg, "content")
                                    and hasattr(msg, "type")
                                    and msg.type == "human"
                                ):
                                    query = msg.content
                                    break

                            await emit(
                                HybridSearchStartEvent(
                                    query=query,
                                    alpha=input_state.get("alpha", 0.25),
                                    fetch_k=RETRIEVER_FETCH_K,
                                )
                            )

                elif event_type == "on_chain_end":
                    if event_name in skipped_nodes:
                        skipped_nodes.remove(event_name)
                        continue

                    if event_name in tracked_nodes:
                        duration_ms = 0.0
                        if event_name in node_start_times:
                            duration_ms = (time.time() - node_start_times[event_name]) * 1000
                            metrics[event_name] = metrics.get(event_name, 0) + duration_ms

                        # Extract output from event
                        output = event_data.get("output", {})
                        if isinstance(output, dict):
                            accumulated_output.update(output)

                            # Emit node-specific events
                            # Pass streaming flag for agent node to avoid duplicate response emission
                            await self._emit_node_events(
                                event_name,
                                output,
                                emit,
                                already_streamed=(
                                    response_streaming_started if event_name == "agent" else False
                                ),
                            )

                            # Emit any events queued by retriever_node
                            await self._emit_queued_events(emit)

                        # Skip NodeEndEvent for summary node when no summary was generated
                        skip_node_end = (
                            event_name == "summary"
                            and isinstance(output, dict)
                            and output.get("summary_text") is None
                        )

                        if not skip_node_end:
                            await emit(
                                NodeEndEvent(
                                    node=event_name,
                                    duration_ms=duration_ms,
                                    output_summary=self._summarize_output(
                                        event_name, output if isinstance(output, dict) else {}
                                    ),
                                )
                            )

                        # Yield the output for state tracking
                        if isinstance(output, dict) and output:
                            yield output

                # Handle LLM token streaming
                elif event_type == "on_chat_model_stream":
                    # Stream to chat window for agent node and content generator nodes
                    # (query_evaluator outputs JSON which shouldn't be shown to user)
                    streaming_nodes = {
                        "agent",
                    }
                    if current_node in streaming_nodes:
                        chunk = event_data.get("chunk")
                        if chunk:
                            # Handle different chunk formats
                            content = None
                            if hasattr(chunk, "content") and chunk.content:
                                content = chunk.content
                            elif isinstance(chunk, dict) and "content" in chunk:
                                content = chunk["content"]

                            # Extract text if content is a list of content blocks (Gemini format)
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and "text" in block:
                                        text_parts.append(block["text"])
                                content = "".join(text_parts) if text_parts else None

                            if content and isinstance(content, str):
                                # Emit start event on first chunk (enables chat window streaming)
                                if not response_streaming_started:
                                    await emit(LLMResponseStartEvent())
                                    response_streaming_started = True
                                # Emit token chunk directly to WebSocket
                                await emit(
                                    LLMResponseChunkEvent(
                                        content=content,
                                        is_complete=False,
                                    )
                                )

                # Handle tool events
                elif event_type == "on_tool_start":
                    tool_name = event_name
                    tool_input = event_data.get("input", {})
                    await emit(
                        ToolCallEvent(
                            tool_name=tool_name,
                            tool_args=(
                                tool_input
                                if isinstance(tool_input, dict)
                                else {"query": str(tool_input)}
                            ),
                        )
                    )

        except Exception as e:
            # Log error and re-raise to trigger AgentErrorEvent in process_message
            import traceback

            print(f"Error in astream_events: {e}")
            traceback.print_exc()
            raise

    async def _emit_node_events(
        self,
        node_name: str,
        output: Dict[str, Any],
        emit: EmitCallback,
        already_streamed: bool = False,
    ):
        """Emit detailed events for specific nodes.

        Args:
            already_streamed: If True for agent node, skip re-emitting the full response
                             (it was already streamed token-by-token via on_chat_model_stream)
        """

        if node_name == "intent_classifier":
            await emit(
                IntentClassificationEvent(
                    intent=output.get("intent", "question"),
                    user_query=output.get("user_query", ""),
                    reasoning=output.get("reasoning", "Heuristic classification"),
                    confidence=output.get("confidence") or output.get("intent_confidence"),
                )
            )
        elif node_name == "query_evaluator":
            await emit(
                QueryEvaluationEvent(
                    query="",  # Original query used as-is (no query rewriting)
                    alpha=output.get("alpha", 0.25),
                    query_analysis=output.get("query_analysis", ""),
                    search_strategy=self._get_search_strategy(output.get("alpha", 0.25)),
                )
            )

        elif node_name == "summary":
            await emit(
                SummaryEvent(
                    summary_text=output.get("summary_text"),
                    message_count=output.get("message_count", 0),
                )
            )

        elif node_name == "retriever":
            # Search events (hybrid_search_result etc.) are emitted from within retriever_node
            pass

        elif node_name == "reranker":
            # Emit reranker result event with detailed document information.
            # Prefer the full scored list (``all_reranked_documents``) so the
            # UI can show every candidate the cross-encoder evaluated, not
            # just the top-K cut handed to the agent.
            documents = output.get("all_reranked_documents") or output.get(
                "retrieved_documents", []
            )
            if documents and ENABLE_RERANKING:
                reranked_docs = self._compute_reranked_documents(documents)
                reranking_changed_order = self._check_if_order_changed(documents, reranked_docs)

                await emit(
                    RerankerResultEvent(
                        results=reranked_docs,
                        reranking_changed_order=reranking_changed_order,
                    )
                )

        elif node_name == "quality_gate":
            from config import DEFAULT_ALPHA, QUALITY_GATE_THRESHOLD

            reason = output.get("quality_gate_reason", "")
            triggered = reason.startswith("RETRY")
            await emit(
                QualityGateEvent(
                    triggered=triggered,
                    original_alpha=(
                        DEFAULT_ALPHA if triggered else output.get("alpha", DEFAULT_ALPHA)
                    ),
                    new_alpha=output.get("alpha") if triggered else None,
                    max_score=output.get("reranker_max_score", 0.0),
                    threshold=output.get("quality_gate_threshold_used", QUALITY_GATE_THRESHOLD),
                    reason=reason,
                )
            )

        elif node_name == "agent":
            # Emit LLM events
            messages = output.get("messages", [])
            for msg in messages:
                if isinstance(msg, AIMessage):
                    # Check for reasoning in additional_kwargs
                    reasoning = None
                    if hasattr(msg, "additional_kwargs") and msg.additional_kwargs:
                        reasoning = msg.additional_kwargs.get("reasoning")

                    # Emit reasoning if present
                    if reasoning:
                        await emit(LLMReasoningStartEvent())
                        await emit(
                            LLMReasoningChunkEvent(
                                content=reasoning,
                                is_complete=True,
                            )
                        )

                    # Check for tool calls
                    if hasattr(msg, "tool_calls") and msg.tool_calls:
                        for tool_call in msg.tool_calls:
                            await emit(
                                ToolCallEvent(
                                    tool_name=tool_call["name"],
                                    tool_args=tool_call["args"],
                                )
                            )

                    # Always emit response event if there's content or tool calls
                    # If content is empty but msg exists, emit empty response to signal completion
                    if msg.content or (hasattr(msg, "tool_calls") and msg.tool_calls):
                        if msg.content:
                            # For responses without tool calls, check if content needs parsing
                            # (handles Ollama models that format reasoning as "Reasoning: ... \nAnswer: ...")
                            content = msg.content
                            # Extract text if content is a list of content blocks (Gemini format)
                            if isinstance(content, list):
                                text_parts = []
                                for block in content:
                                    if isinstance(block, dict) and "text" in block:
                                        text_parts.append(block["text"])
                                content = "".join(text_parts) if text_parts else ""
                            reasoning_extracted, response_content = self._parse_structured_response(
                                content
                            )

                            # Emit reasoning if extracted from content
                            if reasoning_extracted and not reasoning:
                                await emit(LLMReasoningStartEvent())
                                await emit(
                                    LLMReasoningChunkEvent(
                                        content=reasoning_extracted,
                                        is_complete=True,
                                    )
                                )

                            if already_streamed:
                                # Response was already streamed token-by-token to chat window
                                # Just emit completion marker
                                await emit(
                                    LLMResponseChunkEvent(
                                        content="",
                                        is_complete=True,
                                    )
                                )
                            else:
                                # Emit full response (fallback for non-streaming models)
                                await emit(LLMResponseStartEvent())
                                await emit(
                                    LLMResponseChunkEvent(
                                        content=response_content,
                                        is_complete=True,
                                    )
                                )
                        elif not already_streamed:
                            # Emit empty response if no content but message was generated
                            await emit(LLMResponseStartEvent())
                            await emit(
                                LLMResponseChunkEvent(
                                    content="",
                                    is_complete=True,
                                )
                            )

    def _parse_structured_response(self, content: str) -> tuple[Optional[str], str]:
        """
        Parse LLM responses that may contain structured reasoning.

        Some models format responses as:
        "Reasoning: <reasoning text>
         Answer: <answer text>"

        Returns:
            A tuple of (reasoning_text, response_text)
            If no structured format is found, returns (None, content)
        """
        if not content:
            return None, content

        # Look for the pattern "Reasoning:" and "Answer:"
        reasoning_pattern = "Reasoning:"
        answer_pattern = "Answer:"

        if reasoning_pattern in content and answer_pattern in content:
            try:
                reasoning_start = content.find(reasoning_pattern) + len(reasoning_pattern)
                reasoning_end = content.find(answer_pattern)

                if reasoning_end > reasoning_start:
                    reasoning_text = content[reasoning_start:reasoning_end].strip()
                    answer_start = reasoning_end + len(answer_pattern)
                    answer_text = content[answer_start:].strip()

                    return reasoning_text, answer_text
            except Exception:
                # If parsing fails, return the original content
                pass

        return None, content

    def _compute_reranked_documents(self, documents: List) -> List:
        """
        Compute RerankedDocument objects from retrieved documents.

        Since the documents in output["retrieved_documents"] are already reranked
        by the retriever_node before reaching this method, we construct RerankedDocument
        objects using their current positions and extract scores from metadata.

        Args:
            documents: List of LangChain Document objects (already reranked)

        Returns:
            List of RerankedDocument objects with ranking information
        """
        reranked_docs = []

        for rank, doc in enumerate(documents, 1):
            source = doc.metadata.get("source", "unknown")
            # Extract reranker score if available, otherwise use 0.0
            score = doc.metadata.get("reranker_score", 0.0)
            # Extract original rank if available, otherwise estimate based on position
            original_rank = doc.metadata.get("original_rank", rank)
            # Calculate rank change (negative = improved/moved up, positive = degraded/moved down)
            rank_change = rank - original_rank

            snippet = (
                doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            )

            reranked_docs.append(
                RerankedDocument(
                    source=source,
                    score=score,
                    rank=rank,
                    original_rank=original_rank,
                    snippet=snippet,
                    rank_change=rank_change,
                    url=doc.metadata.get("url"),
                )
            )

        return reranked_docs

    def _check_if_order_changed(self, documents: List, reranked_docs: List) -> bool:
        """
        Determine if reranking changed the document order.

        This is a heuristic check based on whether any document moved from its
        original position. Since we don't have the pre-reranking order directly,
        we check if any document has a non-zero rank_change value.

        Args:
            documents: List of LangChain Document objects (reranked)
            reranked_docs: List of RerankedDocument objects with rank info

        Returns:
            Boolean indicating if any document's rank changed
        """
        return any(doc.rank_change != 0 for doc in reranked_docs)

    def _get_search_strategy(self, alpha: float) -> str:
        """Convert alpha to human-readable search strategy.

        Alpha scale (standard hybrid search convention):
        - 0.0-0.3: Pure lexical (BM25/text-heavy)
        - 0.3-0.7: Balanced hybrid
        - 0.7-1.0: Pure semantic (vector-heavy)
        """
        if alpha < 0.3:
            return "lexical-heavy"
        elif alpha < 0.7:
            return "balanced"
        else:
            return "semantic-heavy"

    def _summarize_input(self, node_name: str, output: Dict[str, Any]) -> str:
        """Generate a brief summary of node input."""
        if node_name == "query_evaluator":
            return "Evaluating query type for optimal search strategy"
        elif node_name == "retriever":
            return "Executing hybrid search"
        elif node_name == "reranker":
            return "Reranking documents by relevance"
        elif node_name == "quality_gate":
            return "Evaluating result quality"
        elif node_name == "agent":
            return "Generating response from documents"
        elif node_name == "intent_classifier":
            return "Classifying user intent"
        elif node_name == "summary":
            return "Preparing conversation summary"
        return ""

    def _summarize_output(self, node_name: str, output: Dict[str, Any]) -> str:
        """Generate a brief summary of node output."""
        if node_name == "query_evaluator":
            return f"alpha={output.get('alpha', 0.25):.2f}"
        elif node_name == "retriever":
            docs = output.get("retrieved_documents", [])
            return f"{len(docs)} documents retrieved"
        elif node_name == "reranker":
            # Prefer the full scored list so the step header reflects every
            # candidate the cross-encoder evaluated (the agent still gets
            # only the top-K subset for grounded generation).
            docs = output.get("all_reranked_documents") or output.get("retrieved_documents", [])
            max_score = output.get("reranker_max_score", 0.0)
            return f"{len(docs)} documents reranked (max={max_score:.3f})"
        elif node_name == "quality_gate":
            reason = output.get("quality_gate_reason", "")
            return reason
        elif node_name == "agent":
            messages = output.get("messages", [])
            if messages:
                return "Response generated"
            return ""
        elif node_name == "intent_classifier":
            intent = output.get("intent", "unknown")
            reasoning = output.get("reasoning", "Heuristic classification")
            return f"Intent → {intent} ({reasoning})"
        elif node_name == "summary":
            summary_text = output.get("summary_text")
            message_count = output.get("message_count", 0)
            if summary_text:
                return f"{message_count} messages summarized"
            return f"Summary skipped ({message_count} msgs)"
        return ""

    async def _generate_title_async(
        self,
        _thread_id: str,
        user_message: str,
        _response: Optional[str],
    ) -> None:
        """Generate and persist conversation title in background (non-blocking).

        This runs asynchronously after AgentCompleteEvent is emitted, so any
        delays in LLM title generation don't block the WebSocket response.

        `_thread_id` and `_response` are accepted for API symmetry with the
        upstream call site but the agent already has the thread_id internally
        and synthesizes the title from the prior conversation state.
        """
        try:
            loop = asyncio.get_event_loop()
            # update_conversation_title() uses the internally set thread_id
            # and handles both generation and database update
            await loop.run_in_executor(None, self._agent.update_conversation_title)
            logger.debug(f"Background title generation completed for thread {_thread_id}")
        except Exception as e:  # pylint: disable=broad-exception-caught
            logger.warning(f"Background title generation failed: {e}")

    async def cleanup(self):
        """
        Clean up resources held by the agent.

        This must be called before shutting down the service to properly
        release memory held by models (especially the reranker) and database
        connections.
        """
        if self._agent:
            try:
                # Close async pool first
                await self._agent.close_async_pool()
                # Call the agent's cleanup method which handles:
                # - Deleting reranker model from memory
                # - Clearing CUDA cache
                # - Closing database connection pool
                self._agent.cleanup()
                self._agent = None
            except Exception as e:
                print(f"Error during agent cleanup: {e}")
            finally:
                self._initialized = False
