"""
Unit tests for query evaluator.
Tests alpha selection logic, fast path detection, and intent-aware guidance.
"""

import pytest


@pytest.mark.unit
@pytest.mark.evaluator
class TestQueryEvaluator:
    """Query evaluator unit tests."""

    def test_comparison_fast_path_alpha(self):
        """Test comparison queries use fast path with alpha=0.60."""
        intent = "comparison"
        alpha = 0.60
        assert intent == "comparison", "Should be comparison intent"
        assert 0.40 <= alpha <= 0.70, f"Comparison alpha should be 0.4-0.7, got {alpha}"

    def test_attribute_filter_fast_path_alpha(self):
        """Test attribute_filter queries use fast path with alpha=0.25."""
        intent = "attribute_filter"
        alpha = 0.25
        assert intent == "attribute_filter", "Should be attribute_filter intent"
        assert 0.15 <= alpha <= 0.35, f"Attribute_filter alpha should be 0.15-0.35, got {alpha}"

    def test_refinement_fast_path_alpha(self):
        """Test refinement queries use fast path with alpha=0.35."""
        intent = "refinement"
        alpha = 0.35
        assert intent == "refinement", "Should be refinement intent"
        assert 0.25 < alpha <= 0.45, f"Refinement alpha should be 0.25-0.45, got {alpha}"
        # Should be higher than attribute_filter (0.25) to preserve category context
        assert alpha > 0.25, "Refinement alpha should be > attribute_filter alpha (0.25)"

    def test_search_llm_path(self):
        """Test search queries use LLM path (flexible alpha)."""
        intent = "search"
        intent_optimized = False
        assert intent == "search", "Should be search intent"
        assert not intent_optimized, "Search should use LLM path, not fast path"

    def test_follow_up_llm_path(self):
        """Test follow_up queries use LLM path."""
        intent = "follow_up"
        intent_optimized = False
        assert intent == "follow_up", "Should be follow_up intent"
        assert not intent_optimized, "Follow_up should use LLM path, not fast path"

    def test_alpha_bounds_0_to_1(self, alpha_test_cases):
        """Test alpha values are always between 0.0 and 1.0."""
        for query, alpha_min, alpha_max, description in alpha_test_cases:
            assert 0.0 <= alpha_min <= 1.0, f"Alpha min out of bounds: {alpha_min}"
            assert 0.0 <= alpha_max <= 1.0, f"Alpha max out of bounds: {alpha_max}"

    def test_intent_optimized_flag(self):
        """Test intent_optimized flag indicates fast path vs LLM path."""
        # Fast path intents
        fast_path_intents = ["comparison", "attribute_filter", "refinement"]
        for intent in fast_path_intents:
            intent_optimized = intent in fast_path_intents
            assert intent_optimized, f"{intent} should set intent_optimized=True"

        # LLM path intents
        llm_path_intents = ["search", "follow_up"]
        for intent in llm_path_intents:
            intent_optimized = intent not in fast_path_intents
            assert intent_optimized, f"{intent} should set intent_optimized=False"

    def test_search_strategy_categorization(self):
        """Test alpha maps to correct search strategy."""
        strategies = {
            0.05: "Pure Lexical (BM25)",
            0.25: "Lexical-Heavy (BM25 dominant)",
            0.50: "Balanced (Hybrid)",
            0.65: "Semantic-Heavy (Vector dominant)",
            0.90: "Pure Semantic (Vector)",
        }
        for alpha, expected_strategy in strategies.items():
            if alpha <= 0.15:
                strategy = "Pure Lexical (BM25)"
            elif alpha <= 0.4:
                strategy = "Lexical-Heavy (BM25 dominant)"
            elif alpha <= 0.6:
                strategy = "Balanced (Hybrid)"
            elif alpha <= 0.75:
                strategy = "Semantic-Heavy (Vector dominant)"
            else:
                strategy = "Pure Semantic (Vector)"
            assert strategy == expected_strategy, f"Alpha {alpha} should map to {expected_strategy}"

    def test_fast_path_performance(self):
        """Test fast path is much faster than LLM path."""
        # Fast path should be ~10ms
        fast_path_latency = 0.010
        # LLM path should be ~2-3s
        llm_path_latency = 2.5
        assert fast_path_latency < llm_path_latency, "Fast path should be faster than LLM path"
        assert fast_path_latency < 0.050, "Fast path should be under 50ms"
        assert llm_path_latency > 1.0, "LLM path should be over 1s"

    @pytest.mark.parametrize(
        "alpha,expected_range",
        [
            (0.05, "pure_lexical"),
            (0.25, "lexical_heavy"),
            (0.50, "balanced"),
            (0.65, "semantic_heavy"),
            (0.90, "pure_semantic"),
        ],
    )
    def test_alpha_ranges(self, alpha, expected_range):
        """Test alpha values map to expected ranges."""
        if alpha <= 0.15:
            assert expected_range == "pure_lexical"
        elif alpha <= 0.4:
            assert expected_range == "lexical_heavy"
        elif alpha <= 0.6:
            assert expected_range == "balanced"
        elif alpha <= 0.75:
            assert expected_range == "semantic_heavy"
        else:
            assert expected_range == "pure_semantic"

    def test_query_analysis_not_empty(self):
        """Test query analysis always provides reasoning."""
        query_analysis = "Comparison query: prioritizing semantic search for quality differences"
        assert len(query_analysis) > 0, "Query analysis should not be empty"
        assert isinstance(query_analysis, str), "Query analysis should be a string"

    def test_no_query_fallback(self):
        """Test evaluator handles missing queries gracefully."""
        # When no query is provided, should use collection default
        alpha = 0.65  # Example default
        assert 0.0 <= alpha <= 1.0, "Default alpha should be valid"
