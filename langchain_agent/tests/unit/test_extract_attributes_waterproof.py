"""
Unit tests for the waterproof classify-then-branch logic in
_extract_attributes: like color, a resolved term gets an exact filter using
the CANONICAL value; an unresolved term falls back to using the raw
LLM-extracted value directly — always a hard `match` against
product_waterproof_primary, never the generic feature field's lexical
multi_match.

WATERPROOF_CANONICALS (retrieval/attribute_discovery.py) ships with a
registered "waterproof" bucket but ZERO seed variants, by design — unlike
color, there is no static dictionary match to fall back on, so resolution
depends entirely on what the live OS-backed store has learned. This is what
makes a fresh cluster's first "waterproof hiking boots" query a genuine,
reproducible gap rather than a coincidence.

AttributeMappingStore is mocked so these tests never depend on live
OpenSearch state (tests/unit/ convention: zero service dependency).
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from main import EcommerceSearchAgent


class _Resp:
    def __init__(self, content: Any) -> None:
        self.content = content


def _agent_returning_attributes(payload: dict) -> EcommerceSearchAgent:
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.alpha_estimator_llm = MagicMock()
    agent.alpha_estimator_llm.invoke.return_value = _Resp(json.dumps(payload))
    return agent


@pytest.mark.unit
@pytest.mark.phase1
class TestWaterproofClassification:
    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_unmapped_term_hard_filters_on_raw_value(self, mock_store_cls) -> None:
        """The gap case: WATERPROOF_CANONICALS has zero seed variants and the
        store is empty, so "waterproof" cannot resolve — it must still
        produce a HARD match filter (on the raw term), not a soft
        multi_match, since this is exactly the zero-result signal the live
        enrichment flywheel depends on to offer trigger_enrichment."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"waterproof": "waterproof"})

        filters = agent._extract_attributes("waterproof hiking boots")

        assert filters == [{"match": {"product_waterproof_primary": {"query": "waterproof"}}}]

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_agent_learned_variant_from_os_resolves(self, mock_store_cls) -> None:
        """A variant the live flywheel wrote to OpenSearch (there is no
        static seed to fall back on for waterproof) must resolve to its
        canonical, proving the OS lookup is actually consulted."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"weatherproof": "waterproof"}
        agent = _agent_returning_attributes({"waterproof": "weatherproof"})

        filters = agent._extract_attributes("weatherproof jacket")

        assert filters == [{"match": {"product_waterproof_primary": {"query": "waterproof"}}}]

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_opensearch_unavailable_falls_back_to_raw_term(self, mock_store_cls) -> None:
        """If OS is unreachable, classification degrades gracefully (no
        static seed to fall back on either) — the raw term is still used
        as a hard filter rather than crashing or silently dropping it."""
        mock_store_cls.return_value.get_lookup_table.side_effect = ConnectionError("no OS")
        agent = _agent_returning_attributes({"waterproof": "waterproof"})

        filters = agent._extract_attributes("waterproof hiking boots")

        assert filters == [{"match": {"product_waterproof_primary": {"query": "waterproof"}}}]

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_mixed_query_classifies_waterproof_and_color_independently(
        self, mock_store_cls
    ) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes(
            {"brand": "Sony", "color": "black", "waterproof": "waterproof"}
        )

        filters = agent._extract_attributes("black waterproof Sony headphones")

        assert {"match": {"product_brand_normalized": {"query": "Sony"}}} in filters
        assert {"match": {"product_color_primary": {"query": "black"}}} in filters
        assert {"match": {"product_waterproof_primary": {"query": "waterproof"}}} in filters
        assert len(filters) == 3

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_generic_feature_term_still_falls_back_to_lexical(self, mock_store_cls) -> None:
        """Everything that isn't a color or a waterproofing requirement
        (e.g. "breathable") has no taxonomy and stays a soft multi_match —
        deliberately unlike waterproof, which always hard-filters."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"feature": "breathable"})

        filters = agent._extract_attributes("breathable jacket")

        assert filters == [
            {
                "multi_match": {
                    "query": "breathable",
                    "fields": ["title", "chunk_text"],
                    "type": "best_fields",
                }
            }
        ]

    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    def test_waterproof_and_feature_both_present_are_independent(self, mock_store_cls) -> None:
        """A query naming both a waterproofing requirement and an unrelated
        feature word extracts two distinct filters: a hard match for
        waterproof, a soft multi_match for the generic feature."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"waterproof": "waterproof", "feature": "breathable"})

        filters = agent._extract_attributes("breathable waterproof jacket")

        assert {"match": {"product_waterproof_primary": {"query": "waterproof"}}} in filters
        assert {
            "multi_match": {
                "query": "breathable",
                "fields": ["title", "chunk_text"],
                "type": "best_fields",
            }
        } in filters
        assert len(filters) == 2
