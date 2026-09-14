"""
Unit tests for EcommerceSearchAgent._try_enrichment_tool — the manual
two-call tool-binding loop used by agent_node's gap-signal branch.

self.llm is mocked throughout; tools.enrichment_tool.trigger_enrichment's
underlying enrich_attribute call is mocked so these never touch OpenSearch
or trigger a real reindex.
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from main import EcommerceSearchAgent
from quality.enrichment_service import EnrichmentResult
from quality.enrichment_value_judge import EnrichmentValueAssessment


def _agent_with_llm(bound_llm_response, final_response=None, enrichment_assessment=None):
    """Build a minimal agent whose bind_tools(...).invoke(...) returns
    bound_llm_response, and whose plain .invoke(...) (the second, tool-less
    call) returns final_response.

    enrichment_value_judge is pre-set to a mock that approves by default
    (is_meaningful=True) -- tests exercising the decline path pass their
    own enrichment_assessment. Callers that reach the real gate must also
    patch attribute_mapping_store.AttributeMappingStore, since
    _try_enrichment_tool constructs it directly to fetch current_mapping."""
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    llm_with_tools = MagicMock()
    llm_with_tools.invoke.return_value = bound_llm_response

    agent.llm = MagicMock()
    agent.llm.bind_tools.return_value = llm_with_tools
    agent.llm.invoke.return_value = final_response or AIMessage(content="Fixed it!")

    agent.enrichment_value_judge = MagicMock()
    agent.enrichment_value_judge.evaluate.return_value = enrichment_assessment or (
        EnrichmentValueAssessment(is_meaningful=True, reasoning="Genuine, common term.")
    )
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

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_tool_call_executes_and_returns_state(self, mock_enrich, mock_store_cls):
        mock_store_cls.return_value.get_lookup_table.return_value = {}
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
        assert result["enrichment_duration_seconds"] == 18.3
        assert result["enrichment_docs_processed"] == 9618
        mock_enrich.assert_called_once_with("material", "chrome", explicit_canonical="metal")

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_duration_and_docs_processed_omitted_when_reindex_fails(
        self, mock_enrich, mock_store_cls
    ):
        """If the mapping wrote successfully but the reindex itself failed,
        docs_processed/duration_seconds describe a re-index that didn't
        actually complete -- surfacing them as real numbers would be
        misleading, so they're omitted (None) rather than shown (#80)."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="material",
            variant="chrome",
            canonical="metal",
            reindex_triggered=True,
            reindex_success=False,
            reindex_error="docker daemon not running",
            docs_processed=0,
            duration_seconds=2.1,
        )

        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "material", "variant": "chrome", "canonical": "metal"},
                "id": "call_1",
            }
        ]
        final = AIMessage(content="I tried to fix that, but the re-index failed.")
        agent = _agent_with_llm(tool_call_response, final_response=final)

        result = agent._try_enrichment_tool("chrome bar table")

        assert result["enrichment_triggered"] is True
        assert result["enrichment_duration_seconds"] is None
        assert result["enrichment_docs_processed"] is None

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_tool_message_has_matching_tool_call_id(self, mock_enrich, mock_store_cls):
        mock_store_cls.return_value.get_lookup_table.return_value = {}
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

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_classification_failure_still_returns_state_with_final_response(
        self, mock_enrich, mock_store_cls
    ):
        """Even when the tool call itself fails (e.g. unclassifiable term),
        the LLM still gets a chance to respond naturally referencing the
        failure — this isn't a crash path."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
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


class TestEnrichmentValueGate:
    """EnrichmentValueJudge sits between 'the LLM decided to call
    trigger_enrichment' and the tool actually executing -- a declined
    assessment must prevent the real write + reindex entirely."""

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_declined_assessment_never_invokes_the_tool(self, mock_enrich, mock_store_cls):
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "color", "variant": "reddish", "canonical": "red"},
                "id": "call_1",
            }
        ]
        agent = _agent_with_llm(
            tool_call_response,
            enrichment_assessment=EnrichmentValueAssessment(
                is_meaningful=False, reasoning="Too close to an existing 'red' variant."
            ),
        )

        result = agent._try_enrichment_tool("reddish shoes")

        mock_enrich.assert_not_called()
        assert result is not None
        assert result["enrichment_triggered"] is False
        assert result["enrichment_evaluation_declined"] is True
        assert (
            result["enrichment_evaluation_reasoning"] == "Too close to an existing 'red' variant."
        )
        assert "reddish" in result["messages"][0].content

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_declined_assessment_via_correction_path_never_invokes_the_tool(
        self, mock_enrich, mock_store_cls
    ):
        """Same gate applies through _try_correction_tool's call into
        _try_enrichment_tool (shared choke point) -- a disputed tag doesn't
        get corrected just because the shopper disputed it."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"tan": "yellow"}
        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "color", "variant": "tan", "canonical": "brown"},
                "id": "call_1",
            }
        ]
        agent = _agent_with_llm(
            tool_call_response,
            enrichment_assessment=EnrichmentValueAssessment(
                is_meaningful=False, reasoning="Not enough evidence this is a real mistag."
            ),
        )

        result = agent._try_correction_tool(
            [HumanMessage(content="that's not tan, that's tagged yellow which is wrong")],
            "that's not tan, that's tagged yellow which is wrong",
        )

        mock_enrich.assert_not_called()
        assert result["enrichment_triggered"] is False
        assert result["enrichment_evaluation_declined"] is True

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_evaluate_called_with_current_mapping_from_store(self, mock_store_cls):
        mock_store_cls.return_value.get_lookup_table.return_value = {"tan": "yellow"}
        tool_call_response = AIMessage(content="")
        tool_call_response.tool_calls = [
            {
                "name": "trigger_enrichment",
                "args": {"attribute_type": "color", "variant": "tan", "canonical": "brown"},
                "id": "call_1",
            }
        ]
        agent = _agent_with_llm(tool_call_response)
        with patch("quality.enrichment_service.enrich_attribute") as mock_enrich:
            mock_enrich.return_value = EnrichmentResult(
                success=True, attribute_type="color", variant="tan", canonical="brown"
            )
            agent._try_enrichment_tool("show me tan boots")

        agent.enrichment_value_judge.evaluate.assert_called_once_with(
            attribute_type="color",
            variant="tan",
            canonical="brown",
            current_mapping="yellow",
            context="show me tan boots",
        )


class TestAgentNodeGapDetection:
    """agent_node's gap-signal gate: whether _try_enrichment_tool gets
    offered a chance at all. quality_gate_node deliberately never retries
    when the first retrieval pass already returns zero documents (adjusting
    alpha can't fix an exclusionary filter), so quality_gate_retried never
    becomes True for that case -- exactly the scenario an unrecognized
    attribute_filter term produces. zero_result_filter_gap exists to catch
    that case; these tests guard both that it fires, and that it stays
    scoped to attribute_filter intent (a naive `not retrieved_documents`
    would fire for every empty-result search, not just attribute gaps)."""

    def _agent_for_gap_check(self, bare_agent):
        bare_agent._try_enrichment_tool = MagicMock(
            return_value={"messages": [AIMessage(content="handled")], "citations": []}
        )
        # spec=[...] omits "stream" so agent_node's hasattr(self.llm, "stream")
        # check is False, taking the plain .invoke() path instead of
        # _stream_llm_response_simple -- only exercised when the gap gate
        # doesn't short-circuit (the "not triggered" case falls through to
        # real response generation).
        bare_agent.llm = MagicMock(spec=["invoke", "bind_tools"])
        bare_agent.llm.invoke.return_value = AIMessage(content="Here's what I found instead.")
        return bare_agent

    def _base_state(self, intent, retrieved_documents, quality_gate_retried):
        return {
            "messages": [HumanMessage(content="show me camel colored coats")],
            "retrieved_documents": retrieved_documents,
            "intent": intent,
            "quality_gate_retried": quality_gate_retried,
        }

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_zero_result_attribute_filter_triggers_enrichment_offer(self, bare_agent):
        agent = self._agent_for_gap_check(bare_agent)
        state = self._base_state("attribute_filter", [], quality_gate_retried=False)

        result = agent.agent_node(state)

        agent._try_enrichment_tool.assert_called_once_with("show me camel colored coats")
        assert result["messages"][0].content == "handled"

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_zero_result_non_attribute_filter_does_not_trigger(self, bare_agent):
        """A plain search intent with no results is a real 'nothing found'
        case, not an attribute-taxonomy gap -- must not offer the tool.
        Neither retry_exhausted_gap nor zero_result_filter_gap fires here
        (quality_gate_retried=False, intent != attribute_filter), so
        agent_node falls through to normal response generation rather than
        the canned no-info message -- that's expected, not what's tested."""
        agent = self._agent_for_gap_check(bare_agent)
        state = self._base_state("search", [], quality_gate_retried=False)

        agent.agent_node(state)

        agent._try_enrichment_tool.assert_not_called()


class TestDetectCorrectionSignal:
    """Cheap keyword pre-filter for 'this message might be disputing a
    taxonomy tag'. Deliberately broad: false positives just cost one
    extra LLM decision that declines to call the tool; false negatives
    silently drop a real correction, which is worse."""

    @pytest.mark.parametrize(
        "message",
        [
            "that's not tan, that's yellow",
            "Actually I think the color tag is wrong",
            "that boot isn't really brown",
            "the color tag is mistagged",
            "hmm, that's tagged wrong",
            "this is incorrectly tagged as yellow",
        ],
    )
    def test_dispute_phrasings_detected(self, bare_agent, message):
        assert bare_agent._detect_correction_signal(message) is True

    @pytest.mark.parametrize(
        "message",
        [
            "show me camel colored coats",
            "cheaper ones please",
            "only in leather",
            None,
            "",
        ],
    )
    def test_ordinary_messages_not_flagged(self, bare_agent, message):
        assert bare_agent._detect_correction_signal(message) is False


class TestAgentNodeCorrectionDetection:
    """agent_node's taxonomy-correction gate: distinct from the zero-result
    gap path above -- fires when the shopper disputes a tag from a PRIOR
    turn, regardless of this turn's own retrieval results, and only on
    conversation-continuation intents (refinement/follow_up) so a fresh
    standalone query is never misread as a correction."""

    def _agent_for_correction_check(self, bare_agent):
        bare_agent._try_correction_tool = MagicMock(
            return_value={"messages": [AIMessage(content="corrected")], "citations": []}
        )
        bare_agent.llm = MagicMock(spec=["invoke", "bind_tools"])
        bare_agent.llm.invoke.return_value = AIMessage(content="Here's what I found instead.")
        return bare_agent

    def _base_state(self, intent, message, retrieved_documents=None):
        return {
            "messages": [HumanMessage(content=message)],
            "retrieved_documents": retrieved_documents or [],
            "intent": intent,
            "quality_gate_retried": False,
        }

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_dispute_on_refinement_turn_triggers_correction_offer(self, bare_agent):
        agent = self._agent_for_correction_check(bare_agent)
        state = self._base_state("refinement", "that's not tan, that's yellow")

        result = agent.agent_node(state)

        agent._try_correction_tool.assert_called_once()
        assert result["messages"][0].content == "corrected"

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_dispute_on_follow_up_turn_triggers_correction_offer(self, bare_agent):
        agent = self._agent_for_correction_check(bare_agent)
        state = self._base_state("follow_up", "actually that tag looks wrong")

        agent.agent_node(state)

        agent._try_correction_tool.assert_called_once()

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_dispute_on_fresh_search_intent_does_not_trigger(self, bare_agent):
        """A standalone search/attribute_filter turn can't be disputing a
        prior tag -- there's no established conversation to dispute. Even
        with dispute-shaped language, this must not fire."""
        agent = self._agent_for_correction_check(bare_agent)
        state = self._base_state("search", "that's not tan, that's yellow")

        agent.agent_node(state)

        agent._try_correction_tool.assert_not_called()

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_ordinary_refinement_without_dispute_language_does_not_trigger(self, bare_agent):
        agent = self._agent_for_correction_check(bare_agent)
        state = self._base_state("refinement", "only show me the waterproof ones")

        agent.agent_node(state)

        agent._try_correction_tool.assert_not_called()

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", False)
    def test_disabled_flag_never_triggers_even_with_dispute_language(self, bare_agent):
        agent = self._agent_for_correction_check(bare_agent)
        state = self._base_state("refinement", "that's not tan, that's yellow")

        agent.agent_node(state)

        agent._try_correction_tool.assert_not_called()

    @patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
    def test_llm_declining_falls_through_to_normal_response_not_canned_message(self, bare_agent):
        """When the LLM isn't confident this is a real correction,
        _try_correction_tool returns None -- agent_node must fall through
        to ordinary response generation, not the zero-result "no info"
        canned message (this isn't a search failure)."""
        agent = self._agent_for_correction_check(bare_agent)
        agent._try_correction_tool.return_value = None
        state = self._base_state("refinement", "that's not tan, that's yellow")

        result = agent.agent_node(state)

        agent._try_correction_tool.assert_called_once()
        assert result["messages"][0].content == "Here's what I found instead."
