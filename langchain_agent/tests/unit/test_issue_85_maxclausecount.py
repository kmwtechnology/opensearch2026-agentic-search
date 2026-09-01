"""Tests for issue #85: maxClauseCount exceeded in multi-turn refinement conversations.

Covers:
1. Query term truncation in _truncate_query_terms
2. Message filtering in _expand_vague_query (HumanMessage only)
"""

from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from vector_store import OpenSearchVectorStore


@pytest.mark.unit
class TestTruncateQueryTerms:
    """Unit tests for _truncate_query_terms static method."""

    def test_no_truncation_for_short_query(self):
        """Query under max_terms should be unchanged."""
        short_query = "lamp for bedroom"
        result = OpenSearchVectorStore._truncate_query_terms(short_query, max_terms=40)
        assert result == short_query

    def test_truncation_at_max_terms_boundary(self):
        """Query at exactly max_terms should be unchanged."""
        query = " ".join([f"term{i}" for i in range(40)])
        result = OpenSearchVectorStore._truncate_query_terms(query, max_terms=40)
        assert result == query

    def test_truncation_above_max_terms(self):
        """Query exceeding max_terms should be truncated to max_terms."""
        query = " ".join([f"term{i}" for i in range(60)])
        result = OpenSearchVectorStore._truncate_query_terms(query, max_terms=40)
        truncated_terms = result.split()
        assert len(truncated_terms) == 40
        assert result == " ".join([f"term{i}" for i in range(40)])

    def test_truncation_preserves_order(self):
        """Truncation should keep the first N terms in order."""
        query = "apple banana cherry date elderberry fig grape honey"
        result = OpenSearchVectorStore._truncate_query_terms(query, max_terms=3)
        assert result == "apple banana cherry"

    def test_aggressive_truncation(self):
        """Test the aggressive 20-term truncation used in retry paths."""
        query = " ".join([f"word{i}" for i in range(100)])
        result = OpenSearchVectorStore._truncate_query_terms(query, max_terms=20)
        assert len(result.split()) == 20


@pytest.mark.unit
class TestExpandVagueQueryMessageFiltering:
    """Tests for HumanMessage-only filtering in _expand_vague_query."""

    def test_filters_out_ai_responses_from_context(self, bare_agent):
        """AI-only history means no HumanMessage context, so _expand_vague_query
        must short-circuit and return the query unchanged without ever calling
        the LLM -- proving AI turns never reach the expansion prompt."""
        bare_agent.alpha_estimator_llm = MagicMock()

        messages = [
            AIMessage(content="Here are some wireless headphones: Sony WH-1000XM5, Bose QC45"),
            AIMessage(content="Both are great for noise canceling and travel"),
        ]

        result = bare_agent._expand_vague_query("show cheaper ones", messages)

        assert result == "show cheaper ones"
        bare_agent.alpha_estimator_llm.invoke.assert_not_called()

    def test_user_messages_only_reduces_context_size(self, bare_agent):
        """When HumanMessages are present, the LLM prompt must contain only
        their content -- AI response content (product listings) must never
        leak into the expansion context, which is what caused issue #85's
        maxClauseCount errors on multi-turn refinement conversations."""
        bare_agent.alpha_estimator_llm = MagicMock()
        bare_agent.alpha_estimator_llm.invoke.return_value = MagicMock(
            content="wireless headphones under $100"
        )

        # A marker substring, not a full-string membership check: the context
        # builder .strip()s each message's content before joining, so
        # checking containment of the whole ai_bloat string (with its
        # trailing space from the `* 10` repeat) can pass even when the AI
        # content genuinely leaked in, just missing that last space.
        ai_marker = "Sony WH-1000XM5 wireless noise-canceling headphones"
        ai_bloat = f"{ai_marker} with 30-hour battery. " * 10
        messages = [
            HumanMessage(content="wireless headphones"),
            AIMessage(content=ai_bloat),
            HumanMessage(content="show cheaper ones"),
        ]

        bare_agent._expand_vague_query("show cheaper ones", messages)

        assert bare_agent.alpha_estimator_llm.invoke.called
        prompt = bare_agent.alpha_estimator_llm.invoke.call_args[0][0]
        assert "wireless headphones" in prompt
        assert ai_marker not in prompt
