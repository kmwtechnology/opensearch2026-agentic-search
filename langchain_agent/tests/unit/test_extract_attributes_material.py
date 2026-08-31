"""
Unit tests for the material_or_feature classify-then-branch logic added to
_extract_attributes: a term that resolves against the product_material
taxonomy gets an exact filter against product_material_primary (mirroring
brand/color); a term that doesn't resolve (a non-material feature like
"waterproof", or a material outside the taxonomy) falls back to the prior
lexical multi_match unchanged.

AttributeMappingStore is mocked so these tests never depend on live
OpenSearch state (tests/unit/ convention: zero service dependency) — the
static MATERIAL_CANONICALS dictionary alone is enough to exercise both
branches.
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
class TestMaterialClassification:
    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_known_material_gets_exact_filter(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"material_or_feature": "leather"})

        filters = agent._extract_attributes("leather boots")

        assert filters == [{"match": {"product_material_primary": {"query": "leather"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_material_variant_resolves_to_canonical(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"material_or_feature": "cowhide"})

        filters = agent._extract_attributes("cowhide wallet")

        assert filters == [{"match": {"product_material_primary": {"query": "leather"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_non_material_feature_falls_back_to_lexical(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes({"material_or_feature": "waterproof"})

        filters = agent._extract_attributes("waterproof jacket")

        assert filters == [
            {
                "multi_match": {
                    "query": "waterproof",
                    "fields": ["title", "chunk_text"],
                    "type": "best_fields",
                }
            }
        ]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_agent_learned_variant_from_os_resolves(self, mock_store_cls) -> None:
        """A variant the live flywheel wrote to OpenSearch (not in the static
        MATERIAL_CANONICALS seed dict) must also resolve, proving the OS
        lookup is actually consulted, not just the static seed."""
        mock_store_cls.return_value.get_lookup_table.return_value = {"vegan suede": "leather"}
        agent = _agent_returning_attributes({"material_or_feature": "vegan suede"})

        filters = agent._extract_attributes("vegan suede handbag")

        assert filters == [{"match": {"product_material_primary": {"query": "leather"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_opensearch_unavailable_falls_back_gracefully(self, mock_store_cls) -> None:
        """If OS is unreachable, classification degrades to the static seed
        dict rather than crashing — "leather" still resolves via dictionary
        match even with zero OS-sourced data."""
        mock_store_cls.return_value.get_lookup_table.side_effect = ConnectionError("no OS")
        agent = _agent_returning_attributes({"material_or_feature": "leather"})

        filters = agent._extract_attributes("leather boots")

        assert filters == [{"match": {"product_material_primary": {"query": "leather"}}}]

    @patch("attribute_mapping_store.AttributeMappingStore")
    def test_mixed_query_classifies_material_and_leaves_others_intact(self, mock_store_cls) -> None:
        mock_store_cls.return_value.get_lookup_table.return_value = {}
        agent = _agent_returning_attributes(
            {"brand": "Sony", "color": "black", "material_or_feature": "leather"}
        )

        filters = agent._extract_attributes("black leather Sony headphones")

        assert {"match": {"product_brand_normalized": {"query": "Sony"}}} in filters
        assert {"match": {"product_color_primary": {"query": "black"}}} in filters
        assert {"match": {"product_material_primary": {"query": "leather"}}} in filters
        assert len(filters) == 3
