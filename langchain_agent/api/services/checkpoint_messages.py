"""Counts the human/AI messages already checkpointed for a thread_id, read from
LangGraph's checkpoint_blobs table (used by ObservableAgentService)."""

from typing import Any, Optional


async def fetch_latest_messages_blob(pool: Any, thread_id: str) -> Optional[tuple]:
    """Return the latest ``(blob, blob_type)`` for the 'messages' checkpoint
    channel, or None if there isn't one."""
    async with pool.connection() as conn:
        async with conn.cursor() as cur:
            await cur.execute(
                """
                SELECT blob, type
                FROM checkpoint_blobs
                WHERE thread_id = %s AND channel = 'messages'
                ORDER BY version DESC
                LIMIT 1
                """,
                (thread_id,),
            )
            return await cur.fetchone()


def count_conversation_messages(raw_messages: list) -> int:
    """Count human/AI messages with non-empty content in a deserialized message list."""
    return sum(
        1
        for msg in raw_messages
        if hasattr(msg, "type") and msg.type in ("human", "ai") and getattr(msg, "content", None)
    )


async def load_message_count(pool: Any, thread_id: str) -> int:
    """Fetch, deserialize, and count existing messages for a thread. Raises
    on a DB or deserialization error -- callers decide how to handle that
    (e.g. log-and-default-to-0)."""
    blob_row = await fetch_latest_messages_blob(pool, thread_id)
    if not blob_row or not blob_row[0]:
        return 0

    from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

    blob, blob_type = blob_row
    raw_messages = JsonPlusSerializer().loads_typed((blob_type, blob))
    return count_conversation_messages(raw_messages)
