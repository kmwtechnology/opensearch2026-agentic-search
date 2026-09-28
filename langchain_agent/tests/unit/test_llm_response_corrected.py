"""LLMResponseCorrectedEvent schema."""

import pytest

from api.schemas.events import LLMResponseCorrectedEvent


class TestLLMResponseCorrectedEvent:
    def test_schema_defaults(self):
        ev = LLMResponseCorrectedEvent(
            corrected_content="fixed text",
            original_faithfulness=0.7,
            corrected_faithfulness=0.92,
        )
        assert ev.type == "llm_response_corrected"
        assert ev.node == "llm_judge"
        assert ev.corrected_content == "fixed text"
        assert ev.original_faithfulness == pytest.approx(0.7)
        assert ev.corrected_faithfulness == pytest.approx(0.92)

    def test_serializes_to_dict_with_correct_type_key(self):
        ev = LLMResponseCorrectedEvent(
            corrected_content="fixed",
            original_faithfulness=0.5,
            corrected_faithfulness=0.9,
        )
        data = ev.model_dump()
        assert data["type"] == "llm_response_corrected"
        assert data["node"] == "llm_judge"
        assert data["corrected_content"] == "fixed"

    def test_json_round_trip(self):
        ev = LLMResponseCorrectedEvent(
            corrected_content="hello world",
            original_faithfulness=0.6,
            corrected_faithfulness=0.88,
        )
        restored = LLMResponseCorrectedEvent.model_validate_json(ev.model_dump_json())
        assert restored.corrected_content == ev.corrected_content
        assert restored.original_faithfulness == pytest.approx(ev.original_faithfulness)
        assert restored.corrected_faithfulness == pytest.approx(ev.corrected_faithfulness)
