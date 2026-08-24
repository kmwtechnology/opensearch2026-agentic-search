"""Unit tests for EcommerceSearchAgent.quality_gate_node and summary_node."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage


def _make_agent():
    with patch("main.LinkVerifier"), patch("main.DocumentReplacer"):
        from main import EcommerceSearchAgent

        agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
        agent.llm = None
        agent.embeddings = None
        agent.vector_store = None
        agent.pool = None
        agent.async_pool = None
        agent.checkpointer = None
        agent.app = None
        agent.thread_id = None
        agent.emit_callback = None
        agent.event_loop = None
        agent.event_queue = []
        agent.retriever = None
        agent.reranker = None
        agent.alpha_estimator_llm = None
        agent.link_verifier = MagicMock()
        agent.doc_replacer = MagicMock()
        agent.judge = None
    return agent


def _msgs(n=2):
    return [HumanMessage(content=f"msg {i}") for i in range(n)]


@pytest.mark.unit
class TestSummaryNode:
    def test_non_summary_intent_returns_none_text(self):
        agent = _make_agent()
        msgs = _msgs(2)
        result = agent.summary_node({"messages": msgs, "intent": "search"})
        assert result["summary_text"] is None
        assert result["message_count"] == 2

    def test_summary_intent_calls_summarize_messages(self):
        agent = _make_agent()
        msgs = _msgs(3)
        agent.summarize_messages = MagicMock(return_value="Summary text")
        result = agent.summary_node({"messages": msgs, "intent": "summary"})
        agent.summarize_messages.assert_called_once_with(msgs)
        assert result["summary_text"] == "Summary text"
        assert result["message_count"] == 3

    def test_summary_intent_fallback_when_empty_summary(self):
        agent = _make_agent()
        msgs = _msgs(1)
        agent.summarize_messages = MagicMock(return_value="")
        result = agent.summary_node({"messages": msgs, "intent": "summary"})
        assert result["summary_text"] == "No additional context available for summary."

    def test_message_count_always_correct(self):
        agent = _make_agent()
        msgs = _msgs(3)
        result = agent.summary_node({"messages": msgs, "intent": "follow_up"})
        assert result["message_count"] == 3
        assert result["summary_text"] is None


@pytest.mark.unit
class TestQualityGateNode:
    def _docs(self):
        return [MagicMock()]

    def test_pass_when_score_above_threshold(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.5,
            "reranker_max_score": 0.8,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "pass"
        assert result["quality_gate_retried"] is False
        assert result["reranker_max_score"] == pytest.approx(0.8)

    def test_retry_when_score_below_threshold_first_time(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.7,
            "reranker_max_score": 0.3,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "retry"
        assert result["quality_gate_retried"] is True

    def test_retry_adjusts_alpha_toward_lexical_when_high(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.8,
            "reranker_max_score": 0.2,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["alpha"] == pytest.approx(0.5)  # 0.8 - 0.3

    def test_retry_adjusts_alpha_toward_semantic_when_low(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.2,
            "reranker_max_score": 0.1,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["alpha"] == pytest.approx(0.5)  # 0.2 + 0.3

    def test_accept_after_retry(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.5,
            "reranker_max_score": 0.42,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": True,
        }
        result = agent.quality_gate_node(state)
        assert "Accepted after retry" in result["quality_gate_reason"]
        assert result["reranker_max_score"] == pytest.approx(0.42)

    def test_no_documents_returns_early(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.5,
            "reranker_max_score": 0.1,
            "retrieved_documents": [],
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_reason"] == "No documents to evaluate"
        assert result["quality_gate_retried"] is False

    def test_comparison_intent_has_higher_threshold(self):
        """Score 0.50 is below comparison threshold (0.55) → retry."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "comparison",
            "alpha": 0.6,
            "reranker_max_score": 0.50,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "retry"

    def test_attribute_filter_has_lower_threshold(self):
        """Score 0.46 is above attribute_filter threshold (0.45) → pass."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "attribute_filter",
            "alpha": 0.25,
            "reranker_max_score": 0.46,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "pass"

    def test_score_stored_in_result(self):
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.5,
            "reranker_max_score": 0.75,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert "reranker_max_score" in result
        assert result["reranker_max_score"] == pytest.approx(0.75)

    def test_threshold_used_emitted_on_pass(self):
        """quality_gate_threshold_used must be present so the UI shows intent-specific value."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "attribute_filter",
            "alpha": 0.25,
            "reranker_max_score": 0.63,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "pass"
        assert result["quality_gate_threshold_used"] == pytest.approx(0.45)

    def test_threshold_used_emitted_on_retry(self):
        """quality_gate_threshold_used is present on the retry path too."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "comparison",
            "alpha": 0.6,
            "reranker_max_score": 0.3,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_status"] == "retry"
        assert result["quality_gate_threshold_used"] == pytest.approx(0.55)

    def test_threshold_used_emitted_on_no_docs(self):
        """quality_gate_threshold_used is present even when there are no docs."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "search",
            "alpha": 0.5,
            "reranker_max_score": 0.0,
            "retrieved_documents": [],
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        assert result["quality_gate_threshold_used"] == pytest.approx(0.50)

    def test_threshold_used_matches_reason_string(self):
        """The emitted threshold_used must match the value baked into the reason string."""
        agent = _make_agent()
        state = {
            "messages": _msgs(),
            "intent": "attribute_filter",
            "alpha": 0.25,
            "reranker_max_score": 0.63,
            "retrieved_documents": self._docs(),
            "quality_gate_retried": False,
        }
        result = agent.quality_gate_node(state)
        threshold = result["quality_gate_threshold_used"]
        assert f"{threshold:.2f}" in result["quality_gate_reason"]
