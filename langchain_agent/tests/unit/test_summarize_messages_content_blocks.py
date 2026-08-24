"""Unit tests for the _flatten_llm_content helper and summarize_messages.

Regression for task #17: when the user sends a `summary` follow-up against
a prior thread, the agent emitted `agent_error` because `summarize_messages`
returned the LLM response's raw `content` — which is a list of content
blocks on Gemini 3, not a string. The downstream `SummaryEvent.summary_text:
str` Pydantic field then rejected it with a validation error.

Verifies:
- _flatten_llm_content returns a string for both flat-string content and
  Gemini list-of-content-blocks content.
- summarize_messages calls the helper and returns a string regardless of
  which shape the LLM produces.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from main import _flatten_llm_content


class _Resp:
    """Minimal AIMessage-like response object."""

    def __init__(self, content: Any) -> None:
        self.content = content


@pytest.mark.unit
@pytest.mark.phase1
class TestFlattenLLMContent:
    def test_flat_string_passes_through(self) -> None:
        assert _flatten_llm_content(_Resp("hello world")) == "hello world"

    def test_gemini_content_blocks_joined(self) -> None:
        gemini_content = [
            {"type": "text", "text": "Summary of "},
            {"type": "text", "text": "the conversation."},
        ]
        assert _flatten_llm_content(_Resp(gemini_content)) == "Summary of the conversation."

    def test_thinking_blocks_skipped(self) -> None:
        # Reasoning models emit non-text blocks like {"type": "thinking", ...};
        # skip anything without a `text` key so the SummaryEvent doesn't get
        # an internal CoT trace.
        mixed = [
            {"type": "thinking", "thinking": "let me think..."},
            {"type": "text", "text": "Final answer."},
        ]
        assert _flatten_llm_content(_Resp(mixed)) == "Final answer."

    def test_string_blocks_in_list_concatenated(self) -> None:
        # Edge case: some adapters yield a list of plain strings instead of
        # dicts. Treat each as a chunk.
        assert _flatten_llm_content(_Resp(["a", "b", "c"])) == "abc"

    def test_empty_list_returns_empty_string(self) -> None:
        assert _flatten_llm_content(_Resp([])) == ""

    def test_raw_content_payload_accepted(self) -> None:
        # Helper accepts raw content (no .content attribute).
        assert _flatten_llm_content("plain") == "plain"
        assert _flatten_llm_content([{"type": "text", "text": "x"}]) == "x"

    def test_non_string_non_list_coerced_to_str(self) -> None:
        # Defensive: shouldn't happen in practice but must not crash.
        assert _flatten_llm_content(_Resp(42)) == "42"


@pytest.mark.unit
@pytest.mark.phase1
class TestSummarizeMessagesReturnsString:
    """summarize_messages must always return a str, even when the LLM
    returns a list of content blocks (Gemini)."""

    def _agent_with_llm_returning(self, content: Any):
        from main import EcommerceSearchAgent

        agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
        agent.llm = MagicMock()
        agent.llm.invoke.return_value = _Resp(content)
        return agent

    def test_string_response_passes_through(self) -> None:
        agent = self._agent_with_llm_returning("Plain summary.")
        out = agent.summarize_messages([HumanMessage(content="hi"), AIMessage(content="hello")])
        assert isinstance(out, str)
        assert out == "Plain summary."

    def test_gemini_content_blocks_flattened(self) -> None:
        # The exact shape that crashed production on 2026-04-29:
        # response.content was a list of {type, text} dicts and the
        # SummaryEvent Pydantic field rejected it.
        gemini_content = [
            {"type": "text", "text": "User asked about headphones. "},
            {"type": "text", "text": "Assistant returned 4 products."},
        ]
        agent = self._agent_with_llm_returning(gemini_content)
        out = agent.summarize_messages([HumanMessage(content="hi"), AIMessage(content="hello")])
        assert isinstance(out, str)
        assert out == "User asked about headphones. Assistant returned 4 products."
