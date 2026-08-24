"""Regression: query-extraction sites must flatten Gemini list-of-blocks content.

Production incident: a HumanMessage whose ``.content`` was a list of content
blocks (e.g. ``[{"type": "text", "text": "..."}]``) reached
``retriever_node`` unflattened, was passed straight to OpenSearch as the
``query`` field of ``multi_match``, and triggered::

    RequestError(400, 'x_content_parse_exception',
        '[multi_match] unknown token [START_ARRAY] after [query]')

The proximate trigger (``langchain-google-genai`` quirk vs. checkpoint
serde vs. something else) is unconfirmed — Pydantic enforces ``str`` at
the chat route — but five sites in ``main.py`` extracted ``msg.content``
from a HumanMessage as a query string without flattening, so any one of
them was a latent bug. Only ``retriever_node`` crashed because it was the
first to send the value over the wire as JSON; the other four would have
silently corrupted classifier confidence, alpha estimation, the no-info
fallback, and the reranker prompt.

This test pins the fix: each of the five extraction sites must yield a
flat string when the upstream HumanMessage carries list-of-blocks content.
"""

from __future__ import annotations

from typing import Any, List

import pytest
from langchain_core.messages import HumanMessage

from main import _flatten_llm_content

GEMINI_BLOCKS: List[dict] = [
    {"type": "text", "text": "wireless headphones "},
    {"type": "text", "text": "under $100"},
]
EXPECTED = "wireless headphones under $100"


@pytest.mark.unit
@pytest.mark.phase1
class TestHumanMessageQueryExtractionFlattens:
    """Every site in main.py that reads `msg.content` from a HumanMessage
    as a query string must route through _flatten_llm_content.

    The test re-implements each extraction loop verbatim and asserts the
    extracted value is a plain string for both flat-string and Gemini
    list-of-blocks content shapes.
    """

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("wireless headphones under $100", "wireless headphones under $100"),
            (GEMINI_BLOCKS, EXPECTED),
        ],
    )
    def test_intent_classifier_extraction(self, content: Any, expected: str) -> None:
        # Mirrors main.py:520-525 (intent_classifier_node).
        messages = [HumanMessage(content=content)]
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, "content") and msg.content:
                user_query = _flatten_llm_content(msg)
                break
        assert isinstance(user_query, str)
        assert user_query == expected

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("running shoes", "running shoes"),
            (GEMINI_BLOCKS, EXPECTED),
        ],
    )
    def test_query_evaluator_extraction(self, content: Any, expected: str) -> None:
        # Mirrors main.py:618-623 (query_evaluator_node).
        messages = [HumanMessage(content=content)]
        last_user_msg = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                last_user_msg = _flatten_llm_content(msg)
                break
        assert isinstance(last_user_msg, str)
        assert last_user_msg == expected

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("kitchen knives", "kitchen knives"),
            (GEMINI_BLOCKS, EXPECTED),
        ],
    )
    def test_agent_node_extraction(self, content: Any, expected: str) -> None:
        # Mirrors main.py:1064-1069 (agent_node).
        messages = [HumanMessage(content=content)]
        user_query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = _flatten_llm_content(msg)
                break
        assert isinstance(user_query, str)
        assert user_query == expected

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("noise-cancelling headphones", "noise-cancelling headphones"),
            (GEMINI_BLOCKS, EXPECTED),
        ],
    )
    def test_retriever_node_extraction(self, content: Any, expected: str) -> None:
        # Mirrors main.py:2354-2359 (retriever_node) — the site whose
        # unflattened list crashed OpenSearch's multi_match query parser.
        messages = [HumanMessage(content=content)]
        query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                query = _flatten_llm_content(msg)
                break
        assert isinstance(query, str)
        assert query == expected

    @pytest.mark.parametrize(
        "content, expected",
        [
            ("toaster oven", "toaster oven"),
            (GEMINI_BLOCKS, EXPECTED),
        ],
    )
    def test_reranker_node_extraction(self, content: Any, expected: str) -> None:
        # Mirrors main.py:2664-2671 (reranker_node fallback path when
        # state["user_query"] is empty).
        messages = [HumanMessage(content=content)]
        query = ""
        if not query:
            for msg in reversed(messages):
                if isinstance(msg, HumanMessage):
                    query = _flatten_llm_content(msg)
                    break
        assert isinstance(query, str)
        assert query == expected

    def test_thinking_blocks_skipped_in_extraction(self) -> None:
        # Reasoning models can mix thinking + text blocks; only text counts.
        mixed = [
            {"type": "thinking", "thinking": "user wants electronics..."},
            {"type": "text", "text": "smart speakers"},
        ]
        msg = HumanMessage(content=mixed)
        out = _flatten_llm_content(msg)
        assert isinstance(out, str)
        assert out == "smart speakers"
