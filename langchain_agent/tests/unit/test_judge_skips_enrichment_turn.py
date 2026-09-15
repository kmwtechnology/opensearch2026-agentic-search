"""The LLM judge must not grade a taxonomy-correction turn (#107).

Found in a live run-through: on arc 2 turn 2 the agent correctly said "I've
corrected our system so that 'tan' is now properly mapped to the brown color
family", and eight seconds later the judge's auto-retry replaced it with "these
are indeed indexed under the 'yellow' color category" — asserting the bug still
existed, immediately after it had been fixed.

The cause is structural, not a bad roll of the dice. ``llm_judge_node`` grades
the answer against ``retrieved_documents``; the claim that makes this turn worth
demonstrating is grounded in the ``trigger_enrichment`` TOOL RESULT, which the
judge never receives. So the true statement is unfalsifiable from the evidence
the judge holds, is categorised as fabrication, and the regeneration step — which
re-writes using the documents alone — can only produce an answer with the
correction removed.

These tests pin the skip at the node's entry, before the judge is constructed.
"""

import pytest
from langchain_core.documents import Document
from langchain_core.messages import AIMessage

from pipeline.pipeline_nodes import PipelineNodesMixin
from quality.judge import JudgmentResult


class _RecordingJudge:
    """Records whether it was consulted.

    A raising stub is not usable here: ``llm_judge_node`` wraps the judge call
    in try/except and converts any failure into ``judgment=None`` — the same
    result the skip produces — so an exception cannot distinguish "skipped"
    from "graded and blew up".
    """

    def __init__(self):
        self.called = False

    def judge(self, *args, **kwargs):
        self.called = True
        return JudgmentResult(verdict="llm_better", faithfulness=1.0)


class _Node(PipelineNodesMixin):
    """Bare host for the node under test — no LLM, no retriever, no graph."""

    def __init__(self):
        self.judge = _RecordingJudge()


def _state(**overrides):
    state = {
        "messages": [AIMessage(content="I've corrected the taxonomy: tan now maps to brown.")],
        "retrieved_documents": [Document(page_content="A tan leather boot.", metadata={})],
        "user_query": "that's not tan, that's tagged yellow which is wrong",
        "intent": "refinement",
        "optimizations": {"llm": True, "llm_judge": True},
    }
    state.update(overrides)
    return state


@pytest.mark.unit
class TestJudgeSkipsEnrichmentTurn:
    def test_enrichment_turn_is_not_judged(self):
        node = _Node()
        result = node.llm_judge_node(_state(enrichment_triggered=True))

        assert node.judge.called is False, (
            "The judge cannot see the trigger_enrichment tool result, so it "
            "flags the correction claim as fabrication and the retry strips it."
        )
        assert result["judgment"] is None
        assert result["judge_latency_ms"] == 0.0

    def test_skip_is_not_merely_suppressing_the_retry(self):
        """No judgment at all, so no spurious flags reach the UI either.

        Suppressing only the auto-retry would leave the fabrication flags in
        place, and the frontend would decorate the centerpiece answer with a
        hallucination warning instead of rewriting it — a different way to lose
        the same moment.
        """
        result = _Node().llm_judge_node(_state(enrichment_triggered=True))

        assert result["judgment"] is None, "flags must not survive the skip"

    def test_an_ordinary_turn_is_still_judged(self):
        """The skip must be scoped to correction turns and nothing else."""
        node = _Node()
        node.llm_judge_node(_state(enrichment_triggered=False))

        assert node.judge.called is True

    def test_absent_flag_is_treated_as_an_ordinary_turn(self):
        """CustomAgentState is total=False — the key is often simply missing."""
        node = _Node()
        node.llm_judge_node(_state())

        assert node.judge.called is True
