"""
Unit tests for EcommerceSearchAgent._try_enrichment_tool — the manual
two-call tool-binding loop used by agent_node's gap-signal branch.

self.llm is mocked throughout; tools.enrichment_tool.trigger_enrichment's
underlying enrich_attribute call is mocked so these never touch OpenSearch
or trigger a real reindex.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from enrichment_service import EnrichmentResult
from main import EcommerceSearchAgent


def _agent_with_llm(bound_llm_response, final_response=None):
    """Build a minimal agent whose bind_tools(...).invoke(...) returns
    bound_llm_response, and whose plain .invoke(...) (the second, tool-less
    call) returns final_response."""
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    llm_with_tools = MagicMock()
    llm_with_tools.invoke.return_value = bound_llm_response

    agent.llm = MagicMock()
    agent.llm.bind_tools.return_value = llm_with_tools
    agent.llm.invoke.return_value = final_response or AIMessage(content="Fixed it!")
    return agent


class TestTryEnrichmentTool:
    def test_no_tool_call_returns_none(self):
        response = AIMessage(content="I don't see a color or material gap here.")
        response.tool_calls = []
        agent = _agent_with_llm(response)

        result = agent._try_enrichment_tool("random unrelated query")

        assert result is None

    def test_binds_trigger_enrichment_tool(self):
        response = AIMessage(content="")
        response.tool_calls = []
        agent = _agent_with_llm(response)

        agent._try_enrichment_tool("chrome bar table")

        from tools.enrichment_tool import trigger_enrichment

        agent.llm.bind_tools.assert_called_once_with([trigger_enrichment])

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_tool_call_executes_and_returns_state(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="material",
            variant="chrome",
            canonical="metal",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=18.3,
        )

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "material", "variant": "chrome", "canonical": "metal"},
                "id": "call_1",
            }
        ]
        final = AIMessage(content="I've added chrome as a metal and re-indexed the catalog.")
        agent = _agent_with_llm(tool_call_response, final_response=final)

        result = agent._try_enrichment_tool("chrome bar table")

        assert result is not None
        assert result["messages"] == [final]
        assert result["citations"] == []
        assert result["enrichment_triggered"] is True
        assert result["enrichment_attribute_type"] == "material"
        assert result["enrichment_variant"] == "chrome"
        assert result["enrichment_canonical"] == "metal"
        mock_enrich.assert_called_once_with("material", "chrome", explicit_canonical="metal")

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_tool_message_has_matching_tool_call_id(self, mock_enrich):
        mock_enrich.return_value = EnrichmentResult(
            success=True, attribute_type="color", variant="periwinkle", canonical="blue"
        )

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "color", "variant": "periwinkle", "canonical": "blue"},
                "id": "call_xyz",
            }
        ]
        agent = _agent_with_llm(tool_call_response)

        agent._try_enrichment_tool("periwinkle dress")

        # Second invoke() call received the message list including a
        # ToolMessage whose tool_call_id matches the original call's id.
        second_call_messages = agent.llm.invoke.call_args[0][0]
        from langchain_core.messages import ToolMessage

        tool_messages = [m for m in second_call_messages if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].tool_call_id == "call_xyz"

    @patch("tools.enrichment_tool.enrich_attribute")
    def test_classification_failure_still_returns_state_with_final_response(self, mock_enrich):
        """Even when the tool call itself fails (e.g. unclassifiable term),
        the LLM still gets a chance to respond naturally referencing the
        failure — this isn't a crash path."""
        mock_enrich.return_value = EnrichmentResult(
            success=False,
            attribute_type="material",
            variant="xyz",
            reason="could not classify to a known material bucket",
        )

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "material", "variant": "xyz", "canonical": "metal"},
                "id": "call_1",
            }
        ]
        agent = _agent_with_llm(tool_call_response)

        result = agent._try_enrichment_tool("xyz widget")

        assert result is not None
        assert result["enrichment_triggered"] is True
