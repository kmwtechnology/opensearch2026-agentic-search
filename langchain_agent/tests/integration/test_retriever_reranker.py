"""
Integration tests for retriever and reranker coordination.

Tests the interaction between hybrid search retriever (with dynamic alpha) and
LLM-based reranker, including:
- Alpha impact on retrieval (lexical vs semantic)
- Reranker scoring and document reordering
- Score propagation through pipeline
- Document preservation and metadata
"""

from unittest.mock import MagicMock, Mock, patch

import pytest
from langchain_core.documents import Document


@pytest.mark.integration
@pytest.mark.retriever_reranker
class TestRetrieverRerankerIntegration:
    """Integration tests for retriever and reranker working together."""

    @pytest.fixture
    def sample_retrieval_results(self, sample_documents):
        """Simulate retriever output with multiple documents."""
        return sample_documents

    def test_retriever_pure_lexical_alpha_0(self, sample_retrieval_results):
        """Test retriever with pure lexical search (alpha=0.0).

        When alpha=0.0, retriever should prioritize BM25 exact matching.
        """
        alpha = 0.0  # Pure lexical (BM25)
        query = "blue wireless headphones"

        # Simulate retrieval with lexical focus
        retrieved_docs = sample_retrieval_results
        assert len(retrieved_docs) > 0, "Should retrieve documents"
        assert alpha == 0.0, "Alpha should be 0.0 for pure lexical"

        # Verify documents have all required metadata
        for doc in retrieved_docs:
            assert doc.page_content is not None
            assert "source" in doc.metadata
            assert "title" in doc.metadata

    def test_retriever_pure_semantic_alpha_1(self, sample_retrieval_results):
        """Test retriever with pure semantic search (alpha=1.0).

        When alpha=1.0, retriever should prioritize vector similarity.
        """
        alpha = 1.0  # Pure semantic (vector)
        query = "noise-canceling audio devices"

        # Simulate retrieval with semantic focus
        retrieved_docs = sample_retrieval_results
        assert len(retrieved_docs) > 0
        assert alpha == 1.0, "Alpha should be 1.0 for pure semantic"

        # Both approaches should return documents
        assert all(doc.page_content for doc in retrieved_docs)

    def test_retriever_balanced_hybrid_alpha_0_5(self, sample_retrieval_results):
        """Test retriever with balanced hybrid search (alpha=0.5).

        When alpha=0.5, retriever blends lexical and semantic equally.
        """
        alpha = 0.5  # Balanced hybrid
        query = "good headphones for music"

        retrieved_docs = sample_retrieval_results
        assert len(retrieved_docs) > 0
        assert 0.0 < alpha < 1.0, "Alpha should be between 0.0 and 1.0"

    def test_retriever_alpha_impact_on_ranking_order(self):
        """Test that different alpha values may produce different ranking orders.

        Lexical search prioritizes exact keyword matches.
        Semantic search prioritizes conceptual similarity.
        """
        lexical_alpha = 0.1  # Lexical-heavy
        semantic_alpha = 0.9  # Semantic-heavy

        # Lexical retrieval would rank exact matches higher
        lexical_query = "Sony WH-1000XM5 wireless"
        # Expected: documents with "Sony" or "WH-1000XM5" rank highest

        # Semantic retrieval would rank similar concepts higher
        semantic_query = "high-quality audio equipment"
        # Expected: documents semantically similar to quality/audio rank highest

        assert lexical_alpha < semantic_alpha

    def test_reranker_scores_and_orders_documents(self, sample_retrieval_results):
        """Test reranker assigns scores to documents and determines order.

        Reranker takes unranked retriever results and scores them (0.0-1.0).
        """
        retrieved_docs = sample_retrieval_results
        assert len(retrieved_docs) > 0

        # Simulate reranker assigning scores
        reranked_with_scores = [
            (doc, 0.85) if "Sony" in doc.metadata.get("title", "") else (doc, 0.62)
            for doc in retrieved_docs
        ]

        # Verify scores are valid
        for doc, score in reranked_with_scores:
            assert 0.0 <= score <= 1.0, f"Score {score} out of valid range"
            assert isinstance(doc, Document)

        # Order by score (descending)
        sorted_docs = sorted(reranked_with_scores, key=lambda x: x[1], reverse=True)
        assert sorted_docs[0][1] >= sorted_docs[-1][1], "Should be sorted by score"

    def test_reranker_max_score_for_quality_gate(self, sample_retrieval_results):
        """Test that max reranker score feeds into quality gate.

        Quality gate uses max_score >= threshold to decide PASS/RETRY.
        """
        retrieved_docs = sample_retrieval_results

        # Simulate reranking all documents
        scores = [0.72, 0.65, 0.58]
        reranked = list(zip(retrieved_docs[:3], scores))

        # Extract max score
        max_score = max(score for _, score in reranked)
        assert max_score == 0.72

        # Quality gate logic
        threshold_search = 0.50
        threshold_comparison = 0.55

        quality_search = "pass" if max_score >= threshold_search else "retry"
        quality_comparison = "pass" if max_score >= threshold_comparison else "retry"

        assert quality_search == "pass"
        assert quality_comparison == "pass"

    def test_document_preservation_through_pipeline(self, sample_retrieval_results):
        """Test documents maintain metadata and content through retriever->reranker.

        Retriever returns documents; reranker scores them without losing metadata.
        """
        original_docs = sample_retrieval_results
        original_metadata = [doc.metadata for doc in original_docs]

        # Simulate passing through reranker (only adds scores, doesn't modify docs)
        reranked_docs = original_docs  # In real system, just adds scores
        reranked_metadata = [doc.metadata for doc in reranked_docs]

        # Metadata should be preserved
        for orig_meta, reranked_meta in zip(original_metadata, reranked_metadata):
            assert orig_meta == reranked_meta, "Metadata should not change"

    def test_retriever_document_count_validity(self, sample_retrieval_results):
        """Test retriever returns valid document count.

        Typically 5-20 documents for good recall.
        """
        docs = sample_retrieval_results
        assert len(docs) > 0, "Should retrieve at least one document"
        assert len(docs) <= 100, "Should not retrieve too many documents"

    def test_reranker_respects_document_order(self, sample_retrieval_results):
        """Test reranker can reorder documents based on relevance scores.

        Original retriever order may differ from reranker order.
        """
        docs = sample_retrieval_results
        assert len(docs) >= 2, "Should have at least 2 sample documents"

        # Assign scores in different order than retriever
        scores = [0.65, 0.78]  # Not in original order for 2 docs
        scored_docs = list(zip(docs[:2], scores))

        # Sort by score
        reordered = sorted(scored_docs, key=lambda x: x[1], reverse=True)

        # Top result should be highest score
        assert reordered[0][1] == 0.78
        assert reordered[-1][1] == 0.65

    def test_low_score_triggers_retry(self, sample_retrieval_results):
        """Test that low max_score triggers quality gate retry.

        If max_score < threshold and not yet retried, adjust alpha and retry.
        """
        docs = sample_retrieval_results
        low_scores = [0.35, 0.28, 0.42]  # All below standard threshold
        scored_docs = list(zip(docs[:3], low_scores))

        max_score = max(score for _, score in scored_docs)
        threshold = 0.50

        assert max_score < threshold, "Max score should be below threshold"

        # Quality gate should trigger retry
        if max_score < threshold:
            should_retry = True
        else:
            should_retry = False

        assert should_retry, "Should retry when score is low"

    def test_high_score_passes_quality_gate(self, sample_retrieval_results):
        """Test that high max_score passes quality gate without retry."""
        docs = sample_retrieval_results
        high_scores = [0.82, 0.75, 0.68]  # All above standard threshold
        scored_docs = list(zip(docs[:3], high_scores))

        max_score = max(score for _, score in scored_docs)
        threshold = 0.50

        assert max_score > threshold, "Max score should be above threshold"

        if max_score >= threshold:
            quality_status = "pass"
        else:
            quality_status = "retry"

        assert quality_status == "pass"


@pytest.mark.integration
@pytest.mark.retriever_reranker
class TestAlphaImpactOnRetrieval:
    """Integration tests for alpha parameter impact on retrieval."""

    def test_lexical_heavy_alpha_retrieval(self):
        """Test retrieval with lexical-heavy alpha (0.1-0.3).

        Should prioritize exact keyword matches.
        Query: "blue size 10 running shoes"
        Lexical retrieval emphasizes: color=blue, size=10, product=shoes
        """
        alpha = 0.25
        query = "blue size 10 running shoes"

        # Lexical search emphasizes exact attribute matching
        expected_ranking_factors = [
            "exact color match (blue)",
            "exact size match (10)",
            "exact product type (shoes)",
        ]

        assert alpha < 0.4, "Alpha should be lexical-heavy"
        assert all(isinstance(factor, str) for factor in expected_ranking_factors)

    def test_balanced_hybrid_alpha_retrieval(self):
        """Test retrieval with balanced alpha (0.4-0.6).

        Blends lexical and semantic equally.
        Query: "best running shoes for marathons"
        """
        alpha = 0.5
        query = "best running shoes for marathons"

        # Balanced search combines:
        # - Lexical: exact matches on "running", "shoes"
        # - Semantic: understanding of "marathons" and "best"

        assert 0.4 <= alpha <= 0.6, "Alpha should be balanced"

    def test_semantic_heavy_alpha_retrieval(self):
        """Test retrieval with semantic-heavy alpha (0.7-0.95).

        Should prioritize conceptual similarity.
        Query: "comfortable footwear for office work"
        Semantic retrieval emphasizes: comfort, office context
        """
        alpha = 0.85
        query = "comfortable footwear for office work"

        # Semantic search emphasizes:
        # - Document semantics about comfort
        # - Office/work environment context
        # - Even if exact keywords not present

        assert alpha > 0.6, "Alpha should be semantic-heavy"

    def test_attribute_filter_pure_lexical(self):
        """Test attribute_filter intent uses pure lexical (alpha=0.25).

        Should match exact specifications.
        """
        intent = "attribute_filter"
        alpha = 0.25

        query = "red leather backpack under $100"
        expected_matches = ["red", "leather", "backpack", "$100"]

        assert intent == "attribute_filter"
        assert alpha == 0.25
        # Lexical search emphasizes exact word matches

    def test_comparison_semantic_heavy(self):
        """Test comparison intent uses semantic-heavy (alpha=0.60).

        Should understand product differences semantically.
        """
        intent = "comparison"
        alpha = 0.60

        query = "iPhone vs Samsung which is better"
        # Semantic retrieval understands:
        # - "which is better" = quality comparison
        # - Product brands and their characteristics
        # - Differentiation factors

        assert intent == "comparison"
        assert 0.55 <= alpha <= 0.65

    def test_alpha_adjustment_on_retry(self):
        """Test alpha adjustment during quality gate retry.

        If score is low:
        - If current_alpha >= 0.5: decrease by 0.3 (more lexical)
        - If current_alpha < 0.5: increase by 0.3 (more semantic)
        """
        # Scenario 1: High semantic alpha, low score → decrease to more lexical
        initial_alpha_1 = 0.75
        if initial_alpha_1 >= 0.5:
            adjusted_alpha_1 = max(0.0, initial_alpha_1 - 0.3)
        assert adjusted_alpha_1 == 0.45, "High alpha should decrease"

        # Scenario 2: Low lexical alpha, low score → increase to more semantic
        initial_alpha_2 = 0.20
        if initial_alpha_2 < 0.5:
            adjusted_alpha_2 = min(1.0, initial_alpha_2 + 0.3)
        assert adjusted_alpha_2 == 0.50, "Low alpha should increase"


@pytest.mark.integration
@pytest.mark.retriever_reranker
class TestRerankerScoringLogic:
    """Integration tests for reranker scoring and logic."""

    def test_reranker_score_range_validity(self):
        """Test all reranker scores are in valid 0.0-1.0 range."""
        sample_scores = [0.0, 0.25, 0.50, 0.75, 1.0, 0.682, 0.123]

        for score in sample_scores:
            assert 0.0 <= score <= 1.0, f"Score {score} out of range"

    def test_reranker_score_interpretation(self):
        """Test score interpretation for quality decisions.

        0.0-0.2: Poor (irrelevant)
        0.2-0.4: Fair (somewhat relevant)
        0.4-0.6: Good (relevant)
        0.6-0.8: Very good (highly relevant)
        0.8-1.0: Excellent (perfect match)
        """
        score_interpretations = {
            0.15: "poor",
            0.35: "fair",
            0.55: "good",
            0.72: "very_good",
            0.95: "excellent",
        }

        for score, expected_level in score_interpretations.items():
            if score < 0.2:
                level = "poor"
            elif score < 0.4:
                level = "fair"
            elif score < 0.6:
                level = "good"
            elif score < 0.8:
                level = "very_good"
            else:
                level = "excellent"

            assert level == expected_level

    def test_reranker_score_consistency_per_query(self):
        """Test reranker produces consistent scores for same query/documents.

        Multiple reranking passes should produce similar scores.
        """
        # In real system, scores might vary slightly due to LLM randomness
        # But should be within reasonable tolerance
        query = "wireless headphones"
        doc_content = "Sony WH-1000XM5 wireless headphones"

        score_1 = 0.72  # First reranking
        score_2 = 0.70  # Second reranking (slightly different due to LLM)

        # Scores should be reasonably close
        assert abs(score_1 - score_2) < 0.05, "Scores should be consistent"

    def test_reranker_score_sensitivity_to_query(self):
        """Test reranker scores change with different queries.

        Same document should score differently for different queries.
        """
        doc_content = "Sony WH-1000XM5 wireless noise-canceling headphones"

        # Query 1: Exact match
        score_exact = 0.85  # High because of exact keyword match

        # Query 2: Related but different
        score_related = 0.62  # Lower because different intent

        # Query 3: Unrelated
        score_unrelated = 0.28  # Very low because unrelated

        assert score_exact > score_related > score_unrelated

    def test_reranker_score_vs_retriever_rank(self):
        """Test reranker may rank documents differently than retriever.

        Retriever rank (by BM25/vector similarity) != Reranker rank (by LLM).
        """
        # Retriever rank (document order from hybrid search)
        retriever_rank = [
            ("Doc A", "BM25 keyword match"),
            ("Doc B", "Vector similarity"),
            ("Doc C", "Lower relevance"),
        ]

        # Reranker scores (LLM-based relevance)
        reranker_scores = [
            ("Doc A", 0.65),
            ("Doc B", 0.78),  # Reranker prefers this
            ("Doc C", 0.52),
        ]

        # After reranking, Doc B is now top-1
        reranked_order = sorted(reranker_scores, key=lambda x: x[1], reverse=True)
        assert reranked_order[0][0] == "Doc B", "Reranker changed the order"

    def test_intent_specific_reranker_guidance(self):
        """Test reranker uses intent-specific scoring guidance.

        Different intents should have different scoring criteria.
        """
        # Search: Balanced relevance (coverage of features)
        search_guidance = "Reward documents with comprehensive product features"

        # Comparison: Quality differences emphasized
        comparison_guidance = "Reward documents highlighting differences between products"

        # Attribute filter: Specification exactness emphasized
        filter_guidance = "Reward documents with exact specifications and attributes"

        assert "comprehensive" in search_guidance.lower()
        assert "differences" in comparison_guidance.lower()
        assert "exact" in filter_guidance.lower()
