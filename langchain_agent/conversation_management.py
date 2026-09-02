"""Conversation & checkpoint management for EcommerceSearchAgent (split out of
main.py in #47): metadata table, listing/clearing threads, title generation,
summarization and compaction.
"""

import json
import logging
from typing import List, Optional, Sequence, Tuple

import httpx
import psycopg
from langchain_core.messages import BaseMessage, SystemMessage

from config import (
    COMPACTION_THRESHOLD_PCT,
    DATABASE_URL,
    ENABLE_COMPACTION,
    MAX_CONTEXT_TOKENS,
    MESSAGES_TO_KEEP_FULL,
    MIN_MESSAGES_FOR_COMPACTION,
    TOKEN_CHAR_RATIO,
)
from llm_content import _flatten_llm_content

logger = logging.getLogger(__name__)


class ConversationManagementMixin:
    """Conversation/checkpoint methods for EcommerceSearchAgent (see module docstring)."""

    def _ensure_metadata_table(self):
        """Ensure the conversation_metadata table exists.

        Creates the conversation_metadata table if it doesn't already exist.
        This table stores conversation titles and timestamps for the conversation list.

        Raises:
            Does not raise exceptions - logs warnings if table creation fails.
        """
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        CREATE TABLE IF NOT EXISTS conversation_metadata (
                            thread_id TEXT PRIMARY KEY,
                            title TEXT NOT NULL,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Could not create conversation_metadata table: {e}")
        except Exception as e:
            logger.error(f"Unexpected error creating conversation_metadata table: {e}")

    def list_conversations(self):
        """List available previous conversations from PostgreSQL with titles"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Query the metadata table for conversations with titles
                    cur.execute("""
                        SELECT thread_id, title, created_at
                        FROM conversation_metadata
                        ORDER BY created_at DESC
                        LIMIT 20
                    """)
                    conversations = cur.fetchall()
                    return conversations
        except Exception as e:
            print(f"Error listing conversations: {e}")
            return []

    def clear_all_conversations(self):
        """Clear all previous conversations from the database"""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                conn.autocommit = True
                with conn.cursor() as cur:
                    # Delete all conversation metadata
                    cur.execute("DELETE FROM conversation_metadata")
                    metadata_count = cur.rowcount

                    # Delete all checkpoints (conversation history)
                    cur.execute("DELETE FROM checkpoints")
                    checkpoint_count = cur.rowcount

                    # Delete checkpoint blobs if they exist
                    try:
                        cur.execute("DELETE FROM checkpoint_blobs")
                    except psycopg.Error:
                        pass  # Table may not exist, which is acceptable

                    return metadata_count, checkpoint_count
        except Exception as e:
            print(f"Error clearing conversations: {e}")
            return 0, 0

    def generate_conversation_title(self, messages: List[BaseMessage]) -> str:
        """Use the LLM to generate a concise title for the conversation.

        Analyzes the conversation messages and generates a descriptive title
        that captures the main topic being discussed.

        Args:
            messages: List of conversation messages to analyze.

        Returns:
            A concise title (max 50 characters). Returns a default title if
            generation fails or no suitable messages are found.

        Raises:
            Does not raise exceptions - returns fallback titles on error.
        """
        try:
            # Build a summary of the conversation for title generation
            conversation_summary = []
            for msg in messages[-6:]:  # Use last 6 messages for context
                if hasattr(msg, "content") and msg.content:
                    # Safely get message type
                    role = "User" if hasattr(msg, "type") and msg.type == "human" else "Assistant"
                    content = str(msg.content)[:200]  # Truncate long messages
                    conversation_summary.append(f"{role}: {content}")

            if not conversation_summary:
                return "New Conversation"

            prompt = f"""Generate a very short title (max 50 chars) for this conversation.
The title should capture the main topic or question being discussed.
Return ONLY the title, nothing else.

Conversation:
{chr(10).join(conversation_summary)}

Title:"""

            response = self.llm.invoke(prompt)
            title = _flatten_llm_content(response).strip().strip("\"'")[:50]
            return title if title else "Untitled Conversation"
        except Exception as e:
            logger.debug(f"Title generation failed, using fallback: {e}")
            # Fallback: use first user message
            for msg in messages:
                if (
                    hasattr(msg, "type")
                    and msg.type == "human"
                    and hasattr(msg, "content")
                    and msg.content
                ):
                    return str(msg.content)[:50].strip()
            return "Untitled Conversation"

    def update_conversation_title(self, thread_id: Optional[str] = None):
        """Generate and save a title for the current conversation based on its content.

        Retrieves the current conversation messages from the checkpoint, generates
        a descriptive title using the LLM, and stores it in the conversation_metadata table.

        This method is called after each agent response to keep the title up-to-date
        with the conversation content.

        Args:
            thread_id: Conversation to title. Defaults to ``self.thread_id`` for the
                CLI path. The API path (background title generation in
                ``ObservableAgentService``) must pass this explicitly -- ``self`` is a
                single shared agent instance and ``self.thread_id`` may already belong
                to a different concurrent request by the time this runs.

        Raises:
            Does not raise exceptions - logs warnings if title update fails.
        """
        thread_id = thread_id or self.thread_id
        try:
            # Get current conversation messages from checkpoint
            checkpoint = self.checkpointer.get({"configurable": {"thread_id": thread_id}})
            if not checkpoint:
                logger.debug("No checkpoint found for title update")
                return

            # Access messages from channel_values (checkpoint is a dict)
            channel_values = checkpoint.get("channel_values", {})
            messages = channel_values.get("messages", [])
            if not messages:
                logger.debug("No messages in checkpoint for title update")
                return

            # Generate title from conversation
            title = self.generate_conversation_title(messages)

            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Insert or update conversation metadata with new title
                    cur.execute(
                        """
                        INSERT INTO conversation_metadata (thread_id, title)
                        VALUES (%s, %s)
                        ON CONFLICT (thread_id)
                        DO UPDATE SET title = EXCLUDED.title, updated_at = CURRENT_TIMESTAMP
                    """,
                        (thread_id, title),
                    )
                conn.commit()
        except psycopg.Error as e:
            logger.warning(f"Database error updating conversation title: {e}")
        except Exception as e:
            logger.error(f"Unexpected error updating conversation title: {e}")

    def estimate_token_count(self, messages: Sequence[BaseMessage]) -> int:
        """
        Estimate token count for a list of messages.
        Uses 1 token ≈ 4 characters heuristic (conservative for English).

        Args:
            messages: Sequence of BaseMessage objects to estimate token count for.

        Returns:
            Estimated token count based on character length.
        """
        try:
            total_chars = 0
            for msg in messages:
                if hasattr(msg, "content") and msg.content:
                    total_chars += len(str(msg.content))
            return total_chars // TOKEN_CHAR_RATIO
        except Exception:
            return 0

    def _fallback_summarize(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Create a simple fallback summary when LLM summarization fails.
        Uses basic heuristics to extract key information without LLM.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A simple summary of the conversation.
        """
        if not messages_to_summarize:
            return "No earlier context"

        # Extract user questions and assistant topics
        user_topics = []
        assistant_topics = []

        for msg in messages_to_summarize:
            if hasattr(msg, "content") and msg.content:
                content_preview = str(msg.content)[:100].strip()
                if hasattr(msg, "type"):
                    if msg.type == "human":
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)
                else:
                    if "human" in str(type(msg)).lower():
                        user_topics.append(content_preview)
                    else:
                        assistant_topics.append(content_preview)

        # Build simple summary
        summary_parts = [f"Earlier conversation ({len(messages_to_summarize)} messages):"]

        if user_topics:
            summary_parts.append(f"User asked about: {', '.join(user_topics[:3])}")
            if len(user_topics) > 3:
                summary_parts.append(f"(and {len(user_topics) - 3} more topics)")

        if assistant_topics:
            summary_parts.append(f"Assistant discussed: {', '.join(assistant_topics[:3])}")
            if len(assistant_topics) > 3:
                summary_parts.append(f"(and {len(assistant_topics) - 3} more topics)")

        return ". ".join(summary_parts)

    def summarize_messages(self, messages_to_summarize: Sequence[BaseMessage]) -> str:
        """
        Use LLM to create a concise summary of older messages.
        Preserves key facts and context while being brief.
        Falls back to simple summaries if LLM fails.

        Args:
            messages_to_summarize: Sequence of messages to summarize.

        Returns:
            A concise summary of the message content.
        """
        if not messages_to_summarize:
            return "No earlier context"

        try:
            # Build context of messages to summarize
            context = ""
            for msg in messages_to_summarize:
                if hasattr(msg, "content") and msg.content:
                    # Determine role from message type
                    if hasattr(msg, "type"):
                        role = "User" if msg.type == "human" else "Assistant"
                    else:
                        role = "Assistant" if "assistant" in str(type(msg)).lower() else "User"
                    context += f"{role}: {msg.content}\n\n"

            if not context.strip():
                return "No earlier context"

            # Prompt LLM to summarize
            summary_prompt = f"""Summarize the following conversation concisely in 1-2 paragraphs, preserving key facts and context.
Focus on what the user asked, what the assistant already provided, and whether any next steps remain.
Mention any uncertainties or missing pieces so the user knows what's incomplete.

Conversation:
{context}

Summary:"""

            # Invoke LLM for summary (direct, not through agent). Gemini may
            # return content as a list of content blocks; flatten so the
            # SummaryEvent's `summary_text: str` field accepts it.
            response = self.llm.invoke(summary_prompt)
            return _flatten_llm_content(response)

        except httpx.ConnectError as e:
            logger.error(
                f"Connection error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to simple concatenation summary")
            return self._fallback_summarize(messages_to_summarize)

        except (json.JSONDecodeError, ValueError) as e:
            logger.error(
                f"JSON/parsing error while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to word count summary")
            return self._fallback_summarize(messages_to_summarize)

        except TimeoutError as e:
            logger.error(
                f"Timeout while summarizing {len(messages_to_summarize)} messages: {e}",
                exc_info=True,
            )
            logger.info("Falling back to first/last message summary")
            # Get first and last messages
            first_msg = ""
            last_msg = ""
            if messages_to_summarize:
                if hasattr(messages_to_summarize[0], "content"):
                    first_msg = str(messages_to_summarize[0].content)[:80]
                if hasattr(messages_to_summarize[-1], "content"):
                    last_msg = str(messages_to_summarize[-1].content)[:80]
            summary = f"Earlier conversation ({len(messages_to_summarize)} messages): "
            if first_msg:
                summary += f"Started with: {first_msg}. "
            if last_msg:
                summary += f"Ended with: {last_msg}"
            return summary

        except Exception as e:
            logger.error(
                f"Unexpected error while summarizing {len(messages_to_summarize)} messages: {type(e).__name__}: {e}",
                exc_info=True,
            )
            logger.info("Falling back to basic summary")
            return self._fallback_summarize(messages_to_summarize)

    def compact_conversation_if_needed(
        self, messages: Sequence[BaseMessage]
    ) -> Tuple[Sequence[BaseMessage], bool, int]:
        """
        Check if conversation needs compaction and compact if necessary.

        Args:
            messages: Sequence of messages to check for compaction.

        Returns:
            Tuple of (compacted_messages, was_compacted, num_compacted) where:
            - compacted_messages: The potentially compacted message sequence
            - was_compacted: Boolean indicating if compaction occurred
            - num_compacted: Number of messages that were compacted
        """
        if not ENABLE_COMPACTION or not messages:
            return messages, False, 0

        if len(messages) < MIN_MESSAGES_FOR_COMPACTION:
            return messages, False, 0

        # Estimate token count
        token_count = self.estimate_token_count(messages)
        threshold = int(MAX_CONTEXT_TOKENS * COMPACTION_THRESHOLD_PCT)

        if token_count < threshold:
            return messages, False, 0  # No compaction needed

        # Perform compaction
        messages_to_keep = messages[-MESSAGES_TO_KEEP_FULL:]
        messages_to_compact = messages[:-MESSAGES_TO_KEEP_FULL]

        # Generate summary
        summary_text = self.summarize_messages(messages_to_compact)

        # Create summary message
        summary_msg = SystemMessage(content=f"[Earlier conversation summary]: {summary_text}")

        # Return compacted messages
        compacted = [summary_msg] + messages_to_keep
        num_compacted = len(messages_to_compact)

        # Log compaction completion with token counts
        compacted_token_count = self.estimate_token_count(compacted)
        logger.info(
            f"Compacted {num_compacted} messages "
            f"(token count: {compacted_token_count}/{MAX_CONTEXT_TOKENS})"
        )

        return compacted, True, num_compacted
