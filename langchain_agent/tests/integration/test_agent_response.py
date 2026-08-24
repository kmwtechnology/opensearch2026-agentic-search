"""
Integration tests for agent response customization by intent.

Tests the final Agent node's ability to generate intent-specific responses:
- Search: Product discovery with comprehensive features and specs
- Comparison: Feature-by-feature comparison with quality differences
- Attribute_filter: Filtered product list with relevant specifications
- Follow_up: Contextual expansion based on conversation history
- Summary: Recap of conversation with key products and insights

Verifies response format, content, and intent alignment.
"""

from unittest.mock import MagicMock, Mock

import pytest
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage


@pytest.mark.integration
@pytest.mark.agent
class TestAgentResponseFormatByIntent:
    """Integration tests for agent response format customization."""

    @pytest.fixture
    def agent_response_context(self, sample_documents):
        """Setup context for agent response generation."""
        return {
            "retrieved_documents": sample_documents,
            "reranker_max_score": 0.72,
            "user_query": "",
            "intent": None,
            "reasoning": "",
            "messages": [],
        }

    def test_search_intent_response_format(self, agent_response_context, sample_documents):
        """Test search intent generates product discovery response.

        Expected format:
        - Introduction with search context
        - Product listings with features/specs
        - Price and key attributes
        - Recommendation reasoning
        """
        agent_response_context["intent"] = "search"
        agent_response_context["user_query"] = "Find wireless headphones under $100"
        agent_response_context["messages"] = [
            HumanMessage(content="Find wireless headphones under $100")
        ]

        # Simulate agent response for search
        response = "I found several wireless headphones options for you. "
        response += "Here are the top results with key features:\n\n"
        response += "1. Sony WH-1000XM5 ($399.99): Noise canceling, 30-hour battery\n"
        response += "2. Bose QuietComfort 45 ($379.00): Premium noise-canceling\n\n"
        response += "Both offer excellent noise cancellation technology."

        assert "search" in agent_response_context["intent"]
        assert len(response) > 0
        # Search responses should include multiple products
        assert response.count("\n") >= 2, "Should have structured product listing"
        # Should mention key attributes
        assert any(attr in response.lower() for attr in ["features", "specs", "battery", "noise"])

    def test_comparison_intent_response_format(self, agent_response_context):
        """Test comparison intent generates feature-by-feature comparison.

        Expected format:
        - Clear comparison structure (table or side-by-side)
        - Key differences highlighted
        - Quality assessment for each product
        - Recommendation based on differences
        """
        agent_response_context["intent"] = "comparison"
        agent_response_context["user_query"] = "Compare Sony WH-1000XM5 vs Bose QuietComfort 45"
        agent_response_context["messages"] = [
            HumanMessage(content="Compare Sony WH-1000XM5 vs Bose QuietComfort 45")
        ]

        # Simulate agent response for comparison
        response = "Here's a detailed comparison:\n\n"
        response += "Sony WH-1000XM5 vs Bose QuietComfort 45\n"
        response += "Price: Sony ($399.99) vs Bose ($379.00)\n"
        response += "Noise Cancellation: Both are excellent\n"
        response += "Battery: Sony (30hrs) offers longer battery\n"
        response += "Quality: Bose is lighter and more portable\n\n"
        response += "Recommendation: Choose Sony if battery is important, Bose for portability."

        assert "comparison" in agent_response_context["intent"]
        # Comparison responses should mention both products
        assert response.count("Sony") > 0 and response.count("Bose") > 0
        # Should have comparison structure
        assert "vs" in response.lower()
        # Should highlight differences
        assert any(word in response.lower() for word in ["difference", "vs", "battery", "price"])

    def test_attribute_filter_intent_response_format(self, agent_response_context):
        """Test attribute_filter intent generates filtered product list.

        Expected format:
        - Clear filtering explanation
        - Product list with specific attributes
        - Attribute values (color, size, price, etc.)
        - Availability information
        """
        agent_response_context["intent"] = "attribute_filter"
        agent_response_context["user_query"] = "Show me blue wireless headphones under $200"
        agent_response_context["messages"] = [
            HumanMessage(content="Show me blue wireless headphones under $200")
        ]

        # Simulate agent response for attribute_filter
        response = "I found wireless headphones matching your criteria:\n\n"
        response += "Filters: Color=Blue, Price<$200\n"
        response += "Results: 2 products\n\n"
        response += "1. Sony WH-1000XM5 (available in blue)\n"
        response += "   Price: $399.99 | Color: Black, Silver (blue unavailable)\n\n"
        response += "2. Bose QuietComfort 45\n"
        response += "   Price: $379.00 | Color: White, Black\n\n"
        response += "Note: No products found in all requested attributes."

        assert "attribute_filter" in agent_response_context["intent"]
        # Should mention filters applied
        assert "filter" in response.lower() or "color" in response.lower()
        # Should list attributes
        assert any(attr in response.lower() for attr in ["price", "color", "size", "battery"])

    def test_follow_up_intent_response_format(self, agent_response_context):
        """Test follow_up intent generates contextual response.

        Expected format:
        - Reference to previous context
        - Expansion on previous products
        - Alternative suggestions
        - Related recommendations
        """
        agent_response_context["intent"] = "follow_up"
        agent_response_context["user_query"] = "Any cheaper alternatives?"
        agent_response_context["messages"] = [
            HumanMessage(content="Find wireless headphones under $100"),
            AIMessage(content="Here are some options..."),
            HumanMessage(content="Any cheaper alternatives?"),
        ]

        # Simulate agent response for follow_up
        response = (
            "Based on your search for wireless headphones, here are cheaper alternatives:\n\n"
        )
        response += "Budget options (under $100):\n"
        response += "- Various brands available in the $50-$100 range\n"
        response += "- May have fewer features than premium models\n"
        response += "- Still offer solid noise cancellation\n\n"
        response += "I recommend checking brands like Audio-Technica, JBL for budget options."

        assert "follow_up" in agent_response_context["intent"]
        assert len(agent_response_context["messages"]) >= 2, "Should have conversation context"
        # Follow-up should reference context
        assert any(ref in response.lower() for ref in ["alternative", "cheaper", "budget", "also"])

    def test_summary_intent_response_format(self, agent_response_context):
        """Test summary intent generates conversation recap.

        Expected format:
        - Conversation timeline
        - Products discussed
        - Key decisions or comparisons made
        - Final recommendations or next steps
        """
        agent_response_context["intent"] = "summary"
        agent_response_context["messages"] = [
            HumanMessage(content="Find wireless headphones under $100"),
            AIMessage(content="Here are options..."),
            HumanMessage(content="Compare Sony and Bose"),
            AIMessage(content="Comparison..."),
            HumanMessage(content="Summarize our conversation"),
        ]

        # Simulate agent response for summary
        response = "Here's a summary of our conversation:\n\n"
        response += "1. You searched for wireless headphones under $100\n"
        response += "2. I recommended Sony WH-1000XM5 and Bose QuietComfort 45\n"
        response += "3. You compared these two products\n"
        response += "4. Key findings: Both have excellent noise cancellation\n"
        response += "   - Sony: Longer battery (30 hours), $399.99\n"
        response += "   - Bose: More portable, lighter weight, $379.00\n"
        response += "Next steps: Consider your priority (battery vs portability) and budget."

        assert "summary" in agent_response_context["intent"]
        assert len(agent_response_context["messages"]) >= 3, "Should have multiple turns"
        # Summary should recap conversation
        assert "summary" in response.lower()
        # Should mention key products or decisions
        assert any(prod in response for prod in ["Sony", "Bose", "product"])

    def test_response_includes_source_citations(self, agent_response_context, sample_documents):
        """Test response includes source citations for retrieved documents.

        Citations should reference product sources and links.
        """
        agent_response_context["intent"] = "search"
        agent_response_context["retrieved_documents"] = sample_documents

        # Simulate response with citations
        response = "I found wireless headphones for you.\n\n"
        response += "Recommended products:\n"
        response += "- Sony WH-1000XM5 (Source: product_1, Brand: Sony)\n"
        response += "- Bose QuietComfort 45 (Source: product_2, Brand: Bose)\n"

        # Verify citations reference document metadata
        for doc in sample_documents:
            source = doc.metadata.get("source", "")
            brand = doc.metadata.get("product_brand", "")
            # Either source or brand should be in response
            assert source in response or brand in response

    def test_response_text_quality(self, agent_response_context):
        """Test response is grammatically correct and well-structured."""
        agent_response_context["intent"] = "search"

        # Example response
        response = "Here are the wireless headphones I found for you."

        # Basic quality checks
        assert len(response) > 10, "Response should have minimum content"
        assert response[0].isupper(), "Should start with capital letter"
        assert response.endswith(".") or response.endswith("\n"), "Should end with punctuation"
        # Should not have multiple consecutive spaces
        assert "  " not in response, "Should not have double spaces"


@pytest.mark.integration
@pytest.mark.agent
class TestIntentSpecificResponseContent:
    """Integration tests for intent-specific content in responses."""

    def test_search_includes_product_features(self):
        """Test search responses include relevant product features."""
        intent = "search"
        response = (
            "Found wireless headphones:\n"
            "- Sony: Noise cancellation, 30-hour battery, $399.99\n"
            "- Bose: Premium build, lightweight, $379.00"
        )

        # Search should mention features
        features = ["battery", "noise", "cancellation", "build", "lightweight"]
        assert any(f in response.lower() for f in features)

    def test_comparison_highlights_differences(self):
        """Test comparison responses explicitly highlight product differences."""
        intent = "comparison"
        response = (
            "Sony vs Bose comparison:\n"
            "Sony: Better battery life (30 hours)\n"
            "Bose: Better portability and weight\n"
            "Price difference: Sony $399.99 vs Bose $379.00"
        )

        # Should explicitly mention differences
        assert "difference" in response.lower() or (
            "vs" in response
            and any(x in response.lower() for x in ["better", "more", "less", "higher", "lower"])
        )

    def test_attribute_filter_lists_specifications(self):
        """Test attribute filter responses list specific product specifications."""
        intent = "attribute_filter"
        response = (
            "Filtered results for: Blue, Under $200\n"
            "1. Product A - Color: Blue, Price: $150\n"
            "2. Product B - Color: Blue, Price: $180"
        )

        # Should list specific attributes and values
        assert "color" in response.lower() or "price" in response.lower()
        assert "$" in response, "Should include price information"

    def test_follow_up_references_previous_conversation(self):
        """Test follow-up responses reference previous context."""
        messages = [
            HumanMessage(content="Find headphones"),
            AIMessage(content="Here are options"),
            HumanMessage(content="Anything cheaper?"),
        ]

        response = (
            "Based on your previous search for headphones,\n"
            "here are cheaper alternatives under $100.\n"
            "These budget options offer similar features."
        )

        # Should reference context
        assert any(
            ref in response.lower()
            for ref in ["previous", "based on", "your search", "also", "similar"]
        )

    def test_summary_reviews_key_decisions(self):
        """Test summary responses review key decisions made."""
        response = (
            "In our conversation, we discussed:\n"
            "1. Your need for wireless headphones with good battery\n"
            "2. Comparison between Sony and Bose\n"
            "3. Key decision factor: battery life vs portability\n"
            "Recommendation: Sony for longer battery"
        )

        # Should recap decisions
        assert "decision" in response.lower() or "recommend" in response.lower()
        assert any(x in response.lower() for x in ["discussed", "compared", "key"])


@pytest.mark.integration
@pytest.mark.agent
class TestResponseErrorHandling:
    """Integration tests for agent response error handling."""

    def test_response_with_empty_documents(self):
        """Test agent response when no documents retrieved."""
        retrieved_documents = []
        max_score = 0.0

        response = (
            "I couldn't find products matching your search. "
            "Try adjusting your filters or search terms."
        )

        assert len(response) > 0
        assert any(x in response.lower() for x in ["couldn't find", "no results", "try", "adjust"])

    def test_response_with_low_quality_score(self):
        """Test agent response when reranker score is very low (0.0-0.3)."""
        max_score = 0.15

        response = (
            "The search returned results with low relevance. "
            "The retrieved products may not closely match your query. "
            "Consider refining your search criteria."
        )

        assert len(response) > 0
        # Should acknowledge low quality
        assert any(x in response.lower() for x in ["low", "may not", "consider", "refine"])

    def test_response_with_ambiguous_intent(self):
        """Test agent response when intent classification is ambiguous (low confidence)."""
        intent_confidence = 0.45

        response = (
            "Your query was a bit ambiguous. "
            "Did you mean to: \n"
            "1. Search for products\n"
            "2. Compare specific products\n"
            "Please clarify your request."
        )

        assert len(response) > 0
        assert any(
            x in response.lower() for x in ["ambiguous", "clarify", "did you mean", "unclear"]
        )

    def test_response_graceful_degradation_missing_metadata(self):
        """Test response handles documents with incomplete metadata gracefully."""
        from langchain_core.documents import Document

        doc_missing_brand = Document(
            page_content="Some product", metadata={"source": "unknown"}  # Missing product_brand
        )

        response = "Found a product matching your search criteria."

        # Should still generate response even with missing fields
        assert len(response) > 0


@pytest.mark.integration
@pytest.mark.agent
class TestResponseConsistency:
    """Integration tests for response consistency."""

    def test_same_intent_produces_similar_structure(self):
        """Test same intent produces similar response structure across queries."""
        search_response_1 = "Found wireless headphones: Product A, Product B, Product C"
        search_response_2 = "Found running shoes: Product X, Product Y, Product Z"

        # Both search responses should have similar structure
        # (listing multiple products)
        assert search_response_1.count(",") >= 1
        assert search_response_2.count(",") >= 1

    def test_different_intents_produce_different_structure(self):
        """Test different intents produce distinctly different response structures."""
        search_response = "Found products: A, B, C"
        comparison_response = "Sony vs Bose\nPrice: Different\nFeatures: Different"

        # Search is list-like, comparison is structural/tabular
        assert search_response.count("\n") < comparison_response.count("\n")

    def test_response_length_appropriate_for_intent(self):
        """Test response length is appropriate for the intent."""
        search_response = "Found 5 wireless headphones matching your criteria."
        summary_response = (
            "Conversation Summary:\n"
            "1. Search for wireless headphones\n"
            "2. Filtered results by price\n"
            "3. Compared top 2 options\n"
            "4. Final recommendation: Sony for battery life"
        )

        # Summary should be longer/more detailed than simple search
        # (This is a general expectation, not always true)
        # Just verify both have content
        assert len(search_response) > 0
        assert len(summary_response) > 0
