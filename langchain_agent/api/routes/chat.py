"""
WebSocket endpoint for real-time chat with agent observability.
"""

import asyncio
import uuid
from typing import Dict

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.middleware.origin_auth import verify_websocket_origin
from api.schemas.events import AgentErrorEvent, BaseEvent, ConnectionEstablished
from core.logging_config import get_logger

logger = get_logger(__name__)

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

    async def connect(self, websocket: WebSocket, thread_id: str) -> None:
        """Accept the WebSocket and register it under its thread ID."""
        await websocket.accept()
        self.active_connections[thread_id] = websocket

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
            # process_task's finally has usually removed the entry already.
            self.running_tasks.pop(thread_id, None)

    async def emit_event(self, thread_id: str, event: BaseEvent):
        """
        Send an event to a specific connection.

        Args:
            thread_id: Target connection's thread ID
            event: Event to send
        """
        if thread_id not in self.active_connections:
            # This used to fail silently -- a caller passing a thread_id that
            # doesn't match the one the connection was registered under (see
            # `connect()`) previously dropped every event with no signal at
            # all, which once produced a WebSocket that looked "hung" from
            # the client's perspective even though the server had completed
            # and "successfully emitted" every event into the void.
            logger.warning(
                "emit_event_unknown_thread_id",
                thread_id=thread_id,
                event_type=type(event).__name__,
            )
            return
        websocket = self.active_connections[thread_id]
        try:
            await websocket.send_json(event.model_dump(mode="json"))
        except (WebSocketDisconnect, RuntimeError, ValueError) as e:
            logger.error("websocket_send_error", thread_id=thread_id, error=str(e))
        except Exception as e:
            logger.error("unexpected_websocket_send_error", thread_id=thread_id, error=str(e))

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
# WEBSOCKET ENDPOINT
# ============================================================================


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    WebSocket endpoint for real-time chat with streaming observability.

    This is the primary endpoint for client-server communication. Supports:
    - Real-time message streaming with token-by-token output
    - Observability events showing pipeline execution (retrieval, reranking, etc.)
    - Conversation resumption by thread_id (backend capability; the current UI runs one
      conversation at a time per the projector-demo revamp, #104)

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
          If not provided, server generates `conversation_{uuid}`.

    **Client Message Format (JSON):**
        ```json
        {
            "type": "chat_message",
            "message": "Show me tan boots",
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
        - `OpenSearchQueryEvent` — Detailed query (DSL, alpha, intent)
        - `RerankerProgressEvent` — Documents being reranked
        - `QualityGateEvent` — Quality validation results
        - `QueryExpansionEvent` — Vague query expansion with context
        - `LLMResponseChunkEvent` — Token-by-token output streaming
        - `AgentCompleteEvent` — Execution finished with response and citations
        - `PipelineSummaryEvent` — End-of-pipeline scorecard (per-stage latency,
          confidence proxy, LLM-as-judge generation row with categorical
          hallucination flags)
        - `AgentErrorEvent` — Error occurred

    **Authentication:**
        Same-origin only — the Origin header must be on the allow-list of
        localhost ports.

    **Error Handling:**
        - Processing errors → sends AgentErrorEvent with error message
    """
    # Verify same-origin authentication before accepting connection
    if not await verify_websocket_origin(websocket):
        return  # Connection closed by verify function

    # Get or generate thread ID
    thread_id = websocket.query_params.get("thread_id")
    if not thread_id:
        thread_id = f"conversation_{uuid.uuid4().hex[:8]}"

    # Accept connection
    await manager.connect(websocket, thread_id)

    await manager.emit_event(thread_id, ConnectionEstablished(thread_id=thread_id))

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
                        )
                    except asyncio.CancelledError:
                        # The client already reset its own state when it sent the stop;
                        # an agent_error here would mark the live socket as disconnected.
                        logger.info("agent_task_cancelled", thread_id=msg_thread_id)
                    except Exception as e:
                        logger.error(
                            "agent_processing_error", thread_id=msg_thread_id, error=str(e)
                        )
                        await manager.emit_event(msg_thread_id, AgentErrorEvent(error=str(e)))
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
