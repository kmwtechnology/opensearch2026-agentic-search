"""
Unit tests for the color classify-then-branch logic in _extract_attributes:
a term that resolves against the product_color taxonomy gets an exact
filter using the CANONICAL value (fixing variant spellings like "grey" not
matching an index normalized to "gray"); a term that doesn't resolve falls
back to using the raw LLM-extracted value directly, matching pre-existing
behavior (color, unlike material_or_feature, has no lexical multi_match
fallback path — it never did before this change either).

AttributeMappingStore is mocked so these tests never depend on live
OpenSearch state — the static COLOR_CANONICALS dictionary alone is enough
to exercise both branches.
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
class TestColorClassification:
    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_canonical_color_resolves_to_itself(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"color": "black"})

        filters = agent._extract_attributes("black boots")

        assert filters == [{"match": {"product_color_primary": {"query": "black"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_variant_spelling_resolves_to_canonical(self, mock_store_cls) -> None:
        """'grey' must resolve to 'gray' — the index is only ever tagged
        with the canonical spelling, so the raw variant would silently
        match nothing without this classify step."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"color": "grey"})

        filters = agent._extract_attributes("grey sneakers")

        assert filters == [{"match": {"product_color_primary": {"query": "gray"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_unresolved_color_falls_back_to_raw_term(self, mock_store_cls) -> None:
        """Unlike material_or_feature, color has no lexical multi_match
        fallback — an unclassified term is used as-is, matching the
        pre-existing (pre-classification) behavior exactly."""
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"color": "iridescent"})

        filters = agent._extract_attributes("iridescent phone case")

        assert filters == [{"match": {"product_color_primary": {"query": "iridescent"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_agent_learned_variant_from_os_resolves(self, mock_store_cls) -> None:
        """A variant the live flywheel wrote to OpenSearch (not in the
        static COLOR_CANONICALS seed dict) must also resolve."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"periwinkle": "blue"}
        agent = _agent_returning_attributes({"color": "periwinkle"})

        filters = agent._extract_attributes("periwinkle dress")

        assert filters == [{"match": {"product_color_primary": {"query": "blue"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_opensearch_unavailable_falls_back_gracefully(self, mock_store_cls) -> None:
        """If OS is unreachable, classification degrades to the static seed
        dict rather than crashing — 'black' still resolves via dictionary
        match even with zero OS-sourced data."""
        mock_store_cls.return_value.get_lookup_table.side_effect = ConnectionError("no OS")
        agent = _agent_returning_attributes({"color": "black"})

        filters = agent._extract_attributes("black boots")

        assert filters == [{"match": {"product_color_primary": {"query": "black"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_mixed_query_classifies_color_and_material_independently(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes(
            {"brand": "Sony", "color": "grey", "material_or_feature": "leather"}
        )

        filters = agent._extract_attributes("grey leather Sony headphones")

        assert {"match": {"product_brand_normalized": {"query": "Sony"}}} in filters
        assert {"match": {"product_color_primary": {"query": "gray"}}} in filters
        assert {"match": {"product_material_primary": {"query": "leather"}}} in filters
        assert len(filters) == 3
