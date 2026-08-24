"""Regression: _extract_attributes must coerce LLM-returned arrays to strings.

Production incident reproduced 2026-05-06 via the demo scenario "wireless
headphones" → "only noise cancelling ones" (DEMO_QUERIES.md scenario 2).
Turn 2 routes to ``refinement`` intent, which calls ``_extract_attributes``;
Gemini occasionally returns ``material_or_feature`` (or ``size``) as a JSON
**array** rather than a string — e.g. ``["noise canceling"]``. That array
gets put into a ``multi_match`` filter as the ``query`` field, and OpenSearch
rejects it with::

    RequestError(400, 'x_content_parse_exception',
        '[multi_match] unknown token [START_ARRAY] after [query]')

Same root-cause shape as the HumanMessage list-of-blocks bug in this PR,
but a different code path. Fix is at main.py:1640-1690 — every extracted
attribute value goes through ``_coerce`` (handles strings, lists, None,
empty values) before reaching an OpenSearch ``query`` field.

This test pins the contract: regardless of how ugly the LLM's JSON gets
(arrays, mixed types, empty strings, single-element lists, nulls in arrays),
the resulting filter clause must always have a flat string ``query`` field.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

import pytest

from main import EcommerceSearchAgent


class _Resp:
    def __init__(self, content: Any) -> None:
        self.content = content


def _agent_returning_attributes(payload: dict) -> EcommerceSearchAgent:
    """Build a minimal agent whose attribute-extractor LLM returns ``payload``."""
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.alpha_estimator_llm = MagicMock()
    agent.alpha_estimator_llm.invoke.return_value = _Resp(json.dumps(payload))
    return agent


def _all_query_fields_are_strings(filters: list) -> None:
    """Walk filter clauses and assert every ``query`` value is a string.

    The bug shape is "list-where-string-expected"; this is the structural
    contract OpenSearch enforces and the only thing that matters here.
    """
    for f in filters:
        for op in ("multi_match", "match"):
            clause = f.get(op)
            if not clause:
                continue
            if op == "multi_match":
                q = clause.get("query")
            else:
                # match: nested under field name → {"query": ...}
                inner = next(iter(clause.values()))
                q = inner.get("query") if isinstance(inner, dict) else None
            assert isinstance(q, str), (
                f"Expected string for {op}.query, got {type(q).__name__}={q!r}. "
                f"Full filter: {f!r}"
            )


@pytest.mark.unit
@pytest.mark.phase1
class TestExtractAttributesCoercion:
    def test_string_attributes_pass_through(self) -> None:
        agent = _agent_returning_attributes(
            {
                "brand": "Sony",
                "color": "black",
                "material_or_feature": "noise canceling",
                "size": "large",
            }
        )
        filters = agent._extract_attributes("noise canceling Sony headphones")
        _all_query_fields_are_strings(filters)
        # Every supplied attribute should have produced a clause.
        assert len(filters) == 4

    def test_array_material_collapsed_to_string(self) -> None:
        # The exact shape that crashed prod: material_or_feature as a
        # single-element JSON array.
        agent = _agent_returning_attributes({"material_or_feature": ["noise canceling"]})
        filters = agent._extract_attributes("only noise cancelling ones please")
        _all_query_fields_are_strings(filters)
        # Verify the value made it through — not just dropped silently.
        mm = filters[0]["multi_match"]
        assert mm["query"] == "noise canceling"

    def test_multi_element_array_joined_with_space(self) -> None:
        agent = _agent_returning_attributes(
            {"material_or_feature": ["noise canceling", "wireless"]}
        )
        filters = agent._extract_attributes("wireless noise cancelling")
        _all_query_fields_are_strings(filters)
        mm = filters[0]["multi_match"]
        assert mm["query"] == "noise canceling wireless"

    def test_array_brand_and_color_coerced(self) -> None:
        agent = _agent_returning_attributes({"brand": ["Sony"], "color": ["black", "blue"]})
        filters = agent._extract_attributes("sony black headphones")
        _all_query_fields_are_strings(filters)
        # Brand becomes single-string, color becomes joined string.
        brand = next(f for f in filters if "product_brand_normalized" in f.get("match", {}))
        color = next(f for f in filters if "product_color_primary" in f.get("match", {}))
        assert brand["match"]["product_brand_normalized"]["query"] == "Sony"
        assert color["match"]["product_color_primary"]["query"] == "black blue"

    def test_array_size_coerced(self) -> None:
        agent = _agent_returning_attributes({"size": ["XL"]})
        filters = agent._extract_attributes("size XL shirt please")
        _all_query_fields_are_strings(filters)
        assert filters[0]["multi_match"]["query"] == "XL"

    def test_empty_array_dropped(self) -> None:
        # An empty array shouldn't produce a clause at all — that would
        # send {"query": ""} which OpenSearch will reject differently.
        agent = _agent_returning_attributes({"material_or_feature": [], "brand": None, "color": ""})
        filters = agent._extract_attributes("vague refinement query here")
        assert filters == []

    def test_array_with_nulls_filtered(self) -> None:
        # Defensive: if the LLM emits [null, "noise canceling"], drop the null.
        agent = _agent_returning_attributes({"material_or_feature": [None, "noise canceling", ""]})
        filters = agent._extract_attributes("only noise cancelling ones")
        _all_query_fields_are_strings(filters)
        assert filters[0]["multi_match"]["query"] == "noise canceling"
