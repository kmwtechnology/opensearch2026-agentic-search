"""
Internal model deliberation must never reach the chat window (#103).

agent_node makes model calls that are not the answer: the trigger_enrichment
tool offer, and the enrichment value judge. observable_agent streams every
on_chat_model_stream it sees while the agent node is current, so before this
fix the model's private reasoning was rendered to the user AS the reply.

Found by running DEMO.md live: asking "Find me wireless headphones under $100"
produced the answer "Nothing in the query ... looks like a color or material
term" — the tool-offer prompt thinking out loud about taxonomy, in response to
a question about headphones.

These tests pin the contract from both ends, because it takes both halves to
work and each half looks fine on its own.
"""

import inspect

from core.config import INTERNAL_LLM_TAG


class TestInternalLLMCallsAreTagged:
    """Producer side: the deliberation calls must carry the tag."""

    def test_enrichment_tool_offer_call_is_tagged(self):
        from pipeline import pipeline_nodes

        src = inspect.getsource(pipeline_nodes.PipelineNodesMixin._try_enrichment_tool)
        assert "INTERNAL_LLM_TAG" in src, (
            "the trigger_enrichment tool-offer call must be tagged as internal, "
            "or its refusal prose is streamed to the user as the answer"
        )

    def test_enrichment_value_judge_call_is_tagged(self):
        from quality import enrichment_value_judge

        src = inspect.getsource(enrichment_value_judge)
        assert (
            "INTERNAL_LLM_TAG" in src
        ), "the value judge also runs inside agent_node and streams the same way"


class TestObservableAgentHonoursTheTag:
    """Consumer side: a tagged stream event must be dropped."""

    def test_stream_handler_checks_the_tag(self):
        from api.services import observable_agent

        src = inspect.getsource(observable_agent.ObservableAgentService._astream_graph)
        assert "INTERNAL_LLM_TAG" in src, (
            "observable_agent must skip on_chat_model_stream events carrying the "
            "internal tag; tagging the producer alone changes nothing"
        )

    def test_tag_value_is_shared_not_duplicated(self):
        """Both halves must read the same constant — a literal on either side
        would silently stop matching the day someone edits one of them."""
        from api.services import observable_agent
        from pipeline import pipeline_nodes

        assert observable_agent.INTERNAL_LLM_TAG == INTERNAL_LLM_TAG
        assert pipeline_nodes.INTERNAL_LLM_TAG == INTERNAL_LLM_TAG
