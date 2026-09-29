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
    EnrichmentTriggeredEvent,
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
    SummaryEvent,
    ToolCallEvent,
)
from api.services.checkpoint_messages import load_message_count

# Alias so the schema model doesn't collide with the dataclass from
# observability.confidence_proxy imported below.
ConfidenceProxyModel = ConfidenceProxy
from core.config import (
    ANSWER_STREAM_TAG,
    INTERNAL_LLM_TAG,
    RERANKER_TYPE,
    RETRIEVER_FETCH_K,
)
from main import EcommerceSearchAgent
from observability.confidence_proxy import confidence_from_scores, count_rank_changes
from pipeline import enrichment_events

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
        # `self._agent` is a single shared EcommerceSearchAgent (see #23): its
        # thread_id/emit_callback/event_loop/event_queue are plain instance
        # attributes, reassigned per request. Two concurrent process_message()
        # calls race on them -- request B's emit_callback can overwrite
        # request A's mid-flight, so A's intermediate events land on B's
        # WebSocket (or vice versa), which manifests as one connection never
        # completing and Cloud Run's keepalive killing it with a 1011. This
        # lock serializes the section that touches shared agent state so only
        # one request drives the shared agent at a time.
        self._request_lock = asyncio.Lock()

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
        from core.config import RERANKER_WARMUP_ENABLED

        if not RERANKER_WARMUP_ENABLED:
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
            return await load_message_count(self._agent.async_pool, thread_id)
        except Exception:
            return 0

    async def process_message(
        self,
        message: str,
        thread_id: str,
        emit: EmitCallback,
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

            async with self._request_lock:
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
                from core.config import DEFAULT_ALPHA

                initial_state = {
                    "messages": [HumanMessage(content=message)],
                    "alpha": DEFAULT_ALPHA,
                    "query_analysis": "",
                    "quality_gate_retried": False,  # Reset for each new message
                }

                config = {
                    "configurable": {"thread_id": thread_id},
                }

                # Track metrics timing
                node_start_times: Dict[str, float] = {}
                final_response: Optional[str] = None
                documents_used = 0
                citations: List[Dict[str, str]] = []

                # Pipeline-summary state — accumulated as state updates flow past us.
                # Last-write-wins for each key: retriever_node sets pre_rerank/
                # latencies, reranker_node overwrites retrieved_documents
                # with the post-rerank list and adds reranker_latency_ms.
                pipeline_state: Dict[str, Any] = {
                    "user_query": "",
                    "pre_rerank_documents": [],
                    "post_rerank_documents": [],
                    "judgment": None,
                    "original_judgment": None,
                    "corrected_response": None,
                    "hallucination_retry_used": False,
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
                                            # Extract text if content is a list of content blocks
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
                                "judgment",
                                "original_judgment",
                                "corrected_response",
                                "hallucination_retry_used",
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

            # Emit completion event
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
                    citations=citations,
                )
            )
            logger.info("AgentCompleteEvent emitted successfully")

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

            # Emit the Pipeline Summary — last card the UI renders.
            # Best-effort; never blocks the user response on metric failure.
            try:
                summary = self._build_pipeline_summary(pipeline_state)
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
    ) -> Optional[PipelineSummaryEvent]:
        """Build the end-of-pipeline summary.

        Returns ``None`` when the request didn't trigger retrieval at all
        (e.g. summary intent), so the UI doesn't render an empty card.

        Emits the self-referential confidence proxy from the reranker score
        distribution, a per-stage latency table, and the LLM-as-judge row.
        """
        pre_rerank = pipeline_state.get("pre_rerank_documents") or []
        post_rerank = pipeline_state.get("post_rerank_documents") or []
        if not pre_rerank and not post_rerank:
            return None

        query = pipeline_state.get("user_query") or ""
        rerank_latency = float(pipeline_state.get("reranker_latency_ms") or 0.0)
        hybrid_latency = float(pipeline_state.get("retriever_latency_ms") or 0.0)

        hybrid_ids = [doc.metadata.get("product_id", "") for doc in pre_rerank]
        rerank_ids = [doc.metadata.get("product_id", "") for doc in post_rerank]

        # Confidence proxy from reranker scores (retrieval scores when the
        # reranker didn't score anything).
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

        # Latency table in pipeline order; the reranked row only when the
        # reranker actually ran (latency > 0).
        latency = [LatencyStage(stage="hybrid", latency_ms=hybrid_latency)]
        if rerank_latency > 0:
            latency.append(LatencyStage(stage="reranked", latency_ms=rerank_latency))

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
            query=query,
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
        # Snapshot-and-clear instead of repeated pop(0), which is O(n) per
        # call on a plain list and made the whole drain O(n^2).
        queued_events = self._agent.event_queue
        self._agent.event_queue = []
        for event in queued_events:
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

        # Bridge enrichment lifecycle events out of the agent node's worker
        # thread and onto this event loop (#103). The node publishes 'started'
        # before a ~20s re-index and a terminal event after it; without this
        # hop those would have nowhere to go, since the node is not on the
        # loop thread. Installed for the duration of this turn only, so
        # concurrent WebSocket turns never emit into each other's sockets.
        loop = asyncio.get_running_loop()

        def _publish_enrichment(**fields: Any) -> None:
            future = asyncio.run_coroutine_threadsafe(
                emit(EnrichmentTriggeredEvent(**fields)), loop
            )
            # Surface a failed hand-off instead of letting it vanish into an
            # un-awaited future.
            future.add_done_callback(
                lambda f: (
                    logger.warning("Enrichment event emit failed: %s", f.exception())
                    if f.exception()
                    else None
                )
            )

        publisher_token = enrichment_events.set_publisher(_publish_enrichment)

        try:
            async for event in self._agent.app.astream_events(
                initial_state,
                config=config,
                version="v2",
            ):
                event_type = event.get("event", "")
                event_name = event.get("name", "")
                event_data = event.get("data", {})

                # Handle node lifecycle events
                if event_type == "on_chain_start":
                    if event_name == "retriever":
                        input_state = event_data.get("input", {})
                        if input_state.get("intent") == "summary":
                            skipped_nodes.add(event_name)
                            continue

                    if event_name in tracked_nodes:
                        current_node = event_name
                        node_start_times[event_name] = time.time()

                        await emit(
                            NodeStartEvent(
                                node=event_name,
                                input_summary=self._summarize_input(event_name),
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
                                    # The node reports this itself now: its
                                    # tokens go out through the sync emit
                                    # bridge, not through a callback this loop
                                    # can observe (#103).
                                    (
                                        response_streaming_started
                                        or bool(accumulated_output.get("response_streamed"))
                                    )
                                    if event_name == "agent"
                                    else False
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
                    # agent_node makes model calls that are deliberation rather
                    # than the answer (the trigger_enrichment tool offer, the
                    # enrichment value judge). They run while current_node is
                    # "agent", so without this check their reasoning is streamed
                    # into the chat window as the reply — a user asking for
                    # wireless headphones got "Nothing in the query ... looks
                    # like a color or material term" (#103).
                    tags = event.get("tags") or []
                    is_internal = INTERNAL_LLM_TAG in tags
                    # agent_node streams the visible answer itself through the
                    # sync emit bridge. Streaming it here too doubles every
                    # token into the same browser-side buffer, rendering the
                    # reply interleaved with itself (#103).
                    is_answer_stream = ANSWER_STREAM_TAG in tags
                    if current_node in streaming_nodes and not is_internal and not is_answer_stream:
                        chunk = event_data.get("chunk")
                        if chunk:
                            # Handle different chunk formats
                            content = None
                            if hasattr(chunk, "content") and chunk.content:
                                content = chunk.content
                            elif isinstance(chunk, dict) and "content" in chunk:
                                content = chunk["content"]

                            # Extract text if content is a list of content blocks
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

        except Exception:
            # Log error and re-raise to trigger AgentErrorEvent in process_message
            logger.exception("Error in astream_events")
            raise
        finally:
            enrichment_events.reset_publisher(publisher_token)

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
            if documents:
                reranked_docs = self._compute_reranked_documents(documents)
                reranking_changed_order = self._check_if_order_changed(documents, reranked_docs)

                await emit(
                    RerankerResultEvent(
                        results=reranked_docs,
                        reranking_changed_order=reranking_changed_order,
                        reranker_type=RERANKER_TYPE,
                    )
                )

        elif node_name == "quality_gate":
            from core.config import DEFAULT_ALPHA, QUALITY_GATE_THRESHOLD

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
            # NOTE: enrichment events are NOT emitted here any more (#103).
            # This branch could only ever fire after the node had finished —
            # i.e. after the ~20s re-index AND the follow-up LLM compose — so
            # it could describe the lifecycle but never narrate it. The node
            # now publishes 'started' and its terminal event as they happen,
            # through pipeline.enrichment_events, bridged onto this loop in
            # stream_agent_events(). Re-adding an emit here would double-fire
            # the terminal event, ~2s late.

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
                            # Extract text if content is a list of content blocks
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

    def _summarize_input(self, node_name: str) -> str:
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
            except Exception:
                logger.exception("Error during agent cleanup")
            finally:
                self._initialized = False
