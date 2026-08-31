"""
Integration tests for AttributeNormalizer's OpenSearch-backed color lookup
(use_opensearch=True, the default) — verifies it correctly sources from
AttributeMappingStore and falls back to the bundled JSON when OpenSearch
has no color data.

Requires a live local OpenSearch (docker compose up -d).
"""

import json
from pathlib import Path

import pytest

import attribute_mapping_store as store_module
from attribute_mapping_store import AttributeMappingStore
from attribute_normalizer import AttributeNormalizer

pytestmark = pytest.mark.integration

TEST_INDEX = "test_attribute_mappings_normalizer"
COLOR_MAPPINGS_PATH = (
    Path(__file__).parent.parent.parent / "lucille-esci" / "conf" / "color_mappings.json"
)


@pytest.fixture
def mapping_store(monkeypatch):
    """Point AttributeMappingStore (used internally by AttributeNormalizer)
    at a throwaway index so this test never touches real mapping data."""
    monkeypatch.setattr(store_module, "INDEX_NAME", TEST_INDEX)
    s = AttributeMappingStore()
    s.client.indices.delete(index=TEST_INDEX, ignore=[404])
    yield s
    s.client.indices.delete(index=TEST_INDEX, ignore=[404])


class TestOpenSearchBackedNormalization:
    def test_uses_opensearch_data_when_available(self, mapping_store):
        mapping_store.migrate_from_dict(
            "color", {"black": ["black", "jet black"], "blue": ["blue", "navy"]}
        )

        normalizer = AttributeNormalizer(use_opensearch=True)

        assert normalizer.normalize_color("jet black") == ("black", None)
        assert normalizer.normalize_color("navy") == ("blue", None)

    def test_agent_written_mapping_is_immediately_reflected(self, mapping_store):
        """The live-flywheel scenario: a mapping written by the agent must be
        visible to a normalizer instantiated right after, with no lag."""
        mapping_store.migrate_from_dict("color", {"black": ["black"]})
        mapping_store.add_mapping("color", "onyx", "black", source="agent")

        normalizer = AttributeNormalizer(use_opensearch=True)
        assert normalizer.normalize_color("onyx") == ("black", None)

    def test_falls_back_to_json_when_opensearch_has_no_color_data(self, mapping_store):
        """Index exists (via the fixture's delete/recreate lifecycle) but has
        no color docs — get_lookup_table returns {} and the normalizer must
        fall back to the bundled JSON rather than operating with an empty
        lookup."""
        mapping_store.ensure_index_exists()  # index exists, but zero docs

        normalizer = AttributeNormalizer(use_opensearch=True)

        # Bundled JSON still has the real 16-color taxonomy
        assert normalizer.normalize_color("black") == ("black", None)
        assert len(normalizer.color_lookup) > 0


class TestParityWithBundledJson:
    """The migrated OS data and the bundled JSON fallback must agree on
    every variant — this is the regression gate for the color migration."""

    def test_full_dataset_parity(self, mapping_store):
        with open(COLOR_MAPPINGS_PATH) as f:
            base_colors = json.load(f)["base_colors"]
        mapping_store.migrate_from_dict("color", base_colors)

        json_normalizer = AttributeNormalizer(use_opensearch=False)
        os_normalizer = AttributeNormalizer(use_opensearch=True)

        for variant, expected_canonical in json_normalizer.color_lookup.items():
            assert os_normalizer.color_lookup.get(variant) == expected_canonical, (
                f"Mismatch for '{variant}': JSON says '{expected_canonical}', "
                f"OS says '{os_normalizer.color_lookup.get(variant)}'"
            )
