"""
REST endpoints for managing conversations.
"""

import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import psycopg
from fastapi import APIRouter, HTTPException
from fastapi import Path as PathParam
from fastapi import Query, Request
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.middleware.origin_auth import verify_same_origin
from api.middleware.session_auth import verify_session
from config import DATABASE_URL, RATE_LIMIT_CONVERSATIONS
from logging_config import get_logger

# Thread ID validation pattern (alphanumeric, underscore, hyphen, 1-64 chars)
THREAD_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")


def validate_thread_id(thread_id: str) -> str:
    """
    Validate thread_id format to prevent injection attacks.

    Args:
        thread_id: The thread ID to validate

    Returns:
        The validated thread_id

    Raises:
        HTTPException: If thread_id is invalid
    """
    if not thread_id or not THREAD_ID_PATTERN.match(thread_id):
        raise HTTPException(
            status_code=400,
            detail="Invalid thread_id format. Must be 1-64 alphanumeric characters, underscores, or hyphens.",
        )
    return thread_id


logger = get_logger(__name__)

# Initialize limiter
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


# ============================================================================
# RESPONSE MODELS
# ============================================================================


class ConversationSummary(BaseModel):
    """Summary of a conversation for listing.

    Example:
        ```json
        {
            "thread_id": "conv_abc123",
            "title": "Laptop Shopping Help",
            "created_at": "2026-04-16T10:30:00",
            "updated_at": "2026-04-16T11:45:00"
        }
        ```
    """

    thread_id: str = Field(
        description="Unique conversation identifier (alphanumeric, underscore, hyphen, max 64 chars)"
    )
    title: str = Field(
        description="Auto-generated title based on first message (derived from thread_id if not set)"
    )
    created_at: datetime = Field(description="Conversation creation timestamp (ISO 8601)")
    updated_at: Optional[datetime] = Field(None, description="Last message timestamp (ISO 8601)")


class ObservabilitySnapshot(BaseModel):
    """Last observability state for a historical conversation, hydrated from
    the most recent LangGraph checkpoint's `channel_values`. Used by the
    frontend to repopulate the observability panel when a user clicks back
    into a past conversation without re-running the query (issue #22).
    """

    thread_id: str
    has_data: bool = Field(description="True when a checkpoint with observability fields was found")
    user_query: Optional[str] = None
    intent: Optional[str] = None
    intent_confidence: Optional[float] = None
    reasoning: Optional[str] = None
    alpha: Optional[float] = None
    query_analysis: Optional[str] = None
    reranker_max_score: Optional[float] = None
    quality_gate_retried: Optional[bool] = None
    quality_gate_reason: Optional[str] = None
    latency: dict = Field(default_factory=dict)


class ConversationDetail(BaseModel):
    """Full conversation details including messages.

    Example:
        ```json
        {
            "thread_id": "conv_abc123",
            "title": "Laptop Shopping Help",
            "created_at": "2026-04-16T10:30:00",
            "message_count": 5,
            "messages": [
                {
                    "type": "human",
                    "content": "What are good gaming laptops?"
                },
                {
                    "type": "ai",
                    "content": "Here are some great options..."
                }
            ]
        }
        ```
    """

    thread_id: str = Field(description="Conversation thread ID")
    title: str = Field(description="Conversation title")
    created_at: datetime = Field(description="Creation timestamp")
    message_count: int = Field(description="Total number of human + AI messages")
    messages: List[dict] = Field(
        description="Message history (human and AI messages only, tool messages filtered)"
    )


# ============================================================================
# ENDPOINTS
# ============================================================================


@router.get("/conversations", response_model=List[ConversationSummary])
@limiter.limit(RATE_LIMIT_CONVERSATIONS)
async def list_conversations(
    request: Request,
    limit: int = Query(
        default=20, ge=1, le=100, description="Maximum conversations to return (1-100)"
    ),
):
    """
    List all previous conversations with summaries.

    **Purpose:** Populate conversation sidebar/history in the UI.

    **Features:**
        - Sorted by most recent first (by updated_at or created_at)
        - Configurable limit (1-100, default 20)
        - Rate limited (default: 30 req/min per IP)
        - Same-origin required

    **Request:** `GET /api/conversations?limit=20`

    **Response:** 200 OK
        ```json
        [
            {
                "thread_id": "conversation_abc123",
                "title": "Wireless Earbuds Comparison",
                "created_at": "2026-04-16T10:30:00",
                "updated_at": "2026-04-16T11:45:00"
            },
            {
                "thread_id": "conversation_def456",
                "title": "Gaming Laptop Search",
                "created_at": "2026-04-15T14:20:00",
                "updated_at": "2026-04-15T15:10:00"
            }
        ]
        ```

    **Query Parameters:**
        - `limit` (int, 1-100, default 20): Max conversations to return

    **Errors:**
        - 401: Unauthorized (same-origin violation)
        - 429: Rate limited
        - 500: Database error

    Args:
        request: FastAPI request object (for auth and rate limiting)
        limit: Maximum number of conversations to return (1-100, default 20)

    Returns:
        List of conversation summaries ordered by most recent first.
    """
    await verify_same_origin(request)
    await verify_session(request)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT thread_id, title, created_at, updated_at
                    FROM conversation_metadata
                    ORDER BY COALESCE(updated_at, created_at) DESC
                    LIMIT %s
                """,
                    (limit,),
                )

                conversations = []
                for row in cur.fetchall():
                    conversations.append(
                        ConversationSummary(
                            thread_id=row[0],
                            title=row[1],
                            created_at=row[2],
                            updated_at=row[3],
                        )
                    )

                return conversations
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/conversations/{thread_id}", response_model=ConversationDetail)
@limiter.limit(RATE_LIMIT_CONVERSATIONS)
async def get_conversation(request: Request, thread_id: str):
    """
    Get full details of a specific conversation including message history.

    **Purpose:** Load a conversation for resuming or viewing in detail.

    **Features:**
        - Returns complete message history
        - Filters out tool/system messages (human + AI only)
        - Includes message count and metadata
        - Thread ID validation to prevent injection attacks

    **Request:** `GET /api/conversations/conversation_abc123`

    **Response:** 200 OK
        ```json
        {
            "thread_id": "conversation_abc123",
            "title": "Wireless Earbuds Comparison",
            "created_at": "2026-04-16T10:30:00",
            "message_count": 4,
            "messages": [
                {
                    "type": "human",
                    "content": "What wireless earbuds have the best noise cancellation?"
                },
                {
                    "type": "ai",
                    "content": "Here are some great options with ANC..."
                }
            ]
        }
        ```

    **Path Parameters:**
        - `thread_id` (str, 1-64 chars): Conversation ID (alphanumeric, underscore, hyphen)

    **Errors:**
        - 400: Invalid thread_id format
        - 404: Conversation not found
        - 429: Rate limited
        - 500: Database error

    Args:
        request: FastAPI request object (for auth and rate limiting)
        thread_id: The conversation thread ID (1-64 alphanumeric/underscore/hyphen)

    Returns:
        Full conversation details with message history.
    """
    await verify_same_origin(request)
    await verify_session(request)
    thread_id = validate_thread_id(thread_id)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                # Get metadata
                cur.execute(
                    """
                    SELECT title, created_at
                    FROM conversation_metadata
                    WHERE thread_id = %s
                """,
                    (thread_id,),
                )

                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                title, created_at = row

                # Get messages from checkpoint_blobs (LangGraph stores them as msgpack)
                # Get latest messages blob for this thread
                cur.execute(
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

                blob_row = cur.fetchone()
                messages = []

                if blob_row and blob_row[0]:
                    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

                    try:
                        blob, blob_type = blob_row
                        serializer = JsonPlusSerializer()
                        raw_messages = serializer.loads_typed((blob_type, blob))

                        for msg in raw_messages:
                            # LangChain message objects have type and content attributes
                            msg_type = getattr(msg, "type", None)
                            content = getattr(msg, "content", "")
                            # Skip tool messages and empty content
                            if content and msg_type in ("human", "ai"):
                                messages.append(
                                    {
                                        "type": msg_type,
                                        "content": content,
                                    }
                                )
                    except Exception as e:
                        logger.warning("message_decode_error", thread_id=thread_id, error=str(e))

                return ConversationDetail(
                    thread_id=thread_id,
                    title=title,
                    created_at=created_at,
                    message_count=len(messages),
                    messages=messages,
                )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.get("/conversations/{thread_id}/observability", response_model=ObservabilitySnapshot)
@limiter.limit(RATE_LIMIT_CONVERSATIONS)
async def get_conversation_observability(request: Request, thread_id: str):
    """Return the last observability snapshot for a conversation, hydrated from
    the most recent LangGraph checkpoint. See issue #22.

    The fields come from the checkpoint's `channel_values` JSONB which carries
    the scalar end-state of every pipeline node (intent, alpha, latencies,
    reranker score, quality-gate decision). Returns `has_data=False` when no
    checkpoint exists (e.g., conversation that was clarified but never ran a
    full retrieval).
    """
    await verify_same_origin(request)
    await verify_session(request)
    thread_id = validate_thread_id(thread_id)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT checkpoint -> 'channel_values'
                    FROM checkpoints
                    WHERE thread_id = %s
                    ORDER BY checkpoint_id DESC
                    LIMIT 1
                    """,
                    (thread_id,),
                )
                row = cur.fetchone()
                if not row or not row[0]:
                    return ObservabilitySnapshot(thread_id=thread_id, has_data=False)

                values = row[0]
                latency = {
                    k: values.get(k)
                    for k in (
                        "bm25_latency_ms",
                        "retriever_latency_ms",
                        "reranker_latency_ms",
                        "stock_bm25_latency_ms",
                        "judge_latency_ms",
                    )
                    if values.get(k) is not None
                }
                return ObservabilitySnapshot(
                    thread_id=thread_id,
                    has_data=True,
                    user_query=values.get("user_query"),
                    intent=values.get("intent"),
                    intent_confidence=values.get("intent_confidence"),
                    reasoning=values.get("reasoning"),
                    alpha=values.get("alpha"),
                    query_analysis=values.get("query_analysis"),
                    reranker_max_score=values.get("reranker_max_score"),
                    quality_gate_retried=values.get("quality_gate_retried"),
                    quality_gate_reason=values.get("quality_gate_reason"),
                    latency=latency,
                )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch observability for {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.delete("/conversations", status_code=204)
@limiter.limit(RATE_LIMIT_CONVERSATIONS)
async def clear_all_conversations(request: Request):
    """
    Delete all conversations and their history.

    **⚠️ WARNING: This is DESTRUCTIVE and cannot be undone.**

    **Purpose:** Clear all conversation history from the database.

    **Use cases:**
        - Clearing debug/test conversations
        - Privacy: remove all user data
        - System cleanup/reset

    **Request:** `DELETE /api/conversations`

    **Response:** 204 No Content (no body)

    **Behavior:**
        - Deletes all entries in conversation_metadata table
        - Deletes all LangGraph checkpoints
        - Deletes all checkpoint blobs (message history)
        - Atomic transaction (all-or-nothing)

    **Errors:**
        - 401: Unauthorized (same-origin violation)
        - 429: Rate limited
        - 500: Database error

    **Note:** This cannot be undone. Consider using `DELETE /api/conversations/{thread_id}` for selective deletion.

    Args:
        request: FastAPI request object (for auth and rate limiting)

    Returns:
        204 No Content on success.
    """
    await verify_same_origin(request)
    await verify_session(request)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Delete metadata
                cur.execute("DELETE FROM conversation_metadata")

                # Delete checkpoints
                cur.execute("DELETE FROM checkpoints")

                # Delete checkpoint blobs if they exist
                try:
                    cur.execute("DELETE FROM checkpoint_blobs")
                except psycopg.Error:
                    pass  # Table may not exist

                logger.info(f"Cleared all conversations")
    except Exception as e:
        logger.error(f"Failed to clear all conversations: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")


@router.delete("/conversations/{thread_id}", status_code=204)
@limiter.limit(RATE_LIMIT_CONVERSATIONS)
async def delete_conversation(request: Request, thread_id: str):
    """
    Delete a specific conversation and its history.

    Returns 204 No Content on success (RESTful standard for DELETE).

    **Purpose:** Remove a single conversation from history.

    **Features:**
        - Selective deletion (only specified conversation)
        - Removes metadata and all message history
        - Thread ID validation to prevent injection attacks
        - Atomic transaction

    **Request:** `DELETE /api/conversations/conversation_abc123`

    **Response:** 204 No Content (no body)

    **Behavior:**
        - Deletes conversation metadata entry
        - Deletes LangGraph checkpoints for this thread
        - Removes all message history

    **Path Parameters:**
        - `thread_id` (str, 1-64 chars): Conversation to delete (alphanumeric, underscore, hyphen)

    **Errors:**
        - 400: Invalid thread_id format
        - 404: Conversation not found
        - 429: Rate limited
        - 500: Database error

    **Note:** This cannot be undone. Ensure the user confirms before calling.

    Args:
        request: FastAPI request object (for auth and rate limiting)
        thread_id: The conversation thread ID to delete (1-64 alphanumeric/underscore/hyphen)

    Returns:
        204 No Content on success.
    """
    await verify_same_origin(request)
    await verify_session(request)
    thread_id = validate_thread_id(thread_id)

    try:
        with psycopg.connect(DATABASE_URL) as conn:
            conn.autocommit = True
            with conn.cursor() as cur:
                # Delete metadata
                cur.execute("DELETE FROM conversation_metadata WHERE thread_id = %s", (thread_id,))

                if cur.rowcount == 0:
                    raise HTTPException(status_code=404, detail="Conversation not found")

                # Delete checkpoints
                cur.execute("DELETE FROM checkpoints WHERE thread_id = %s", (thread_id,))

                logger.info(f"Conversation deleted: {thread_id}")
                # 204 No Content - no response body needed
                return None
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete conversation {thread_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Database error: {e}")
