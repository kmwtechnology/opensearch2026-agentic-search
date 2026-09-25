"""
Unit tests for EnrichmentValueJudge -- the second-opinion gate that decides
whether a proposed trigger_enrichment call is worth a real catalog write +
reindex, independent of the agent's own tool-call decision. The chat model
is mocked throughout so these never make a real API call.
"""

from unittest.mock import MagicMock, patch

from quality.enrichment_value_judge import (
    EnrichmentValueAssessment,
    EnrichmentValueJudge,
    _build_prompt,
)


class TestBuildPrompt:
    def test_includes_current_mapping_when_present(self):
        prompt = _build_prompt("color", "tan", "brown", "yellow", "show me tan boots")

        assert 'Currently mapped to: "yellow"' in prompt
        assert "correction" in prompt

    def test_notes_new_addition_when_no_current_mapping(self):
        prompt = _build_prompt(
            "waterproof", "weatherproof", "waterproof", None, "weatherproof jacket"
        )

        assert "Not currently in the taxonomy" in prompt
        assert "new addition" in prompt

    def test_includes_variant_canonical_and_context(self):
        prompt = _build_prompt("color", "tan", "brown", "yellow", "show me tan boots")

        assert '"tan"' in prompt
        assert '"brown"' in prompt
        assert "show me tan boots" in prompt


class TestEnrichmentValueJudge:
    def _judge_with_mocked_response(self, assessment: EnrichmentValueAssessment):
        with patch("quality.enrichment_value_judge.build_chat_model"):
            judge = EnrichmentValueJudge(model_name="qwen3.6:35b-a3b-q4_K_M")
        judge.structured_llm = MagicMock()
        judge.structured_llm.invoke.return_value = assessment
        return judge

    def test_evaluate_returns_the_structured_assessment(self):
        expected = EnrichmentValueAssessment(is_meaningful=True, reasoning="Real, common term.")
        judge = self._judge_with_mocked_response(expected)

        result = judge.evaluate(
            attribute_type="color",
            variant="tan",
            canonical="brown",
            current_mapping="yellow",
            context="show me tan boots",
        )

        assert result is expected

    def test_evaluate_can_decline(self):
        expected = EnrichmentValueAssessment(
            is_meaningful=False, reasoning="Too ambiguous to be a real correction."
        )
        judge = self._judge_with_mocked_response(expected)

        result = judge.evaluate(
            attribute_type="color",
            variant="reddish",
            canonical="red",
            current_mapping=None,
            context="reddish shoes",
        )

        assert result.is_meaningful is False

    def test_evaluate_invokes_structured_llm_with_system_and_user_messages(self):
        judge = self._judge_with_mocked_response(
            EnrichmentValueAssessment(is_meaningful=True, reasoning="ok")
        )

        judge.evaluate(
            attribute_type="color",
            variant="tan",
            canonical="brown",
            current_mapping="yellow",
            context="show me tan boots",
        )

        call_args = judge.structured_llm.invoke.call_args[0][0]
        roles = [m["role"] for m in call_args]
        assert roles == ["system", "user"]
