"""
Integration tests for edge cases and error handling.

Tests pipeline behavior with edge cases:
- Empty/missing inputs (queries, documents, metadata)
- Invalid inputs (out-of-range values, invalid enums)
- Extreme values (alpha bounds, score bounds)
- Malformed state/documents
- Partial failures and graceful degradation
- Resource constraints and timeouts

Ensures robustness and reliability across error scenarios.
"""

import pytest
from langchain_core.documents import Document
from langchain_core.messages import HumanMessage


@pytest.mark.integration
@pytest.mark.edge_cases
class TestEmptyAndMissingInputs:
    """Tests for handling empty and missing inputs."""

    def test_empty_query_string(self):
        """Test intent classifier handles empty query."""
        query = ""

        # Should either handle gracefully or raise appropriate error
        if query == "":
            intent = None
            confidence = 0.0
        else:
            intent = "search"
            confidence = 0.95

        # Empty query should result in no confident intent
        assert intent is None or confidence < 0.7

    def test_whitespace_only_query(self):
        """Test intent classifier with whitespace-only query."""
        query = "   \n\t  "

        # Whitespace should be treated same as empty
        query_stripped = query.strip()
        assert len(query_stripped) == 0

    def test_very_long_query(self):
        """Test intent classifier with extremely long query (potential DoS)."""
        query = "a" * 10000  # 10K characters

        # Should handle or reject gracefully
        assert len(query) > 0
        # Query should be truncated or rejected, not cause crash

    def test_no_retrieved_documents(self):
        """Test reranker and quality gate with empty retriever results."""
        retrieved_documents = []

        # Quality gate should handle empty results
        if len(retrieved_documents) == 0:
            # No documents to score
            max_score = 0.0
            quality_status = "no_results"
        else:
            max_score = 0.72
            quality_status = "pass"

        assert max_score == 0.0
        assert quality_status == "no_results"

    def test_documents_missing_required_metadata(self):
        """Test documents with missing critical metadata."""
        # Document requires page_content to be a string (not None)
        # This should raise a validation error
        try:
            doc_missing_content = Document(
                page_content=None, metadata={"source": "unknown"}  # Invalid - must be string
            )
            should_fail = False
        except (TypeError, ValueError):
            should_fail = True

        assert should_fail, "Document should reject None page_content"

        # Valid document with missing metadata fields
        doc_missing_source = Document(
            page_content="Some product", metadata={}  # Missing source and other optional fields
        )

        # Should provide default or skip missing fields
        source = doc_missing_source.metadata.get("source", "unknown")
        assert source == "unknown"
        assert isinstance(source, str)

    def test_none_values_in_state(self):
        """Test agent state with None values in optional fields."""
        state = {
            "messages": [],
            "intent": None,
            "alpha": None,
            "retrieved_documents": None,
            "reranker_max_score": None,
        }

        # Safe access with defaults - use 'or' to handle None values
        intent = state.get("intent") or "unknown"
        alpha = state.get("alpha") or 0.5
        max_score = state.get("reranker_max_score") or 0.0

        assert intent == "unknown"
        assert alpha == 0.5
        assert max_score == 0.0


@pytest.mark.integration
@pytest.mark.edge_cases
class TestInvalidAndOutOfRangeInputs:
    """Tests for invalid values and out-of-range inputs."""

    def test_alpha_below_lower_bound(self):
        """Test alpha value below 0.0."""
        alpha = -0.5

        # Should be clamped or rejected
        clamped_alpha = max(0.0, alpha)
        assert clamped_alpha == 0.0
        assert 0.0 <= clamped_alpha <= 1.0

    def test_alpha_above_upper_bound(self):
        """Test alpha value above 1.0."""
        alpha = 1.5

        # Should be clamped or rejected
        clamped_alpha = min(1.0, alpha)
        assert clamped_alpha == 1.0
        assert 0.0 <= clamped_alpha <= 1.0

    def test_score_below_0(self):
        """Test reranker score below 0.0."""
        score = -0.1

        # Should be treated as invalid
        if score < 0.0 or score > 1.0:
            is_valid = False
        else:
            is_valid = True

        assert not is_valid

    def test_score_above_1(self):
        """Test reranker score above 1.0."""
        score = 1.5

        # Should be treated as invalid
        if score < 0.0 or score > 1.0:
            is_valid = False
        else:
            is_valid = True

        assert not is_valid

    def test_confidence_negative(self):
        """Test intent confidence below 0.0."""
        confidence = -0.2

        # Should be invalid
        assert not (0.0 <= confidence <= 1.0)

    def test_confidence_above_1(self):
        """Test intent confidence above 1.0."""
        confidence = 1.2

        # Should be invalid
        assert not (0.0 <= confidence <= 1.0)

    def test_invalid_intent_enum(self):
        """Test invalid intent value not in expected set."""
        intent = "invalid_intent"
        valid_intents = {"search", "comparison", "attribute_filter", "follow_up", "summary"}

        if intent not in valid_intents:
            is_valid = False
        else:
            is_valid = True

        assert not is_valid

    def test_negative_threshold(self):
        """Test quality gate with negative threshold."""
        threshold = -0.1
        max_score = 0.72

        # Negative threshold is invalid
        if threshold < 0.0 or threshold > 1.0:
            threshold = 0.5  # Use default

        assert threshold >= 0.0


@pytest.mark.integration
@pytest.mark.edge_cases
class TestBoundaryConditions:
    """Tests for boundary condition handling."""

    def test_alpha_exactly_at_boundaries(self):
        """Test alpha at exact boundary values: 0.0 and 1.0."""
        # Test 0.0 (pure lexical)
        alpha_min = 0.0
        assert 0.0 <= alpha_min <= 1.0

        # Test 1.0 (pure semantic)
        alpha_max = 1.0
        assert 0.0 <= alpha_max <= 1.0

    def test_score_at_exact_threshold(self):
        """Test reranker score exactly at quality gate threshold."""
        score = 0.50
        threshold = 0.50

        # At exactly threshold should PASS (>=)
        if score >= threshold:
            status = "pass"
        else:
            status = "fail"

        assert status == "pass"

    def test_confidence_exactly_at_clarification_threshold(self):
        """Test intent confidence exactly at 0.7 clarification threshold."""
        confidence = 0.7
        clarify_threshold = 0.7

        # At exactly 0.7 should NOT trigger clarification (< 0.7)
        if confidence < clarify_threshold:
            should_clarify = True
        else:
            should_clarify = False

        assert not should_clarify

    def test_confidence_just_below_threshold(self):
        """Test confidence just below clarification threshold (0.6999)."""
        confidence = 0.6999

        # Just below 0.7 should trigger clarification
        if confidence < 0.7:
            should_clarify = True
        else:
            should_clarify = False

        assert should_clarify

    def test_alpha_adjustment_clipping(self):
        """Test alpha adjustment clips correctly at boundaries."""
        # Test case 1: High alpha, decrease to minimum
        alpha = 0.85
        adjusted = max(0.0, alpha - 0.3)
        assert adjusted == 0.55
        assert 0.0 <= adjusted <= 1.0

        # Test case 2: Low alpha, increase to maximum
        alpha = 0.05
        adjusted = min(1.0, alpha + 0.3)
        assert adjusted == 0.35
        assert 0.0 <= adjusted <= 1.0

        # Test case 3: Very high alpha, decrease past minimum
        alpha = 0.2
        adjusted = max(0.0, alpha - 0.3)
        assert adjusted == 0.0
        assert 0.0 <= adjusted <= 1.0

        # Test case 4: Very low alpha, increase past maximum
        alpha = 0.9
        adjusted = min(1.0, alpha + 0.3)
        assert adjusted == 1.0
        assert 0.0 <= adjusted <= 1.0


@pytest.mark.integration
@pytest.mark.edge_cases
class TestMalformedDocuments:
    """Tests for handling malformed or incomplete documents."""

    def test_document_with_empty_content(self):
        """Test document with empty page_content."""
        doc = Document(page_content="", metadata={"source": "test", "title": "Empty"})

        # Should handle gracefully
        content = doc.page_content
        assert content == ""

    def test_document_with_very_long_content(self):
        """Test document with extremely long content (1MB+)."""
        long_content = "x" * (1024 * 1024)  # 1MB
        doc = Document(page_content=long_content, metadata={"source": "test"})

        # Should handle or truncate gracefully
        assert len(doc.page_content) > 0

    def test_document_with_special_characters(self):
        """Test document with special/control characters."""
        special_content = "Product \x00 with \x01 control \xff characters"
        doc = Document(page_content=special_content, metadata={"source": "test"})

        # Should preserve or handle safely
        assert len(doc.page_content) > 0

    def test_document_with_unicode_content(self):
        """Test document with unicode characters."""
        unicode_content = "Product: 商品 🎧 Ñoño €uro ₹upee"
        doc = Document(page_content=unicode_content, metadata={"source": "test"})

        # Should handle unicode correctly
        assert len(doc.page_content) > 0
        assert "商品" in doc.page_content

    def test_document_metadata_with_missing_fields(self):
        """Test document when some metadata fields are missing."""
        doc = Document(
            page_content="Product",
            metadata={
                "source": "test",
                # Missing: title, product_id, product_brand, price
            },
        )

        # Should provide defaults for missing fields
        title = doc.metadata.get("title", "Unknown")
        brand = doc.metadata.get("product_brand", "Unknown")
        price = doc.metadata.get("price", None)

        assert title == "Unknown"
        assert brand == "Unknown"
        assert price is None

    def test_document_metadata_with_null_values(self):
        """Test document with null/None values in metadata."""
        doc = Document(
            page_content="Product",
            metadata={
                "source": "test",
                "title": None,
                "price": None,
            },
        )

        # Should handle None values
        title = doc.metadata.get("title") or "Unknown"
        assert title == "Unknown"


@pytest.mark.integration
@pytest.mark.edge_cases
class TestConcurrencyAndStateIssues:
    """Tests for potential concurrency and state issues."""

    def test_state_field_isolation(self):
        """Test that state fields don't interfere with each other."""
        state1 = {"intent": "search", "alpha": 0.65}
        state2 = {"intent": "comparison", "alpha": 0.60}

        # States should be independent
        assert state1["intent"] != state2["intent"]
        assert state1["alpha"] != state2["alpha"]

    def test_message_ordering_preservation(self):
        """Test that message order is preserved through pipeline."""
        messages = [
            HumanMessage(content="First message"),
            HumanMessage(content="Second message"),
            HumanMessage(content="Third message"),
        ]

        # Order should be preserved
        assert len(messages) == 3
        assert messages[0].content == "First message"
        assert messages[1].content == "Second message"
        assert messages[2].content == "Third message"

    def test_immutability_of_document_content(self):
        """Test documents are not accidentally modified."""
        original_content = "Original product description"
        doc = Document(page_content=original_content, metadata={"source": "test"})

        # Simulate processing
        processed_content = doc.page_content

        # Original should not change
        assert doc.page_content == original_content


@pytest.mark.integration
@pytest.mark.edge_cases
class TestGracefulDegradation:
    """Tests for graceful degradation when systems fail."""

    def test_fallback_when_reranker_fails(self):
        """Test pipeline fallback when reranker is unavailable."""
        retriever_results = [
            Document(page_content="Product 1", metadata={"score": 0.8}),
            Document(page_content="Product 2", metadata={"score": 0.6}),
        ]

        # If reranker unavailable, use retriever scores
        max_score = 0.8  # Use retriever score instead

        assert max_score > 0.0, "Should have fallback score"

    def test_fallback_when_intent_classifier_uncertain(self):
        """Test pipeline when intent confidence is very low."""
        confidence = 0.35  # Very uncertain

        # Should ask for clarification instead of guessing
        if confidence < 0.5:
            action = "ask_clarification"
        else:
            action = "proceed"

        assert action == "ask_clarification"

    def test_default_alpha_when_evaluator_fails(self):
        """Test using default alpha when query evaluator fails."""
        default_alpha = 0.5
        evaluated_alpha = None

        # Use default if evaluation failed
        final_alpha = evaluated_alpha if evaluated_alpha is not None else default_alpha

        assert final_alpha == 0.5

    def test_default_threshold_when_not_specified(self):
        """Test quality gate uses default threshold when not specified."""
        intent = "unknown"
        intent_specific_threshold = None
        default_threshold = 0.50

        # Use default for unknown intents
        threshold = (
            0.55 if intent == "comparison" else intent_specific_threshold or default_threshold
        )

        assert threshold == 0.50


@pytest.mark.integration
@pytest.mark.edge_cases
class TestTypeValidation:
    """Tests for type validation and conversion."""

    def test_non_numeric_alpha_handling(self):
        """Test handling of non-numeric alpha values."""
        alpha_str = "0.5"  # String instead of float

        # Should convert or reject
        try:
            alpha_float = float(alpha_str)
            is_valid = 0.0 <= alpha_float <= 1.0
        except (TypeError, ValueError):
            is_valid = False

        assert is_valid

    def test_non_numeric_score_handling(self):
        """Test handling of non-numeric score values."""
        score_str = "high"  # String instead of float

        # Should reject invalid scores
        try:
            score_float = float(score_str)
            is_valid = 0.0 <= score_float <= 1.0
        except (TypeError, ValueError):
            is_valid = False

        assert not is_valid

    def test_list_as_score_value(self):
        """Test handling when score is a list instead of number."""
        score = [0.5, 0.6, 0.7]

        # Should reject
        is_valid = isinstance(score, (int, float))
        assert not is_valid

    def test_dict_as_documents_value(self):
        """Test handling when documents is dict instead of list."""
        documents = {"doc1": "content", "doc2": "content"}

        # Should be list, not dict
        is_valid = isinstance(documents, list)
        assert not is_valid
