"""
WebSocket endpoint for real-time chat with agent observability.
"""

import asyncio
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError, field_validator
from slowapi import Limiter
from slowapi.util import get_remote_address

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.middleware.origin_auth import verify_same_origin, verify_websocket_origin
from api.middleware.session_auth import verify_session, verify_websocket_session
from api.schemas.events import (
    AgentCompleteEvent,
    AgentErrorEvent,
    BaseEvent,
    ConnectionEstablished,
)
from config import RATE_LIMIT_CHAT
from logging_config import get_logger

logger = get_logger(__name__)

# Thread ID pattern: starts with letter, alphanumeric with underscores/hyphens, max 64 chars
THREAD_ID_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]{0,63}$")

# Initialize limiter (will use app.state.limiter)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


# ============================================================================
# CONNECTION MANAGER
# ============================================================================


class ConnectionManager:
    """Manages WebSocket connections and message routing."""

    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
        self.running_tasks: Dict[str, asyncio.Task] = {}  # Track running agent tasks
        self._agent_service = None  # Lazy initialization

    @property
    def agent_service(self):
        """Lazy load agent service to avoid slow startup."""
        if self._agent_service is None:
            from api.services.observable_agent import ObservableAgentService

            self._agent_service = ObservableAgentService()
        return self._agent_service

    async def connect(self, websocket: WebSocket, thread_id: str) -> bool:
        """
        Accept WebSocket connection and register it.

        Args:
            websocket: The WebSocket connection
            thread_id: Conversation thread ID

        Returns:
            True if connection successful
        """
        await websocket.accept()
        self.active_connections[thread_id] = websocket
        return True

    async def disconnect(self, thread_id: str):
        """Remove connection from active connections and cancel any running task."""
        if thread_id in self.active_connections:
            del self.active_connections[thread_id]
        # Cancel running task if any
        if thread_id in self.running_tasks:
            task = self.running_tasks[thread_id]
            if not task.done():
                task.cancel()
            del self.running_tasks[thread_id]

    def register_task(self, thread_id: str, task: asyncio.Task):
        """Register a running agent task for a thread."""
        self.running_tasks[thread_id] = task

    async def cancel_task(self, thread_id: str):
        """Cancel the running task for a thread."""
        if thread_id in self.running_tasks:
            task = self.running_tasks[thread_id]
            if not task.done():
                logger.info("cancelling_agent_task", thread_id=thread_id)
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass  # Expected
            del self.running_tasks[thread_id]

    async def emit_event(self, thread_id: str, event: BaseEvent):
        """
        Send an event to a specific connection.

        Args:
            thread_id: Target connection's thread ID
            event: Event to send
        """
        if thread_id in self.active_connections:
            websocket = self.active_connections[thread_id]
            try:
                await websocket.send_json(event.model_dump(mode="json"))
            except (WebSocketDisconnect, RuntimeError, ValueError) as e:
                logger.error("websocket_send_error", thread_id=thread_id, error=str(e))
            except Exception as e:
                logger.error("unexpected_websocket_send_error", thread_id=thread_id, error=str(e))

    def get_connection_count(self) -> int:
        """Return number of active connections."""
        return len(self.active_connections)

    async def shutdown(self):
        """
        Shutdown the connection manager and clean up resources.

        This should be called during application shutdown to properly
        release memory held by the agent service, including models and
        database connections.
        """
        # Close all active connections
        for thread_id in list(self.active_connections.keys()):
            try:
                websocket = self.active_connections[thread_id]
                await websocket.close()
            except (WebSocketDisconnect, RuntimeError):
                pass  # Connection already closed or in invalid state
            except Exception as e:
                logger.error("unexpected_websocket_close_error", thread_id=thread_id, error=str(e))
        self.active_connections.clear()

        # Cleanup agent service if initialized
        if self._agent_service is not None:
            try:
                await self._agent_service.cleanup()
                self._agent_service = None
            except (RuntimeError, TimeoutError, ConnectionError) as e:
                logger.warning("agent_service_cleanup_error", error=str(e))
            except Exception as e:
                logger.error("unexpected_agent_service_cleanup_error", error=str(e))


# Global connection manager instance
manager = ConnectionManager()


# ============================================================================
# REQUEST MODELS
# ============================================================================


class ChatMessage(BaseModel):
    """Incoming chat message from client with validation.

    Example:
        ```json
        {
            "type": "chat_message",
            "message": "Show me wireless headphones with active noise cancellation under $200",
            "thread_id": "conv_abc123"
        }
        ```
    """

    type: str = "chat_message"
    message: str = Field(
        ...,
        min_length=1,
        max_length=4000,
        description="User query or statement (1-4000 characters). Can be a product search, comparison, attribute filter, or follow-up question.",
    )
    thread_id: Optional[str] = Field(
        None,
        description="Conversation thread ID for resuming conversations. Format: alphanumeric, underscore, hyphen, max 64 chars. Auto-generated if omitted.",
    )
    optimizations: Optional[Dict[str, bool]] = Field(
        None,
        description=(
            "Per-feature search optimization toggles. Nine recognized keys: "
            "hybrid, fuzzy, synonyms, phonetic, phrase_boost, field_boost, typeahead, "
            "reranking, llm. Missing keys default to true (enabled). Skipped stages "
            "are collapsed out of the observability panel and the Pipeline Quality "
            "Summary's per-stage metrics."
        ),
    )

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not THREAD_ID_PATTERN.match(v):
            raise ValueError(
                "thread_id must start with a letter and contain only "
                "alphanumeric characters, underscores, or hyphens (max 64 chars)"
            )
        return v

    @field_validator("message")
    @classmethod
    def validate_message_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty or whitespace only")
        return v


# ============================================================================
# WEBSOCKET ENDPOINT
# ============================================================================


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat with streaming observability.

    This is the primary endpoint for client-server communication. Supports:
    - Real-time message streaming with token-by-token output
    - Observability events showing pipeline execution (retrieval, reranking, etc.)
    - Multiple parallel conversations via thread_id
    - Conversation resumption by thread_id

    **Connection Flow:**
        1. Client connects via WebSocket (same-origin required)
        2. Server verifies authentication via Origin header
        3. Server sends ConnectionEstablished event with thread_id
        4. Client sends chat_message events in a loop
        5. Server streams observability events as agent processes
        6. Server sends AgentCompleteEvent or AgentErrorEvent when done
        7. Client can request stop_execution to cancel in-flight processing

    **Query Parameters:**
        - `thread_id` (optional, str): Conversation thread ID for resuming conversations.
          Format: alphanumeric, underscore, hyphen, max 64 chars.
          If not provided, server generates `conversation_{uuid}`.

    **Client Message Format (JSON):**
        ```json
        {
            "type": "chat_message",
            "message": "What wireless earbuds have the best noise cancellation?",
            "thread_id": "conv_abc123"
        }
        ```
        or to stop execution:
        ```json
        {
            "type": "stop_execution",
            "thread_id": "conv_abc123"
        }
        ```

    **Server Event Types** (see api/schemas/events.py):
        - `ConnectionEstablished` — Initial connection confirmation with thread_id
        - `SearchProgressEvent` — Search initiated
        - `OpenSearchQueryEvent` — Detailed query (DSL, alpha, intent, optimization toggles)
        - `RerankerProgressEvent` — Documents being reranked
        - `QualityGateEvent` — Quality validation results
        - `QueryExpansionEvent` — Vague query expansion with context
        - `LLMResponseChunkEvent` — Token-by-token output streaming
        - `AgentCompleteEvent` — Execution finished with response and citations
        - `PipelineSummaryEvent` — End-of-pipeline quality scorecard
          (BM25 / Hybrid / Reranked NDCG@10, MRR, Recall@20, Precision@10
          when ESCI judgments exist; confidence proxy otherwise; LLM-as-judge
          generation row with categorical hallucination flags when enabled)
        - `AgentErrorEvent` — Error occurred (recoverable or fatal)
        - `ClarificationRequestedEvent` — Intent classification too uncertain
        - `ClarificationResolvedEvent` — User provided clarification

    **Authentication:**
        Two layers, both enforced before the WebSocket is accepted:
        1. **Same-origin** — Origin header must match the deployed app
           (allow-list of localhost dev ports + Cloud Run `*.run.app`).
        2. **Shared-password session cookie** (`ahs_session`) — set by
           ``POST /api/auth/login``; verified by ``verify_websocket_session``.
           Rejection closes the socket with code **4401** so the SPA can
           route back to the login screen.

    **Error Handling:**
        - Invalid thread_id format → disconnects with error
        - Processing errors → sends AgentErrorEvent with error message
        - Network errors → logs and attempts graceful reconnection
    """
    # Verify same-origin authentication before accepting connection
    if not await verify_websocket_origin(websocket):
        return  # Connection closed by verify function

    # Verify the session cookie carries an authenticated login. Closes with
    # 4401 on failure so the SPA can route back to the login screen.
    if not await verify_websocket_session(websocket):
        return

    # Get or generate thread ID
    thread_id = websocket.query_params.get("thread_id")
    if not thread_id:
        thread_id = f"conversation_{uuid.uuid4().hex[:8]}"

    # Accept connection
    await manager.connect(websocket, thread_id)

    # Load existing message count from checkpoint
    existing_count = 0
    try:
        pool = (
            manager.agent_service._agent.async_pool
            if manager.agent_service and manager.agent_service._agent
            else None
        )

        if pool:
            async with pool.connection() as conn:
                async with conn.cursor() as cur:
                    # Query checkpoint_blobs for existing messages
                    await cur.execute(
                        """
                        SELECT blob, type
                        FROM checkpoint_blobs
                        WHERE thread_id = %s
                          AND channel = 'messages'
                        ORDER BY version DESC
                        LIMIT 1
                    """,
                        (thread_id,),
                    )

                    blob_row = await cur.fetchone()

                    if blob_row and blob_row[0]:
                        from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

                        blob, blob_type = blob_row
                        serializer = JsonPlusSerializer()
                        raw_messages = serializer.loads_typed((blob_type, blob))

                        # Count human and AI messages with content
                        existing_count = sum(
                            1
                            for msg in raw_messages
                            if hasattr(msg, "type")
                            and msg.type in ("human", "ai")
                            and hasattr(msg, "content")
                            and msg.content
                        )
    except Exception as e:
        logger.warning("message_count_load_error", thread_id=thread_id, error=str(e))

    # Send connection established event
    await manager.emit_event(
        thread_id,
        ConnectionEstablished(
            thread_id=thread_id,
            existing_messages=existing_count,
        ),
    )

    try:
        # Ensure agent service is initialized
        logger.info("initializing_agent_service", thread_id=thread_id)
        await manager.agent_service.ensure_initialized()
        logger.info("agent_service_initialized", thread_id=thread_id)

        while True:
            # Wait for client message
            data = await websocket.receive_json()

            if data.get("type") == "stop_execution":
                # Handle stop request
                stop_thread_id = data.get("thread_id", thread_id)
                logger.info("stop_execution_requested", thread_id=stop_thread_id)
                await manager.cancel_task(stop_thread_id)
                continue

            if data.get("type") == "chat_message":
                message = data.get("message", "").strip()
                msg_thread_id = data.get("thread_id", thread_id)
                # Validate the per-message optimization toggles. We accept only
                # the known allowlist of keys so a hostile client can't inflate
                # checkpoint state with arbitrary JSON. Unknown keys are dropped
                # silently. Mirror this list in optimizationsStore.ts.
                _ALLOWED_OPTIMIZATIONS = frozenset(
                    {
                        "hybrid",
                        "fuzzy",
                        "synonyms",
                        "phonetic",
                        "phrase_boost",
                        "field_boost",
                        "typeahead",
                        "reranking",
                        "llm",
                        "llm_judge",
                    }
                )
                raw_optimizations = data.get("optimizations")
                msg_optimizations: Optional[Dict[str, bool]] = None
                if isinstance(raw_optimizations, dict):
                    msg_optimizations = {
                        k: bool(v)
                        for k, v in raw_optimizations.items()
                        if isinstance(k, str) and k in _ALLOWED_OPTIMIZATIONS
                    }

                if not message:
                    continue

                # Create emit callback for this request
                async def emit_callback(event: BaseEvent):
                    await manager.emit_event(msg_thread_id, event)

                # Create and register the processing task
                async def process_task():
                    try:
                        await manager.agent_service.process_message(
                            message=message,
                            thread_id=msg_thread_id,
                            emit=emit_callback,
                            optimizations=msg_optimizations,
                        )
                    except asyncio.CancelledError:
                        logger.info("agent_task_cancelled", thread_id=msg_thread_id)
                        # Notify client that execution was cancelled
                        await manager.emit_event(
                            msg_thread_id,
                            AgentErrorEvent(
                                error="Execution stopped by user",
                                recoverable=True,
                            ),
                        )
                    except Exception as e:
                        logger.error(
                            "agent_processing_error", thread_id=msg_thread_id, error=str(e)
                        )
                        await manager.emit_event(
                            msg_thread_id,
                            AgentErrorEvent(
                                error=str(e),
                                recoverable=True,
                            ),
                        )
                    finally:
                        # Clean up the task reference
                        if msg_thread_id in manager.running_tasks:
                            del manager.running_tasks[msg_thread_id]

                # Create task and register it
                task = asyncio.create_task(process_task())
                manager.register_task(msg_thread_id, task)

    except WebSocketDisconnect:
        logger.info("websocket_disconnected", thread_id=thread_id)
    except Exception as e:
        import traceback

        logger.error(
            "websocket_error", thread_id=thread_id, error=str(e), traceback=traceback.format_exc()
        )
    finally:
        # Always cleanup connection and cancel any running tasks
        logger.info("websocket_cleanup", thread_id=thread_id)
        await manager.disconnect(thread_id)


# ============================================================================
# REST FALLBACK (for testing without WebSocket)
# ============================================================================


class ChatRequest(BaseModel):
    """REST chat request (non-streaming fallback) with validation."""

    message: str = Field(
        ..., min_length=1, max_length=4000, description="User message content (1-4000 characters)"
    )
    thread_id: Optional[str] = Field(None, description="Conversation thread ID (optional)")

    @field_validator("thread_id")
    @classmethod
    def validate_thread_id(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not THREAD_ID_PATTERN.match(v):
            raise ValueError(
                "thread_id must start with a letter and contain only "
                "alphanumeric characters, underscores, or hyphens (max 64 chars)"
            )
        return v

    @field_validator("message")
    @classmethod
    def validate_message_content(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message cannot be empty or whitespace only")
        return v


class Citation(BaseModel):
    """Citation source for a response.

    Example:
        ```json
        {
            "label": "Sony WH-1000XM5 Headphones",
            "url": "https://www.amazon.com/s?k=Sony+WH-1000XM5+Headphones"
        }
        ```
    """

    label: str = Field(description="Product name or title")
    url: str = Field(description="Product URL (Amazon search by title for ESCI products)")


class ChatResponse(BaseModel):
    """REST chat response (non-streaming fallback).

    Returns the final response text, citations, and execution timing.
    For real-time streaming, use the WebSocket endpoint instead.

    Example:
        ```json
        {
            "thread_id": "conversation_abc123",
            "response": "Here are some great wireless earbuds...",
            "duration_ms": 2450.5,
            "citations": [
                {
                    "label": "Sony WH-1000XM5",
                    "url": "https://www.amazon.com/s?k=Sony+WH-1000XM5"
                }
            ]
        }
        ```
    """

    thread_id: str = Field(description="Conversation thread ID (for resuming conversations)")
    response: str = Field(
        description="Agent's response text with product information and recommendations"
    )
    duration_ms: float = Field(description="Total execution time in milliseconds")
    citations: List[Citation] = Field(
        default=[], description="Product sources with labels and URLs"
    )


@router.post("/api/chat", response_model=ChatResponse)
@limiter.limit(RATE_LIMIT_CHAT)
async def chat_rest(request: Request, chat_request: ChatRequest):
    """
    REST endpoint for chat (non-streaming fallback).

    **Use this endpoint for:**
        - Testing without WebSocket support
        - Simple synchronous requests
        - Integrations that don't support WebSocket

    **For real-time streaming and observability, use `/ws/chat` (WebSocket) instead.**

    **Features:**
        - Synchronous request-response pattern
        - Final response + citations returned in one response
        - Conversation resumption via thread_id
        - Rate limited (default: 10 req/min per IP)

    **Authentication:**
        - Same-origin required (enforced via Origin header)
        - Shared-password session cookie (`ahs_session`, set by
          ``POST /api/auth/login``); 401 on missing/expired session

    **Request:** `POST /api/chat`
        ```json
        {
            "message": "What are the best gaming laptops under $1500?",
            "thread_id": "conv_my_session"
        }
        ```

    **Response:** 200 OK
        ```json
        {
            "thread_id": "conv_my_session",
            "response": "Here are some excellent gaming laptops...",
            "duration_ms": 2450.5,
            "citations": [...]
        }
        ```

    **Errors:**
        - 400: Invalid request (empty message, invalid thread_id format)
        - 429: Rate limited (too many requests)
        - 500: Internal server error

    Args:
        request: FastAPI request object (for auth and rate limiting)
        chat_request: Chat request with message and optional thread_id

    Returns:
        Chat response with agent's answer and citations.
    """
    # Verify same-origin authentication
    await verify_same_origin(request)
    await verify_session(request)

    thread_id = chat_request.thread_id or f"conversation_{uuid.uuid4().hex[:8]}"

    start_time = datetime.now(timezone.utc)

    # Collect events (we won't stream them in REST mode)
    events = []

    async def collect_event(event: BaseEvent):
        events.append(event)

    await manager.agent_service.ensure_initialized()

    try:
        final_response = await manager.agent_service.process_message(
            message=chat_request.message,
            thread_id=thread_id,
            emit=collect_event,
        )

        duration_ms = (datetime.now(timezone.utc) - start_time).total_seconds() * 1000

        # Extract citations from the agent complete event
        citations: List[Citation] = []
        for event in events:
            if isinstance(event, AgentCompleteEvent) and event.citations:
                citations = [
                    Citation(label=c.get("label", ""), url=c.get("url", ""))
                    for c in event.citations
                    if c.get("url")  # Only include citations with URLs
                ]
                break

        return ChatResponse(
            thread_id=thread_id,
            response=final_response or "No response generated",
            duration_ms=duration_ms,
            citations=citations,
        )
    except Exception as e:
        raise Exception(f"Agent error: {e}")
