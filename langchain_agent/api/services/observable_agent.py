"""Wraps EcommerceSearchAgent and emits a WebSocket event for each step of a turn."""

import asyncio
import logging
import time
from typing import Any, Callable, Coroutine, Dict, List, Optional

from langchain_core.messages import AIMessage, HumanMessage

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
    LLMResponseChunkEvent,
    LLMResponseCorrectedEvent,
    LLMResponseStartEvent,
    NodeEndEvent,
    NodeStartEvent,
    PipelineSummaryEvent,
    QualityGateEvent,
    QueryEvaluationEvent,
    RerankedDocument,
    RerankerResultEvent,
    SummaryEvent,
)
from api.services.checkpoint_messages import load_message_count
from core.config import (
    ANSWER_STREAM_TAG,
    DEFAULT_ALPHA,
    INTERNAL_LLM_TAG,
)
from main import EcommerceSearchAgent
from observability.confidence_proxy import confidence_from_scores, count_rank_changes
from observability.llm_content import _flatten_llm_content
from pipeline import enrichment_events

logger = logging.getLogger(__name__)

# Type alias for emit callback
EmitCallback = Callable[[BaseEvent], Coroutine[Any, Any, None]]


class ObservableAgentService:
    """Drives the shared EcommerceSearchAgent and emits structured events per step."""

    def __init__(self):
        """Initialize the observable agent service (lazy loading)."""
        self._agent: Optional[EcommerceSearchAgent] = None
        self._initialized = False
        self._lock = asyncio.Lock()
        self._warmup_complete = False
        self._warmup_lock = asyncio.Lock()
        # The single shared agent keeps emit_callback/event_loop as plain
        # attributes set per request; concurrent turns would overwrite each other's and
        # cross-deliver events. This lock serializes the section that uses them.
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
        """Number of prior human/AI messages checkpointed for the thread (0 on any error)."""
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
        """Run one user message through the graph, emitting events; returns the final answer text, or None on failure."""
        start_time = time.time()
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
                # Nodes on worker threads emit through these.
                self._agent.emit_callback = emit
                self._agent.event_loop = asyncio.get_running_loop()

                previous_count = await self._load_conversation_context(thread_id)
                is_new = previous_count == 0
                await emit(
                    ConversationContextEvent(
                        previous_message_count=previous_count,
                        is_new_conversation=is_new,
                    )
                )

                # Per-query state is reset here; history comes from the checkpoint.
                initial_state = {
                    "messages": [HumanMessage(content=message)],
                    "alpha": DEFAULT_ALPHA,
                    "query_analysis": "",
                    "quality_gate_retried": False,  # Reset for each new message
                }

                config = {
                    "configurable": {"thread_id": thread_id},
                }

                final_response: Optional[str] = None
                citations: List[Dict[str, str]] = []

                # Pipeline-summary state, last write wins per key as node outputs flow past.
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

                # 150s cap so a hung node cannot hold the request lock forever.
                async def stream_graph_with_timeout():
                    nonlocal final_response, citations
                    async for event in self._astream_graph(initial_state, config, emit):
                        if isinstance(event, dict):
                            if "messages" in event:
                                for msg in event.get("messages", []):
                                    if isinstance(msg, AIMessage) and msg.content:
                                        if not getattr(msg, "tool_calls", None):
                                            final_response = _flatten_llm_content(msg)
                                            logger.debug(
                                                f"Extracted final_response: {len(final_response)} chars"
                                            )

                            if "retrieved_documents" in event:
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

            total_duration_ms = (time.time() - start_time) * 1000

            logger.info(
                f"Emitting AgentCompleteEvent: {len(final_response or '')} chars, {total_duration_ms:.0f}ms"
            )
            await emit(
                AgentCompleteEvent(
                    thread_id=thread_id,
                    total_duration_ms=total_duration_ms,
                    final_response=final_response or "No response generated",
                    citations=citations,
                )
            )

            # The judge auto-corrected the answer: tell the UI to replace the streamed text.
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

            # Last card the UI renders; a failure here must not block the answer.
            try:
                summary = self._build_pipeline_summary(pipeline_state)
                if summary is not None:
                    await emit(summary)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("Failed to build PipelineSummaryEvent: %s", exc, exc_info=True)

            return final_response

        except Exception as e:
            # Transient failures are expected; anything else gets a traceback.
            if not isinstance(e, (TimeoutError, ConnectionError, RuntimeError)):
                logger.exception("Unexpected error in agent execution")
            await emit(AgentErrorEvent(error=str(e)))
            return None

    def _build_pipeline_summary(
        self,
        pipeline_state: Dict[str, Any],
    ) -> Optional[PipelineSummaryEvent]:
        """End-of-turn summary: confidence proxy from the reranker score distribution, a
        per-stage latency table, and the judge rows. None when the turn did no retrieval."""
        pre_rerank = pipeline_state.get("pre_rerank_documents") or []
        post_rerank = pipeline_state.get("post_rerank_documents") or []
        if not pre_rerank and not post_rerank:
            return None

        query = pipeline_state.get("user_query") or ""
        rerank_latency = float(pipeline_state.get("reranker_latency_ms") or 0.0)
        hybrid_latency = float(pipeline_state.get("retriever_latency_ms") or 0.0)

        hybrid_ids = [doc.metadata.get("product_id", "") for doc in pre_rerank]
        rerank_ids = [doc.metadata.get("product_id", "") for doc in post_rerank]

        # Reranker scores, or retrieval scores when the reranker scored nothing.
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
        confidence = ConfidenceProxy(**proxy.to_dict())

        # The reranked row only when the reranker ran.
        latency = [LatencyStage(stage="hybrid", latency_ms=hybrid_latency)]
        if rerank_latency > 0:
            latency.append(LatencyStage(stage="reranked", latency_ms=rerank_latency))

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
            latency=latency,
        )

    async def _astream_graph(
        self,
        initial_state: Dict[str, Any],
        config: Dict[str, Any],
        emit: EmitCallback,
    ):
        """Stream the graph via astream_events v2: node lifecycle, LLM tokens; yields each node's output."""
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
        node_start_times: Dict[str, float] = {}
        current_node: Optional[str] = None
        accumulated_output: Dict[str, Any] = {}
        response_streaming_started = False

        # Bridge enrichment lifecycle events from the agent node's worker thread onto this
        # loop, for this turn only so concurrent turns never emit into each other's sockets.
        loop = asyncio.get_running_loop()

        def _publish_enrichment(**fields: Any) -> None:
            future = asyncio.run_coroutine_threadsafe(
                emit(EnrichmentTriggeredEvent(**fields)), loop
            )
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

                if event_type == "on_chain_start":
                    if event_name in tracked_nodes:
                        current_node = event_name
                        node_start_times[event_name] = time.time()

                        await emit(
                            NodeStartEvent(
                                node=event_name,
                                input_summary=self._summarize_input(event_name),
                            )
                        )

                        if event_name == "retriever":
                            await emit(HybridSearchStartEvent())

                elif event_type == "on_chain_end":
                    if event_name in tracked_nodes:
                        duration_ms = 0.0
                        if event_name in node_start_times:
                            duration_ms = (time.time() - node_start_times[event_name]) * 1000

                        output = event_data.get("output", {})
                        if isinstance(output, dict):
                            accumulated_output.update(output)

                            await self._emit_node_events(
                                event_name,
                                output,
                                emit,
                                # The agent node reports it itself: its tokens leave through the
                                # sync emit bridge, not a callback this loop can observe.
                                already_streamed=event_name == "agent"
                                and (
                                    response_streaming_started
                                    or bool(accumulated_output.get("response_streamed"))
                                ),
                            )

                        await emit(
                            NodeEndEvent(
                                node=event_name,
                                duration_ms=duration_ms,
                                output_summary=self._summarize_output(
                                    event_name, output if isinstance(output, dict) else {}
                                ),
                            )
                        )

                        if isinstance(output, dict) and output:
                            yield output

                elif event_type == "on_chat_model_stream":
                    # Only untagged model calls inside the agent node stream here: the answer
                    # is streamed by the node itself (tagged ANSWER_STREAM_TAG; streaming it
                    # here too would interleave every token twice), and INTERNAL_LLM_TAG marks
                    # deliberation (tool offers, value judge) that must not reach the chat.
                    tags = event.get("tags") or []
                    if (
                        current_node == "agent"
                        and INTERNAL_LLM_TAG not in tags
                        and ANSWER_STREAM_TAG not in tags
                    ):
                        chunk = event_data.get("chunk")
                        content = (
                            _flatten_llm_content(
                                chunk.get("content") if isinstance(chunk, dict) else chunk
                            )
                            if chunk
                            else ""
                        )
                        if content:
                            if not response_streaming_started:
                                await emit(LLMResponseStartEvent())
                                response_streaming_started = True
                            await emit(LLMResponseChunkEvent(content=content, is_complete=False))

        except Exception:
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
        """Emit the node-specific event(s) for a finished node.

        `already_streamed`: the agent's answer already went out token by token, so only the
        completion marker is sent.
        """
        if node_name == "intent_classifier":
            await emit(
                IntentClassificationEvent(
                    intent=output["intent"],
                    user_query=output.get("user_query", ""),
                    reasoning=output["reasoning"],
                    confidence=output.get("confidence") or output.get("intent_confidence"),
                )
            )
        elif node_name == "query_evaluator":
            await emit(
                QueryEvaluationEvent(
                    alpha=output.get("alpha", DEFAULT_ALPHA),
                    query_analysis=output.get("query_analysis", ""),
                    search_strategy=self._get_search_strategy(output.get("alpha", DEFAULT_ALPHA)),
                )
            )

        elif node_name == "summary":
            await emit(
                SummaryEvent(
                    summary_text=output.get("summary_text"),
                    message_count=output.get("message_count", 0),
                )
            )

        # The retriever emits its own search events from inside retriever_node.

        elif node_name == "reranker":
            # The full scored list, not just the top-K handed to the agent.
            documents = output.get("all_reranked_documents") or output.get(
                "retrieved_documents", []
            )
            if documents:
                reranked_docs = self._compute_reranked_documents(documents)
                reranking_changed_order = any(doc.rank_change != 0 for doc in reranked_docs)

                await emit(
                    RerankerResultEvent(
                        results=reranked_docs,
                        reranking_changed_order=reranking_changed_order,
                    )
                )

        elif node_name == "quality_gate":
            from core.config import QUALITY_GATE_THRESHOLD

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
            # Enrichment lifecycle events are published by the node as they happen (bridged in
            # _astream_graph); emitting them here would repeat the terminal event seconds late.
            for msg in output.get("messages", []):
                if not isinstance(msg, AIMessage) or not msg.content:
                    continue
                if already_streamed:
                    await emit(LLMResponseChunkEvent(content="", is_complete=True))
                else:
                    # Canned replies (clarify, summary, no-match, enrichment) are not streamed.
                    await emit(LLMResponseStartEvent())
                    await emit(
                        LLMResponseChunkEvent(content=_flatten_llm_content(msg), is_complete=True)
                    )

    def _compute_reranked_documents(self, documents: List) -> List:
        """RerankedDocument rows from documents already in reranked order, with rank changes vs `original_rank`."""
        reranked_docs = []

        for rank, doc in enumerate(documents, 1):
            original_rank = doc.metadata.get("original_rank", rank)
            snippet = (
                doc.page_content[:200] + "..." if len(doc.page_content) > 200 else doc.page_content
            )
            reranked_docs.append(
                RerankedDocument(
                    source=doc.metadata.get("source", "unknown"),
                    score=doc.metadata.get("reranker_score", 0.0),
                    rank=rank,
                    original_rank=original_rank,
                    snippet=snippet,
                    rank_change=rank - original_rank,
                    url=doc.metadata.get("url"),
                )
            )

        return reranked_docs

    def _get_search_strategy(self, alpha: float) -> str:
        """Bucket alpha: < 0.3 lexical-heavy, < 0.7 balanced, else semantic-heavy."""
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
            return f"alpha={output.get('alpha', DEFAULT_ALPHA):.2f}"
        elif node_name == "retriever":
            docs = output.get("retrieved_documents", [])
            return f"{len(docs)} documents retrieved"
        elif node_name == "reranker":
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
            return f"Intent → {output.get('intent')} ({output.get('reasoning')})"
        elif node_name == "summary":
            return f"{output.get('message_count', 0)} messages summarized"
        return ""

    async def cleanup(self):
        """Release the reranker model and database pools; call before shutdown."""
        if self._agent:
            try:
                await self._agent.close_async_pool()
                self._agent.cleanup()
                self._agent = None
            except Exception:
                logger.exception("Error during agent cleanup")
            finally:
                self._initialized = False
