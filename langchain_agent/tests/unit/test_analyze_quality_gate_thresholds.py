"""Unit tests for the quality-gate threshold analysis tool (issue #56 Phase C)."""

import sys
from types import ModuleType
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import scripts.analyze_quality_gate_thresholds as script


def _score(trace_id, value=None, string_value=None):
    return NS(trace_id=trace_id, value=value, string_value=string_value)


def test_scores_by_trace_maps_trace_id_to_value():
    client = MagicMock()
    client.api.scores.get_many.return_value = NS(
        data=[_score("t1", value=0.7), _score("t2", value=0.3), _score(None, value=0.9)]
    )
    result = script._scores_by_trace(client, "reranker_max_score", limit=200)
    assert result == {"t1": 0.7, "t2": 0.3}
    client.api.scores.get_many.assert_called_once_with(name="reranker_max_score", limit=200)


def test_main_skips_when_langfuse_disabled():
    with patch.object(script, "LANGFUSE_ENABLED", False):
        assert script.main([]) == 1


def test_main_reports_no_joined_traces():
    client_instance = MagicMock()
    client_instance.api.scores.get_many.return_value = NS(data=[])
    client_cls = MagicMock(return_value=client_instance)

    fake_module = ModuleType("langfuse")
    fake_module.Langfuse = client_cls

    with (
        patch.object(script, "LANGFUSE_ENABLED", True),
        patch.dict(sys.modules, {"langfuse": fake_module}),
    ):
        assert script.main([]) == 0
