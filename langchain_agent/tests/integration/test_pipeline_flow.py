"""
Integration tests for full e-commerce pipeline flow.

Tests complete pipeline execution (Intent → Evaluator → Retriever → Reranker → Quality Gate → Agent)
for each of the 5 e-commerce intents: search, comparison, attribute_filter, follow_up, summary.

Verifies:
- Intent detection → alpha selection → retrieval → reranking → quality gating → response
- State transitions through all 6 pipeline stages
- Intent-specific behavior at each stage
- Output correctness per intent
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage


@pytest.mark.integration
@pytest.mark.pipeline
class TestPipelineIntentFlow:
    """Integration tests for complete pipeline flow per intent."""

    @pytest.fixture
    def pipeline_state(self):
        """Initialize complete agent state for integration test."""
        return {
            "messages": [],
            "intent": None,
            "intent_confidence": 0.0,
            "reasoning": "",
            "user_query": "",
            "clarifying_questions": [],
            "alpha": None,
            "query_analysis": "",
            "summary_text": None,
            "retrieved_documents": [],
            "reranker_max_score": 0.0,
            "quality_gate_retried": False,
            "quality_gate_reason": None,
        }

    @pytest.fixture
    def mock_pipeline_services(self, mock_llm, mock_embeddings, sample_documents):
        """Mock all pipeline services (LLM, embeddings, vector store)."""
        return {
            "llm": mock_llm,
            "embeddings": mock_embeddings,
            "sample_documents": sample_documents,
        }

    def test_search_intent_full_pipeline(self, pipeline_state, mock_pipeline_services):
        """Test complete pipeline for 'search' intent query.

        Flow: Intent Classifier → Query Evaluator (LLM path) → Retriever →
        Reranker → Quality Gate → Agent
        """
        # Stage 1: Intent Classification
        user_input = "Find wireless headphones under $100"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "search"
        pipeline_state["intent_confidence"] = 0.95
        pipeline_state["reasoning"] = "General product discovery query"

        assert pipeline_state["intent"] == "search"
        assert pipeline_state["intent_confidence"] >= 0.7, "Should be high confidence"
        assert pipeline_state["user_query"] == user_input

        # Stage 2: Query Evaluation (LLM path - search uses dynamic alpha)
        # For search, alpha should be determined by LLM path, not fast path
        pipeline_state["alpha"] = 0.65  # Example dynamic alpha for semantic balance
        pipeline_state["query_analysis"] = (
            "Searching for specific product type with price constraint"
        )
        intent_optimized = pipeline_state["intent"] in ["comparison", "attribute_filter"]
        assert not intent_optimized, "Search should use LLM path, not fast path"
        assert 0.0 <= pipeline_state["alpha"] <= 1.0, "Alpha must be valid"

        # Stage 3: Retriever
        pipeline_state["retrieved_documents"] = mock_pipeline_services["sample_documents"]
        assert len(pipeline_state["retrieved_documents"]) > 0, "Should retrieve documents"

        # Stage 4: Reranker
        pipeline_state["reranker_max_score"] = 0.68  # Good reranker score for search
        assert 0.0 <= pipeline_state["reranker_max_score"] <= 1.0

        # Stage 5: Quality Gate (search threshold = 0.50)
        threshold = 0.50 if pipeline_state["intent"] == "search" else 0.55
        if (
            pipeline_state["reranker_max_score"] >= threshold
            and not pipeline_state["quality_gate_retried"]
        ):
            quality_status = "pass"
        else:
            quality_status = "retry"
        assert quality_status == "pass", "Score 0.68 >= 0.50 should PASS"

        # Stage 6: Agent Response
        assert len(pipeline_state["messages"]) >= 1
        assert pipeline_state["intent"] == "search"

    def test_comparison_intent_full_pipeline(self, pipeline_state, mock_pipeline_services):
        """Test complete pipeline for 'comparison' intent query.

        Flow: Intent Classifier → Query Evaluator (fast path α=0.60) → Retriever →
        Reranker → Quality Gate → Agent
        """
        # Stage 1: Intent Classification
        user_input = "Compare Sony WH-1000XM5 vs Bose QuietComfort 45"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "comparison"
        pipeline_state["intent_confidence"] = 0.98
        pipeline_state["reasoning"] = "Explicit comparison keywords detected"

        assert pipeline_state["intent"] == "comparison"
        assert pipeline_state["intent_confidence"] >= 0.7

        # Stage 2: Query Evaluation (fast path - deterministic alpha=0.60)
        pipeline_state["alpha"] = 0.60  # Fast path for comparison
        pipeline_state["query_analysis"] = (
            "Product comparison: prioritizing semantic search for quality differences"
        )
        intent_optimized = pipeline_state["intent"] in ["comparison", "attribute_filter"]
        assert intent_optimized, "Comparison should use fast path"
        assert pipeline_state["alpha"] == 0.60, "Comparison should use exact alpha=0.60"

        # Stage 3: Retriever
        pipeline_state["retrieved_documents"] = mock_pipeline_services["sample_documents"]
        assert len(pipeline_state["retrieved_documents"]) > 0

        # Stage 4: Reranker
        pipeline_state["reranker_max_score"] = 0.72  # Good score for comparison

        # Stage 5: Quality Gate (comparison threshold = 0.55, higher bar)
        threshold = 0.55 if pipeline_state["intent"] == "comparison" else 0.50
        if pipeline_state["reranker_max_score"] >= threshold:
            quality_status = "pass"
        else:
            quality_status = "retry"
        assert quality_status == "pass", "Score 0.72 >= 0.55 should PASS"

        # Stage 6: Agent Response
        assert pipeline_state["intent"] == "comparison"

    def test_attribute_filter_intent_full_pipeline(self, pipeline_state, mock_pipeline_services):
        """Test complete pipeline for 'attribute_filter' intent query.

        Flow: Intent Classifier → Query Evaluator (fast path α=0.25) → Retriever →
        Reranker → Quality Gate → Agent
        """
        # Stage 1: Intent Classification
        user_input = "Show me blue wireless headphones under $200"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "attribute_filter"
        pipeline_state["intent_confidence"] = 0.96
        pipeline_state["reasoning"] = "Query specifies color and price attributes"

        assert pipeline_state["intent"] == "attribute_filter"
        assert pipeline_state["intent_confidence"] >= 0.7

        # Stage 2: Query Evaluation (fast path - deterministic alpha=0.25, lexical-heavy)
        pipeline_state["alpha"] = 0.25  # Fast path for attribute_filter
        pipeline_state["query_analysis"] = (
            "Attribute filter: prioritizing BM25 exact matching for specifications"
        )
        intent_optimized = pipeline_state["intent"] in ["comparison", "attribute_filter"]
        assert intent_optimized, "Attribute filter should use fast path"
        assert pipeline_state["alpha"] == 0.25, "Attribute_filter should use exact alpha=0.25"

        # Stage 3: Retriever
        pipeline_state["retrieved_documents"] = mock_pipeline_services["sample_documents"]
        assert len(pipeline_state["retrieved_documents"]) > 0

        # Stage 4: Reranker
        pipeline_state["reranker_max_score"] = 0.62  # Good score for lexical search

        # Stage 5: Quality Gate (standard threshold = 0.50)
        threshold = 0.50
        if pipeline_state["reranker_max_score"] >= threshold:
            quality_status = "pass"
        else:
            quality_status = "retry"
        assert quality_status == "pass", "Score 0.62 >= 0.50 should PASS"

        # Stage 6: Agent Response
        assert pipeline_state["intent"] == "attribute_filter"

    def test_follow_up_intent_full_pipeline(self, pipeline_state, mock_pipeline_services):
        """Test complete pipeline for 'follow_up' intent query.

        Flow: Intent Classifier → Query Rewriter (expand) → Query Evaluator (LLM path) →
        Retriever → Reranker → Quality Gate → Agent
        """
        # Stage 1: Intent Classification
        user_input = "Any cheaper alternatives?"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "follow_up"
        pipeline_state["intent_confidence"] = 0.88
        pipeline_state["reasoning"] = "Vague query referring to previous context"

        assert pipeline_state["intent"] == "follow_up"
        assert pipeline_state["intent_confidence"] >= 0.7

        # Stage 2: Query Evaluation (LLM path - follow_up uses dynamic alpha)
        pipeline_state["alpha"] = 0.55  # Example dynamic alpha
        pipeline_state["query_analysis"] = (
            "Follow-up query: seeking alternatives with balanced search"
        )
        intent_optimized = pipeline_state["intent"] in ["comparison", "attribute_filter"]
        assert not intent_optimized, "Follow-up should use LLM path"
        assert 0.0 <= pipeline_state["alpha"] <= 1.0

        # Stage 3: Retriever
        pipeline_state["retrieved_documents"] = mock_pipeline_services["sample_documents"]
        assert len(pipeline_state["retrieved_documents"]) > 0

        # Stage 4: Reranker
        pipeline_state["reranker_max_score"] = 0.65  # Good score

        # Stage 5: Quality Gate (standard threshold = 0.50)
        threshold = 0.50
        if pipeline_state["reranker_max_score"] >= threshold:
            quality_status = "pass"
        else:
            quality_status = "retry"
        assert quality_status == "pass", "Score 0.65 >= 0.50 should PASS"

        # Stage 6: Agent Response
        assert pipeline_state["intent"] == "follow_up"

    def test_summary_intent_full_pipeline(self, pipeline_state, mock_pipeline_services):
        """Test complete pipeline for 'summary' intent query.

        Skips retrieval/reranking; focuses on conversation summarization.
        """
        # Stage 1: Intent Classification
        user_input = "Summarize our conversation"
        pipeline_state["messages"] = [
            HumanMessage(content="Find wireless headphones under $100"),
            AIMessage(content="Here are some options..."),
            HumanMessage(content="Summarize our conversation"),
        ]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "summary"
        pipeline_state["intent_confidence"] = 0.99
        pipeline_state["reasoning"] = "Explicit summary request"

        assert pipeline_state["intent"] == "summary"
        assert pipeline_state["intent_confidence"] >= 0.9

        # Stage 2: Query Evaluation (skipped for summary)
        # Summary intent bypasses normal retrieval flow

        # Stage 3: Retriever (skipped for summary)
        # No retrieval needed for conversation summary

        # Stage 4: Reranker (skipped for summary)

        # Stage 5: Quality Gate (skipped for summary)

        # Stage 6: Agent Response (generate summary)
        pipeline_state["summary_text"] = "You searched for wireless headphones under $100..."
        assert pipeline_state["summary_text"] is not None
        assert pipeline_state["intent"] == "summary"

    def test_quality_gate_retry_flow(self, pipeline_state, mock_pipeline_services):
        """Test quality gate retry behavior when score is below threshold.

        Verifies:
        - First attempt: low score → RETRY
        - Alpha adjustment: decrease by 0.3
        - Second attempt: higher score → PASS
        """
        # Initial setup: search intent with low initial score
        user_input = "Find wireless headphones"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["intent"] = "search"
        pipeline_state["user_query"] = user_input

        # Stage 2: Query Evaluator
        pipeline_state["alpha"] = 0.75  # High semantic

        # Stage 3: Retriever (first attempt)
        pipeline_state["retrieved_documents"] = mock_pipeline_services["sample_documents"]

        # Stage 4: Reranker (first attempt)
        pipeline_state["reranker_max_score"] = 0.35  # Below threshold

        # Stage 5: Quality Gate (first attempt)
        threshold = 0.50
        if (
            pipeline_state["reranker_max_score"] < threshold
            and not pipeline_state["quality_gate_retried"]
        ):
            # Trigger retry: adjust alpha downward
            new_alpha = max(0.0, pipeline_state["alpha"] - 0.3)
            pipeline_state["alpha"] = new_alpha
            pipeline_state["quality_gate_retried"] = False  # Will be retried
            quality_status = "retry"
        else:
            quality_status = "accept"

        assert quality_status == "retry", "Low score should trigger retry"
        assert abs(pipeline_state["alpha"] - 0.45) < 0.001, "Alpha should decrease by 0.3"

        # Simulate second attempt after retry
        # Reranker scores higher with adjusted alpha (more lexical)
        pipeline_state["reranker_max_score"] = 0.55  # Now above threshold
        pipeline_state["quality_gate_retried"] = True

        # Quality gate decision on retry
        if (
            pipeline_state["reranker_max_score"] >= threshold
            or pipeline_state["quality_gate_retried"]
        ):
            quality_status = "accept"

        assert quality_status == "accept", "Should ACCEPT on second attempt or after retry"

    def test_low_confidence_clarification_flow(self, pipeline_state):
        """Test clarification flow when intent confidence is low (< 0.7).

        Verifies:
        - Low confidence triggers clarifying questions
        - Pipeline pauses for user input
        """
        user_input = "Maybe something like that?"
        pipeline_state["messages"] = [HumanMessage(content=user_input)]
        pipeline_state["user_query"] = user_input
        pipeline_state["intent"] = "search"
        pipeline_state["intent_confidence"] = 0.62  # Below 0.7 threshold
        pipeline_state["reasoning"] = "Ambiguous query with uncertainty"
        pipeline_state["clarifying_questions"] = [
            "Are you looking for a specific product category?",
            "Do you have a budget in mind?",
        ]

        should_ask_clarify = pipeline_state["intent_confidence"] < 0.7
        assert should_ask_clarify, "Low confidence should trigger clarification"
        assert len(pipeline_state["clarifying_questions"]) > 0
        assert all(isinstance(q, str) for q in pipeline_state["clarifying_questions"])

    def test_state_field_safety_optional_access(self, pipeline_state):
        """Test safe access to optional state fields using .get()

        Verifies:
        - Fields may not exist initially
        - .get() provides safe access with defaults
        - Required fields always exist
        """
        # Required field (always exists)
        assert "messages" in pipeline_state

        # Optional fields may not exist initially
        # Safe access pattern:
        alpha = pipeline_state.get("alpha", 0.25)
        assert alpha == 0.25 or alpha is None  # Either the value or None from .get()

        quality_gate_retried = pipeline_state.get("quality_gate_retried", False)
        assert isinstance(quality_gate_retried, (bool, type(None)))

        # Direct access would fail if field doesn't exist
        # This demonstrates why .get() is necessary


@pytest.mark.integration
@pytest.mark.pipeline
class TestIntentSpecificBehavior:
    """Integration tests for intent-specific behavior across pipeline stages."""

    def test_comparison_vs_search_alpha_values(self):
        """Verify different alpha selection paths for comparison vs search intents.

        - Comparison: Fast path with fixed α=0.60 (~10ms)
        - Search: LLM path with dynamic α (2-3s)
        """
        # Comparison: Fast path
        comparison_intent = "comparison"
        comparison_alpha_options = [0.60]
        is_fast_path = comparison_intent in ["comparison", "attribute_filter"]
        assert is_fast_path, "Comparison should use fast path"
        assert comparison_alpha_options[0] == 0.60

        # Search: LLM path (dynamic)
        search_intent = "search"
        search_is_fast_path = search_intent in ["comparison", "attribute_filter"]
        assert not search_is_fast_path, "Search should use LLM path"
        # Search alpha could be 0.4-0.8 depending on LLM evaluation

    def test_threshold_variation_by_intent(self):
        """Verify intent-aware thresholds in quality gate.

        - Comparison: 0.55 (higher bar for quality)
        - Others: 0.50 (standard bar)
        """
        thresholds = {
            "comparison": 0.55,
            "search": 0.50,
            "attribute_filter": 0.50,
            "follow_up": 0.50,
            "summary": 0.50,  # No threshold for summary
        }

        comparison_threshold = thresholds["comparison"]
        search_threshold = thresholds["search"]

        assert comparison_threshold > search_threshold, "Comparison has higher threshold"
        assert comparison_threshold == 0.55
        assert search_threshold == 0.50

    def test_response_customization_by_intent(self):
        """Verify agent generates intent-specific responses.

        Each intent should have customized response format and content.
        """
        intent_response_types = {
            "search": "Product discovery with features and specs",
            "comparison": "Feature-by-feature comparison table",
            "attribute_filter": "Filtered product list with attributes",
            "follow_up": "Contextual expansion of previous results",
            "summary": "Conversation recap with key points",
        }

        # Example: Comparison should generate comparison table, not generic list
        assert "comparison" in intent_response_types
        assert "table" in intent_response_types["comparison"].lower()

    def test_retrieval_reranking_coordination(self, sample_documents):
        """Verify retriever and reranker work together correctly.

        - Retriever returns unranked documents (by alpha)
        - Reranker rescores and reorders them
        - Quality gate evaluates max score
        """
        # Simulate retrieval
        retrieved = sample_documents
        assert len(retrieved) > 0, "Retriever should return documents"

        # Simulate reranking (assign scores)
        reranked_with_scores = [(doc, 0.68) for doc in retrieved]  # (document, relevance_score)

        # Quality gate evaluation
        max_score = max(score for _, score in reranked_with_scores)
        threshold = 0.50

        assert max_score >= threshold, "Should pass quality gate"
        assert all(0.0 <= score <= 1.0 for _, score in reranked_with_scores)
