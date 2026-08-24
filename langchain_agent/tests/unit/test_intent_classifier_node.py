"""Unit tests for EcommerceSearchAgent.intent_classifier_node."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_agent():
    """Construct an EcommerceSearchAgent without any real I/O connections."""
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
        agent.intent_structured = None
    return agent


def _state(messages, **kwargs):
    """Build a minimal agent state dict."""
    return {"messages": messages, **kwargs}


# ---------------------------------------------------------------------------
# TestIntentClassifierNodeExtractsQuery
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentClassifierNodeExtractsQuery:

    def test_extracts_last_human_message(self):
        agent = _make_agent()
        with patch.object(agent, "_classify_intent", return_value=("search", "reason", 0.9, [])):
            result = agent.intent_classifier_node(_state([HumanMessage(content="find headphones")]))
        assert result["user_query"] == "find headphones"

    def test_empty_query_when_no_human_message(self):
        agent = _make_agent()
        with patch.object(agent, "_classify_intent", return_value=("search", "reason", 0.9, [])):
            result = agent.intent_classifier_node(_state([AIMessage(content="hello")]))
        assert result["user_query"] == ""

    def test_skips_ai_messages_to_find_human(self):
        agent = _make_agent()
        messages = [
            HumanMessage(content="first"),
            AIMessage(content="reply"),
            HumanMessage(content="second"),
        ]
        with patch.object(agent, "_classify_intent", return_value=("search", "reason", 0.9, [])):
            result = agent.intent_classifier_node(_state(messages))
        assert result["user_query"] == "second"


# ---------------------------------------------------------------------------
# TestIntentClassifierNodeReturnsFields
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentClassifierNodeReturnsFields:

    def test_returns_all_required_fields(self):
        agent = _make_agent()
        with patch.object(
            agent, "_classify_intent", return_value=("search", "some reason", 0.9, [])
        ):
            result = agent.intent_classifier_node(_state([HumanMessage(content="query")]))
        for field in (
            "intent",
            "user_query",
            "reasoning",
            "confidence",
            "intent_confidence",
            "clarifying_questions",
        ):
            assert field in result, f"Missing field: {field}"

    def test_confidence_matches_intent_confidence(self):
        agent = _make_agent()
        with patch.object(agent, "_classify_intent", return_value=("search", "reason", 0.82, [])):
            result = agent.intent_classifier_node(_state([HumanMessage(content="query")]))
        assert result["confidence"] == result["intent_confidence"]

    def test_search_intent_passthrough(self):
        agent = _make_agent()
        with patch.object(agent, "_classify_intent", return_value=("search", "reason", 0.9, [])):
            result = agent.intent_classifier_node(_state([HumanMessage(content="find shoes")]))
        assert result["intent"] == "search"

    def test_clarifying_questions_passthrough(self):
        agent = _make_agent()
        with patch.object(
            agent, "_classify_intent", return_value=("clarify", "reason", 0.6, ["Q1?"])
        ):
            result = agent.intent_classifier_node(_state([HumanMessage(content="something vague")]))
        assert result["clarifying_questions"] == ["Q1?"]


# ---------------------------------------------------------------------------
# TestIntentClassifierNodeRefinementValidation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIntentClassifierNodeRefinementValidation:

    def test_refinement_with_no_prior_docs_passes_through(self):
        """refinement intent with no prior_search_documents skips continuity check."""
        agent = _make_agent()
        with patch.object(
            agent, "_classify_intent", return_value=("refinement", "reason", 0.85, [])
        ):
            result = agent.intent_classifier_node(_state([HumanMessage(content="under $50")]))
        # No prior_search_documents key → continuity check skipped → refinement preserved
        assert result["intent"] == "refinement"

    def test_refinement_downgraded_to_search_on_low_continuity(self):
        """Low continuity score (<0.3) downgrades refinement to search with confidence=0.95."""
        agent = _make_agent()
        prior_docs = [MagicMock()]
        with (
            patch.object(
                agent, "_classify_intent", return_value=("refinement", "reason", 0.85, [])
            ),
            patch.object(
                agent, "_validate_category_continuity", return_value=(0.2, "different category")
            ),
        ):
            result = agent.intent_classifier_node(
                _state([HumanMessage(content="now in blue")], prior_search_documents=prior_docs)
            )
        assert result["intent"] == "search"
        assert result["confidence"] == 0.95

    def test_refinement_confidence_lowered_on_ambiguous_continuity(self):
        """Continuity score in [0.3, 0.7) caps confidence at 0.65."""
        agent = _make_agent()
        prior_docs = [MagicMock()]
        with (
            patch.object(agent, "_classify_intent", return_value=("refinement", "reason", 0.9, [])),
            patch.object(agent, "_validate_category_continuity", return_value=(0.5, "ambiguous")),
        ):
            result = agent.intent_classifier_node(
                _state(
                    [HumanMessage(content="with better battery")], prior_search_documents=prior_docs
                )
            )
        assert result["intent"] == "refinement"
        assert result["confidence"] <= 0.65

    def test_refinement_preserved_on_high_continuity(self):
        """High continuity score (>=0.7) keeps refinement intent and original confidence."""
        agent = _make_agent()
        prior_docs = [MagicMock()]
        with (
            patch.object(
                agent, "_classify_intent", return_value=("refinement", "reason", 0.88, [])
            ),
            patch.object(
                agent, "_validate_category_continuity", return_value=(0.85, "same category")
            ),
        ):
            result = agent.intent_classifier_node(
                _state([HumanMessage(content="under $100")], prior_search_documents=prior_docs)
            )
        assert result["intent"] == "refinement"
        assert result["confidence"] == 0.88
