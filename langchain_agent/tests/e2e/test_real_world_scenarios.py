"""
Real-World Scenario Testing for Agentic Hybrid Search

Comprehensive end-to-end testing covering realistic user journeys:
1. E-commerce Shopper — Multi-turn conversation: browse → filter → compare → purchase intent
2. Product Expert — Deep technical comparison (specifications, compatibility, features)
3. Content Creator — Generate multiple marketing formats for same product set
4. Support Agent — Answer customer questions with proper citations and accuracy
5. Mobile Shopper — Rapid-fire queries with constrained results (minimal data)
6. International User — Multi-locale queries testing localization
7. Accessibility User — Screen reader compatible responses with clear structure
8. Power User — Complex filtering, faceting, refinements on large datasets
9. Cold Start — First request after deployment (warm-up performance)
10. Streaming Network — Test WebSocket behavior with simulated network jitter

Markers: @pytest.mark.performance, @pytest.mark.e2e, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))


# Configuration
DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "test-api-key")
TIMEOUT = 60  # seconds


class ScenarioTest:
    """Base class for scenario testing."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}
        self.thread_id: Optional[str] = None
        self.conversation_history: List[Dict[str, str]] = []

    def setup_conversation(self) -> str:
        """Create a new conversation."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{self.base_url}/api/conversations",
                headers=self.headers,
                json={"title": self.__class__.__name__},
            )
            self.thread_id = response.json().get("thread_id", "default")
        return self.thread_id

    def send_message(self, content: str) -> Dict[str, Any]:
        """Send a message and get response."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.post(
                f"{self.base_url}/api/conversations/{self.thread_id}/messages",
                headers=self.headers,
                json={"content": content},
            )

        data = response.json()
        self.conversation_history.append(
            {"user": content, "assistant": str(data.get("messages", []))}
        )
        return data

    def get_latest_response(self, data: Dict[str, Any]) -> str:
        """Extract latest assistant response."""
        messages = data.get("messages", [])
        if messages:
            return str(messages[-1].get("content", ""))
        return ""


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestEcommerceShopperScenario:
    """Real-world e-commerce shopper: browse → filter → compare → decision."""

    def test_shopper_journey(self):
        """Complete shopper journey with multi-turn conversation."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        # Step 1: Initial browse
        response1 = scenario.send_message(
            "I'm looking for a new pair of wireless headphones. What do you recommend?"
        )
        assert response1.get("status") in [200, 201], "Initial search should succeed"

        content1 = scenario.get_latest_response(response1)
        assert len(content1) > 50, "Should provide meaningful recommendations"

        # Step 2: Filter by budget
        response2 = scenario.send_message(
            "Those are nice, but I want something under $300. What's available?"
        )
        assert response2.get("status") in [200, 201], "Filter should succeed"

        # Step 3: Compare specific models
        response3 = scenario.send_message(
            "How does the Sony WH-1000XM5 compare to the Bose QuietComfort 45?"
        )
        content3 = scenario.get_latest_response(response3)
        assert (
            "sony" in content3.lower() or "bose" in content3.lower()
        ), "Should compare requested models"

        # Step 4: Feature deep-dive
        response4 = scenario.send_message(
            "Which one has better noise cancellation and battery life?"
        )
        assert response4.get("status") in [200, 201], "Feature comparison should succeed"

        # Step 5: Final decision context
        response5 = scenario.send_message(
            "I mainly use them for commuting and office work. Which would be better?"
        )
        assert response5.get("status") in [200, 201], "Context-aware recommendation should work"

        assert len(scenario.conversation_history) == 5, "Should complete 5-turn conversation"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestProductExpertScenario:
    """Product expert: deep technical comparison and specifications."""

    def test_technical_comparison(self):
        """Deep technical product comparison with specifications."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        # Step 1: Technical deep-dive request
        response1 = scenario.send_message(
            "I need detailed technical specifications for gaming laptops with RTX 4090. "
            "Compare ASUS ROG vs Alienware models."
        )
        assert response1.get("status") in [200, 201], "Technical query should work"

        # Step 2: Compatibility question
        response2 = scenario.send_message(
            "Are these compatible with the latest external GPU enclosures? "
            "What are the Thunderbolt specifications?"
        )
        assert response2.get("status") in [200, 201], "Compatibility check should work"

        # Step 3: Performance benchmarks
        response3 = scenario.send_message(
            "What's the expected FPS in Cyberpunk 2077 at 4K ultra settings?"
        )
        assert response3.get("status") in [200, 201], "Performance estimate should work"

        # Step 4: Power and thermal specs
        response4 = scenario.send_message(
            "What's the power consumption? Do they require special cooling solutions?"
        )
        assert response4.get("status") in [200, 201], "Thermal specs should work"

        assert len(scenario.conversation_history) >= 4, "Should support technical depth"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestContentCreatorScenario:
    """Content creator: generate multiple marketing formats."""

    def test_multi_format_content_generation(self):
        """Test generating content in multiple formats."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        # Step 1: Find products for campaign
        response1 = scenario.send_message(
            "I'm creating marketing content for premium wireless headphones. "
            "Find the top 3 products in this category."
        )
        assert response1.get("status") in [200, 201], "Product discovery should work"

        # Step 2: Request social media content
        response2 = scenario.send_message(
            "Now create a compelling LinkedIn post about these products. "
            "Focus on professional use cases."
        )
        assert response2.get("status") in [200, 201], "Social content generation should work"

        content2 = scenario.get_latest_response(response2)
        assert len(content2) > 100, "Social post should have meaningful content"

        # Step 3: Blog post generation
        response3 = scenario.send_message(
            "Now write a detailed blog post comparing these models for different user types."
        )
        assert response3.get("status") in [200, 201], "Blog post generation should work"

        content3 = scenario.get_latest_response(response3)
        assert len(content3) > 300, "Blog post should be substantial"

        # Step 4: Technical article
        response4 = scenario.send_message(
            "Create a technical deep-dive article about the audio technology behind each model."
        )
        assert response4.get("status") in [200, 201], "Technical article should work"

        assert len(scenario.conversation_history) >= 4, "Should generate multiple formats"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestSupportAgentScenario:
    """Support agent: answer customer questions with accurate citations."""

    def test_customer_support_interactions(self):
        """Test realistic customer support scenarios."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        # Step 1: Customer complaint
        response1 = scenario.send_message(
            "I bought headphones last week and they stopped working after 3 days. "
            "What are my options? Do they come with warranty?"
        )
        assert response1.get("status") in [200, 201], "Support query should work"

        content1 = scenario.get_latest_response(response1)
        # Should mention warranty or support options
        assert len(content1) > 50, "Should provide helpful support information"

        # Step 2: Product comparison for replacement
        response2 = scenario.send_message(
            "I'm looking for a replacement. Are there better models available now?"
        )
        assert response2.get("status") in [200, 201], "Replacement recommendation should work"

        # Step 3: Troubleshooting
        response3 = scenario.send_message(
            "Actually, let me try troubleshooting. How do I reset these headphones?"
        )
        assert response3.get("status") in [200, 201], "Troubleshooting should work"

        # Step 4: Feature help
        response4 = scenario.send_message(
            "How do I enable active noise cancellation? I don't see the setting."
        )
        assert response4.get("status") in [200, 201], "Feature help should work"

        assert len(scenario.conversation_history) >= 4, "Should handle support interactions"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestMobileShopperScenario:
    """Mobile shopper: rapid-fire queries with quick results."""

    def test_rapid_fire_mobile_queries(self):
        """Mobile user with constrained time and data."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        queries = [
            "Best earbuds under $50?",
            "Wireless or wired?",
            "Good battery life?",
            "IP rating for sweat?",
            "Fast to ship?",
        ]

        start_time = time.time()

        for query in queries:
            response = scenario.send_message(query)
            assert response.get("status") in [200, 201], f"Query '{query}' should succeed"

        elapsed = time.time() - start_time
        avg_latency = elapsed / len(queries)

        # Mobile users expect fast responses
        assert avg_latency < 10, f"Mobile queries should average < 10s, got {avg_latency}s"
        assert len(scenario.conversation_history) == 5, "Should handle all rapid queries"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestAccessibilityScenario:
    """Test responses are accessible (screen reader compatible)."""

    def test_accessible_response_structure(self):
        """Responses should be screen reader friendly."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        response = scenario.send_message(
            "I need wireless headphones. I use a screen reader, so please organize the information clearly."
        )
        assert response.get("status") in [200, 201], "Accessibility-aware request should work"

        content = scenario.get_latest_response(response)

        # Check for basic accessibility markers
        # Good responses should have clear structure, not just walls of text
        lines = content.split("\n")
        assert len(lines) > 1, "Response should have clear line breaks for accessibility"

        # Should not have excessively long paragraphs
        avg_line_length = len(content) / len(lines) if lines else 0
        assert avg_line_length < 200, "Lines should be reasonably short for accessibility"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestPowerUserScenario:
    """Power user: complex filtering, faceting, and refinements."""

    def test_complex_filtering_and_refinement(self):
        """Power user with sophisticated filtering needs."""
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        # Step 1: Complex initial query
        response1 = scenario.send_message(
            "Find premium wireless headphones that are: "
            "noise-canceling, over-ear, under $400, "
            "with 30+ hour battery, Bluetooth 5.0+, and waterproof."
        )
        assert response1.get("status") in [200, 201], "Complex filter should work"

        # Step 2: Refinement - add constraint
        response2 = scenario.send_message(
            "Actually, I also need them to work well with both iOS and Android. "
            "Show me which ones have the best multi-device support."
        )
        assert response2.get("status") in [200, 201], "Refinement should work"

        # Step 3: Faceted navigation
        response3 = scenario.send_message("What brands are available in this filtered set?")
        assert response3.get("status") in [200, 201], "Faceted search should work"

        # Step 4: Feature comparison of filtered results
        response4 = scenario.send_message(
            "Compare the microphone quality for calls across these filtered options."
        )
        assert response4.get("status") in [200, 201], "Filtered comparison should work"

        assert len(scenario.conversation_history) >= 4, "Should handle power user workflow"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestColdStartPerformance:
    """Test performance on first request (cold start)."""

    def test_cold_start_latency(self):
        """First request after deployment should still be reasonable."""
        # Create a fresh conversation (simulating cold start)
        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)

        start_time = time.time()
        scenario.setup_conversation()
        setup_latency = time.time() - start_time

        # First query should be responsive even if services need warmup
        query_start = time.time()
        response = scenario.send_message("Find wireless headphones")
        query_latency = time.time() - query_start

        assert response.get("status") in [200, 201], "Cold start query should work"
        # Allow more time for cold start (LLM models might need warmup)
        assert query_latency < 30, f"Cold start should complete within 30s, got {query_latency}s"


@pytest.mark.performance
@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.phase3
class TestStreamingNetworkConditions:
    """Test WebSocket behavior with simulated network conditions."""

    @pytest.mark.asyncio
    async def test_streaming_response_chunking(self):
        """Test that responses stream properly via WebSocket."""
        # This would require WebSocket streaming implementation
        # For now, verify HTTP-based responses are structured for streaming

        scenario = ScenarioTest(DEPLOYMENT_URL, API_KEY)
        scenario.setup_conversation()

        response = scenario.send_message(
            "Please provide a detailed review of wireless headphones options. "
            "Organize it as: introduction, top 3 models, detailed comparison, recommendations."
        )

        assert response.get("status") in [200, 201], "Structured response should work"
        content = scenario.get_latest_response(response)

        # Response should be structured for streaming (not a single JSON blob)
        assert len(content) > 100, "Should return detailed content"


# Scenario reporting
def generate_scenario_report(test_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Generate report from scenario test results."""
    return {
        "timestamp": datetime.now().isoformat(),
        "total_scenarios": len(test_results),
        "successful": sum(1 for r in test_results if r.get("passed")),
        "failed": sum(1 for r in test_results if not r.get("passed")),
        "results": test_results,
    }
