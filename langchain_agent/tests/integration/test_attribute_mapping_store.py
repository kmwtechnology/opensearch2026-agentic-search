"""
Integration tests for AttributeMappingStore — the OpenSearch-backed
variant->canonical mapping store that replaces bundled JSON files
(color_mappings.json) and backs the live enrichment flywheel.

Requires a live local OpenSearch (docker compose up -d). Uses a dedicated
test index, torn down after each test, so it never touches the real
agentic_hybrid_search_attribute_mappings index.
"""

import pytest

from retrieval import attribute_mapping_store as store_module
from retrieval.attribute_mapping_store import AttributeMappingStore

pytestmark = pytest.mark.integration

TEST_INDEX = "test_attribute_mappings"


@pytest.fixture
def store(monkeypatch):
    """AttributeMappingStore pointed at a throwaway index, cleaned up after the test.

    get_lookup_table() caches by (INDEX_NAME, attribute_type) (see #25), which
    structurally isolates this throwaway index's cache entries from the real
    index's -- but every test in this file shares the SAME TEST_INDEX name,
    so cache entries would otherwise leak across tests (e.g. a "color"
    lookup cached by one test surviving into the next test's fresh index).
    Explicitly clearing the cache on both sides of the test is what actually
    guarantees per-test isolation here.
    """
    monkeypatch.setattr(store_module, "INDEX_NAME", TEST_INDEX)
    store_module._clear_lookup_cache()
    s = AttributeMappingStore()
    s.client.indices.delete(index=TEST_INDEX, ignore=[404])
    yield s
    s.client.indices.delete(index=TEST_INDEX, ignore=[404])
    store_module._clear_lookup_cache()


class TestBasicReadWrite:
    def test_add_then_immediate_read_is_consistent(self, store):
        """Default refresh=True means a write is searchable on the very next call."""
        added = store.add_mapping("color", "jet black", "black", source="test")
        assert added is True

        lookup = store.get_lookup_table("color")
        assert lookup.get("jet black") == "black"

    def test_get_mapping_single_lookup(self, store):
        store.add_mapping("material", "vegan leather", "leather", source="test")
        assert store.get_mapping("material", "vegan leather") == "leather"
        assert store.get_mapping("material", "nonexistent") is None

    def test_variant_lookup_is_case_insensitive(self, store):
        store.add_mapping("color", "Jet Black", "black", source="test")
        assert store.get_mapping("color", "JET BLACK") == "black"
        assert store.get_mapping("color", "jet black") == "black"

    def test_unknown_attribute_type_returns_empty(self, store):
        assert store.get_lookup_table("nonexistent") == {}

    def test_lookup_on_never_created_index_returns_empty(self, store):
        """get_lookup_table must not crash before any write has ever happened
        (ensure_index_exists is only called by write paths)."""
        store.client.indices.delete(index=store_module.INDEX_NAME, ignore=[404])
        assert store.get_lookup_table("color") == {}


class TestIdempotency:
    def test_re_adding_same_mapping_returns_false(self, store):
        first = store.add_mapping("color", "jet black", "black", source="test")
        second = store.add_mapping("color", "jet black", "black", source="test")
        assert first is True
        assert second is False

    def test_remapping_to_different_canonical_updates_in_place(self, store):
        store.add_mapping("color", "jet black", "black", source="test")
        store.add_mapping("color", "jet black", "gray", source="agent")
        assert store.get_mapping("color", "jet black") == "gray"

        # only one doc should exist for this variant, not two
        lookup = store.get_lookup_table("color")
        assert lookup["jet black"] == "gray"


class TestAttributeTypeIsolation:
    def test_color_and_material_do_not_leak(self, store):
        store.add_mapping("color", "jet black", "black", source="test")
        store.add_mapping("material", "vegan leather", "leather", source="test")

        color_lookup = store.get_lookup_table("color")
        material_lookup = store.get_lookup_table("material")

        assert "vegan leather" not in color_lookup
        assert "jet black" not in material_lookup
        assert color_lookup == {"jet black": "black"}
        assert material_lookup == {"vegan leather": "leather"}


class TestBulkOperations:
    def test_migrate_from_dict_adds_all_variants_and_is_immediately_queryable(self, store):
        mapping_dict = {
            "red": ["red", "crimson", "scarlet"],
            "blue": ["blue", "navy", "cyan"],
        }
        count = store.migrate_from_dict("color", mapping_dict)
        assert count == 6

        lookup = store.get_lookup_table("color")
        assert lookup["crimson"] == "red"
        assert lookup["navy"] == "blue"
        assert len(lookup) == 6

    def test_migrate_from_dict_is_idempotent_on_rerun(self, store):
        mapping_dict = {"red": ["red", "crimson"]}
        first_count = store.migrate_from_dict("color", mapping_dict)
        second_count = store.migrate_from_dict("color", mapping_dict)
        assert first_count == 2
        assert second_count == 0

    def test_seed_from_discovery_adds_variant_canonical_pairs(self, store):
        discovered = {"vegan leather": "leather", "cowhide": "leather", "cotton blend": "cotton"}
        count = store.seed_from_discovery("material", discovered)
        assert count == 3

        lookup = store.get_lookup_table("material")
        assert lookup["cowhide"] == "leather"
        assert lookup["cotton blend"] == "cotton"


class TestLiveFlywheelScenario:
    """Simulates the exact live-demo path: agent discovers a gap, writes it,
    and must be able to read it back immediately (no eventual-consistency lag)
    since the very next step is a scoped update_by_query against the new term."""

    def test_write_then_immediate_lookup_supports_synchronous_flywheel(self, store):
        # Seed the initial taxonomy (bulk, as if from Phase A bootstrap)
        store.seed_from_discovery("material", {"leather": "leather", "cotton": "cotton"})

        # Live agent turn: a gap term appears, agent classifies + writes it
        store.add_mapping("material", "vegan leather", "leather", source="agent")

        # Immediately-next step in the same turn must see it (no refresh call needed)
        lookup = store.get_lookup_table("material")
        assert lookup["vegan leather"] == "leather"
        assert lookup["leather"] == "leather"
        assert lookup["cotton"] == "cotton"

    def test_write_invalidates_an_already_populated_cache(self, store):
        """Regression coverage for #25's get_lookup_table() cache: a lookup
        BEFORE the write must not shadow the write from a lookup AFTER it.
        (The scenario above doesn't actually exercise this -- its first
        get_lookup_table() call happens after every write, so the cache is
        never populated with stale data to invalidate in the first place.)
        """
        store.add_mapping("material", "leather", "leather", source="test")

        # Populate the cache with the pre-write state.
        first_lookup = store.get_lookup_table("material")
        assert "vegan leather" not in first_lookup

        # Live agent turn: a new gap term is classified and written.
        store.add_mapping("material", "vegan leather", "leather", source="agent")

        # The next lookup must reflect the write, not the cached pre-write table.
        second_lookup = store.get_lookup_table("material")
        assert second_lookup.get("vegan leather") == "leather"
