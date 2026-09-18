"""
Unit tests for the enrichment lifecycle emit bridge (#103).

The taxonomy-correction demo hinges on an audience being able to watch a ~20s
re-index happen. Before #103 the UI got exactly one event, emitted from the
agent node's *completed* output — i.e. only ever after the fact — so the
re-index window was silent and a value-judge rejection was invisible.

These tests pin the three things that fixed it:
  1. a 'started' event is published BEFORE enrich_attribute is called,
  2. a single terminal event follows, carrying corrected_from and the real
     measured numbers,
  3. the judge-decline path publishes at all.

They also pin that publishing is optional, because the CLI, the admin route
and the test suite itself all run with no subscriber attached and a taxonomy
write must never fail for want of an observer.
"""

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from main import EcommerceSearchAgent
from pipeline import enrichment_events
from quality.enrichment_service import EnrichmentResult
from quality.enrichment_value_judge import EnrichmentValueAssessment


def _agent_with_llm(bound_llm_response, final_response=None, enrichment_assessment=None):
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


def _correction_tool_call():
    response = AIMessage(content="")
    response.tool_calls = [
        {
            "name": "trigger_enrichment",
            "args": {"attribute_type": "color", "variant": "tan", "canonical": "brown"},
            "id": "call_1",
        }
    ]
    return response


class _Recorder:
    """Installs a publisher for the duration of a with-block."""

    def __enter__(self):
        self.events = []
        self._token = enrichment_events.set_publisher(lambda **kw: self.events.append(kw))
        return self

    def __exit__(self, *exc):
        enrichment_events.reset_publisher(self._token)
        return False

    def of_status(self, status):
        return [e for e in self.events if e.get("status") == status]


class TestEnrichmentLifecycleEvents:
    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_started_is_published_before_the_reindex_runs(self, mock_enrich, mock_store_cls):
        """The whole point: the audience must learn a re-index is underway
        while it is underway, not 20 seconds later."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        seen_at_call_time = []

        def _record_then_return(*args, **kwargs):
            # Whatever has been published by the time enrich_attribute is
            # entered is, by definition, what the browser could already know.
            seen_at_call_time.extend(recorder.events)
            return EnrichmentResult(
                success=True,
                attribute_type="color",
                variant="tan",
                canonical="brown",
                reindex_triggered=True,
                reindex_success=True,
                docs_processed=9618,
                duration_seconds=19.4,
                corrected_from="yellow",
            )

        mock_enrich.side_effect = _record_then_return
        agent = _agent_with_llm(_correction_tool_call())

        with _Recorder() as recorder:
            agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert len(seen_at_call_time) == 1, "a 'started' event must precede the re-index"
        assert seen_at_call_time[0]["status"] == "started"
        assert seen_at_call_time[0]["variant"] == "tan"

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_started_carries_the_current_mapping_on_a_real_correction(
        self, mock_enrich, mock_store_cls
    ):
        """#142: the 'started' card has to say WHY the re-index is running
        before it finishes, and "tan is currently mapped to yellow" is only
        knowable from the pre-write lookup — EnrichmentResult.corrected_from
        does not exist yet at that point."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"tan": "yellow"}
        mock_enrich.return_value = EnrichmentResult(
            success=True, attribute_type="color", variant="tan", canonical="brown"
        )
        agent = _agent_with_llm(_correction_tool_call())

        with _Recorder() as recorder:
            agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert recorder.of_status("started")[0]["corrected_from"] == "yellow"

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_started_omits_corrected_from_when_the_proposal_is_a_no_op(
        self, mock_enrich, mock_store_cls
    ):
        """Regression (PR review, #142): when the model proposes the canonical
        a variant is ALREADY mapped to, enrich_attribute short-circuits on
        "already mapped" and writes nothing. Passing the current mapping
        through regardless made the card announce `"brown" is currently
        mapped to "brown" — rewriting that`: a rewrite that never happens,
        and a tautology besides. Absent corrected_from, the card falls back
        to the gap wording instead."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"tan": "brown"}
        mock_enrich.return_value = EnrichmentResult(
            success=False,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            reason="already mapped",
        )
        agent = _agent_with_llm(_correction_tool_call())

        with _Recorder() as recorder:
            agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert recorder.of_status("started")[0]["corrected_from"] is None

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_terminal_event_carries_corrected_from_and_real_numbers(
        self, mock_enrich, mock_store_cls
    ):
        """corrected_from is what separates 'learned tan -> brown' from
        'corrected tan from yellow to brown' — the centrepiece of the demo,
        and the field that never used to reach the frontend."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=19.4,
            reindex_mode="local",
            corrected_from="yellow",
        )
        agent = _agent_with_llm(_correction_tool_call())

        with _Recorder() as recorder:
            agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert [e["status"] for e in recorder.events] == ["started", "complete"]
        terminal = recorder.of_status("complete")[0]
        assert terminal["corrected_from"] == "yellow"
        assert terminal["canonical"] == "brown"
        assert terminal["docs_processed"] == 9618
        assert terminal["duration_seconds"] == 19.4
        assert terminal["reindex_mode"] == "local"

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_failed_reindex_publishes_failed_without_fake_numbers(
        self, mock_enrich, mock_store_cls
    ):
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            reindex_triggered=True,
            reindex_success=False,
            reindex_error="docker daemon not running",
            docs_processed=0,
            duration_seconds=2.1,
        )
        agent = _agent_with_llm(_correction_tool_call())

        with _Recorder() as recorder:
            agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert [e["status"] for e in recorder.events] == ["started", "failed"]
        terminal = recorder.of_status("failed")[0]
        assert terminal["error"] == "docker daemon not running"
        # A re-index that didn't finish has no honest doc count to report.
        assert terminal["docs_processed"] is None
        assert terminal["duration_seconds"] is None

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_value_judge_rejection_is_announced_not_silent(self, mock_enrich, mock_store_cls):
        """A guardrail that fires invisibly looks identical to a hung app when
        you are standing in front of 300 people."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_with_llm(
            _correction_tool_call(),
            enrichment_assessment=EnrichmentValueAssessment(
                is_meaningful=False, reasoning="'tan' already resolves sensibly."
            ),
        )

        with _Recorder() as recorder:
            result = agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert result["enrichment_triggered"] is False
        assert [e["status"] for e in recorder.events] == ["declined"]
        assert recorder.of_status("declined")[0]["error"] == "'tan' already resolves sensibly."
        mock_enrich.assert_not_called()

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_enrichment_succeeds_with_no_subscriber_attached(self, mock_enrich, mock_store_cls):
        """cli.py, /api/admin/enrich and the test suite all run with no
        observer. A real taxonomy write must never depend on one."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=19.4,
        )
        agent = _agent_with_llm(_correction_tool_call())

        result = agent._try_enrichment_tool("that's not tan, it's tagged yellow")

        assert result["enrichment_triggered"] is True

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("quality.enrichment_service.enrich_attribute")
    def test_a_broken_subscriber_cannot_break_the_enrichment(self, mock_enrich, mock_store_cls):
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        mock_enrich.return_value = EnrichmentResult(
            success=True,
            attribute_type="color",
            variant="tan",
            canonical="brown",
            reindex_triggered=True,
            reindex_success=True,
            docs_processed=9618,
            duration_seconds=19.4,
        )
        agent = _agent_with_llm(_correction_tool_call())

        def _exploding_publisher(**_kwargs):
            raise RuntimeError("websocket already closed")

        token = enrichment_events.set_publisher(_exploding_publisher)
        try:
            result = agent._try_enrichment_tool("that's not tan, it's tagged yellow")
        finally:
            enrichment_events.reset_publisher(token)

        assert result["enrichment_triggered"] is True
