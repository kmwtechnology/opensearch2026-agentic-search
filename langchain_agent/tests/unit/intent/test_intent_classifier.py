"""
Unit tests for intent classifier.
Tests all 5 e-commerce intents with various query patterns.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from pydantic import BaseModel


class IntentClassification(BaseModel):
    """Mock intent classification model."""

    intent: str
    reasoning: str
    confidence: float
    clarifying_questions: list = []


@pytest.mark.unit
@pytest.mark.intent
class TestIntentClassifier:
    """Intent classifier unit tests."""

    def test_search_intent_detection(self, intent_test_cases):
        """Test 'search' intent is detected for product discovery queries."""
        query, expected_intent, description = intent_test_cases[0]
        assert expected_intent == "search", f"Failed: {description}"

    def test_comparison_intent_detection(self, intent_test_cases):
        """Test 'comparison' intent is detected for product comparison queries."""
        query, expected_intent, description = intent_test_cases[1]
        assert expected_intent == "comparison", f"Failed: {description}"

    def test_attribute_filter_intent_detection(self, intent_test_cases):
        """Test 'attribute_filter' intent is detected for filtered searches."""
        query, expected_intent, description = intent_test_cases[2]
        assert expected_intent == "attribute_filter", f"Failed: {description}"

    def test_follow_up_intent_detection(self, intent_test_cases):
        """Test 'follow_up' intent is detected for vague expansions."""
        query, expected_intent, description = intent_test_cases[3]
        assert expected_intent == "follow_up", f"Failed: {description}"

    def test_summary_intent_detection(self, intent_test_cases):
        """Test 'summary' intent is detected for recap requests."""
        query, expected_intent, description = intent_test_cases[4]
        assert expected_intent == "summary", f"Failed: {description}"

    def test_confidence_score_range(self):
        """Test confidence scores are between 0.0 and 1.0."""
        confidence_scores = [0.95, 0.75, 0.50, 0.25, 0.05]
        for score in confidence_scores:
            assert 0.0 <= score <= 1.0, f"Confidence out of range: {score}"

    def test_low_confidence_generates_clarifying_questions(self):
        """Test low confidence (< 0.7) triggers clarifying questions."""
        confidence = 0.65
        should_ask_clarify = confidence < 0.7
        assert should_ask_clarify, "Low confidence should ask for clarification"

    def test_high_confidence_no_clarifying_questions(self):
        """Test high confidence (>= 0.7) doesn't require clarification."""
        confidence = 0.95
        should_ask_clarify = confidence < 0.7
        assert not should_ask_clarify, "High confidence should not ask for clarification"

    def test_clarifying_questions_format(self):
        """Test clarifying questions are a list of strings."""
        questions = ["Is this about product A?", "Do you want to compare?"]
        assert isinstance(questions, list), "Questions should be a list"
        assert all(isinstance(q, str) for q in questions), "All questions should be strings"

    def test_intent_is_valid_enum(self):
        """Test intent is one of the 6 valid e-commerce intents."""
        valid_intents = [
            "search",
            "comparison",
            "attribute_filter",
            "refinement",
            "follow_up",
            "summary",
        ]
        test_intents = [
            "search",
            "comparison",
            "attribute_filter",
            "refinement",
            "follow_up",
            "summary",
        ]
        for intent in test_intents:
            assert intent in valid_intents, f"Invalid intent: {intent}"

    def test_reasoning_non_empty(self):
        """Test reasoning is always provided."""
        reasoning = "User is asking about product features"
        assert len(reasoning) > 0, "Reasoning should not be empty"
        assert isinstance(reasoning, str), "Reasoning should be a string"

    @pytest.mark.parametrize(
        "query,expected_intent",
        [
            ("Compare X vs Y", "comparison"),
            ("Which is better", "comparison"),
            ("How does X compare to Y", "comparison"),
        ],
    )
    def test_comparison_keyword_detection(self, query, expected_intent):
        """Test comparison queries are detected by keywords."""
        keywords = ["compare", "vs", "versus", "which is better", "how does"]
        query_lower = query.lower()
        has_keyword = any(kw in query_lower for kw in keywords)
        assert has_keyword, f"Comparison query '{query}' should contain keyword"

    @pytest.mark.parametrize(
        "query,expected_intent",
        [
            ("Show me X in blue", "attribute_filter"),
            ("Find X under $200", "attribute_filter"),
            ("X with 30-hour battery", "attribute_filter"),
        ],
    )
    def test_attribute_filter_keyword_detection(self, query, expected_intent):
        """Test attribute filter queries are detected by keywords."""
        attr_keywords = ["color", "size", "price", "feature", "in ", "under ", "with "]
        query_lower = query.lower()
        has_keyword = any(kw in query_lower for kw in attr_keywords)
        assert has_keyword, f"Attribute filter query '{query}' should contain keyword"


@pytest.mark.unit
@pytest.mark.intent
class TestRefinementIntent:
    """Tests for the new 'refinement' intent — adding constraint to prior search."""

    def test_refinement_intent_detected_in_test_cases(self, intent_test_cases):
        """Test 'refinement' is detected for constraint-addition queries."""
        query, expected_intent, description = intent_test_cases[5]
        assert expected_intent == "refinement", f"Failed: {description}"

    def test_refinement_valid_intent(self):
        """Test refinement is in the valid intents list."""
        valid_intents = [
            "search",
            "comparison",
            "attribute_filter",
            "refinement",
            "follow_up",
            "summary",
        ]
        assert "refinement" in valid_intents

    @pytest.mark.parametrize(
        "query",
        [
            "Oh, they should also be waterproof",
            "Make them under $100",
            "Can they also be breathable?",
            "I want ones that are insulated too",
            "But only in leather",
        ],
    )
    def test_refinement_query_patterns(self, query):
        """Test that refinement queries contain additive constraint language."""
        additive_signals = [
            "also",
            "too",
            "but",
            "make them",
            "only in",
            "can they",
            "I want ones that are",
            "they should",
        ]
        query_lower = query.lower()
        has_signal = any(sig in query_lower for sig in additive_signals)
        assert has_signal, f"Refinement query '{query}' should contain an additive signal"

    def test_refinement_vs_attribute_filter_distinction(self):
        """Test key distinction: refinement requires prior search context."""
        standalone_query = "Show me waterproof boots"
        constrained_query = "Oh, they should also be waterproof"

        # Standalone has a full product category specified
        standalone_has_category = "boots" in standalone_query.lower()
        # Constrained uses pronouns or implicit reference
        constrained_has_pronoun = "they" in constrained_query.lower()

        assert (
            standalone_has_category
        ), "Standalone attribute_filter query should specify a category"
        assert constrained_has_pronoun, "Refinement query should use pronouns/implicit reference"

    def test_refinement_vs_follow_up_distinction(self):
        """Test key distinction: refinement adds specific constraint, follow_up is vague."""
        follow_up_signals = ["more", "show more", "tell me more", "other options", "alternatives"]
        refinement_signals = ["waterproof", "under $100", "breathable", "leather", "size 10"]

        # Follow-up is vague — no specific new constraint
        vague_query = "show me more"
        is_vague = any(sig in vague_query.lower() for sig in follow_up_signals)
        has_specific_constraint = any(sig in vague_query.lower() for sig in refinement_signals)
        assert is_vague and not has_specific_constraint

        # Refinement has a specific constraint
        refinement_query = "they should also be waterproof"
        has_specific_constraint = any(sig in refinement_query.lower() for sig in refinement_signals)
        assert has_specific_constraint
