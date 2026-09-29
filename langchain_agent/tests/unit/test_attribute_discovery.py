"""Unit tests for attribute_discovery — pure logic, no external services."""

import pytest

from retrieval.attribute_discovery import (
    COLOR_CANONICALS,
    WATERPROOF_CANONICALS,
    single_term_classify,
)


@pytest.fixture
def seeds():
    return {
        "leather": ["leather", "genuine leather", "cowhide", "faux leather"],
        "cotton": ["cotton", "100% cotton"],
        "metal": ["stainless steel", "aluminum"],
    }


class TestSingleTermClassify:
    def test_exact_match_against_seed_variant(self, seeds):
        assert single_term_classify("cowhide", seeds) == "leather"

    def test_case_insensitive(self, seeds):
        assert single_term_classify("COWHIDE", seeds) == "leather"

    def test_existing_lookup_short_circuits(self, seeds):
        existing = {"vegan leather": "leather"}
        result = single_term_classify("vegan leather", seeds, existing_lookup=existing)
        assert result == "leather"

    def test_substring_match_term_contains_variant(self, seeds):
        # "vegan leather" contains the known variant "leather"
        result = single_term_classify("vegan leather", seeds)
        assert result == "leather"

    def test_unclassifiable_returns_none_without_llm_fallback(self, seeds):
        assert single_term_classify("chartreuse polka dots", seeds) is None


class TestWaterproofCanonicals:
    def test_seed_dict_has_the_registered_bucket(self):
        assert isinstance(WATERPROOF_CANONICALS, dict)
        assert "waterproof" in WATERPROOF_CANONICALS

    def test_seed_variants_are_deliberately_empty(self):
        """Unlike color, WATERPROOF_CANONICALS ships with zero seed variants
        by design (see the module docstring) — this is what makes a fresh
        cluster's first "waterproof hiking boots" query a genuine,
        reproducible gap rather than a coincidence. The canonical KEY still
        has to exist so trigger_enrichment has a known, bounded bucket to
        write into."""
        assert WATERPROOF_CANONICALS["waterproof"] == []

    def test_unresolvable_until_the_live_flywheel_grows_it(self):
        assert single_term_classify("waterproof", WATERPROOF_CANONICALS) is None


class TestColorCanonicals:
    def test_seed_dict_has_expected_shape(self):
        assert isinstance(COLOR_CANONICALS, dict)
        assert len(COLOR_CANONICALS) > 0
        for canonical, variants in COLOR_CANONICALS.items():
            assert isinstance(canonical, str)
            assert isinstance(variants, list)
            assert len(variants) > 0

    def test_known_canonical_buckets_present(self):
        for expected in ["black", "white", "blue", "red", "gray"]:
            assert expected in COLOR_CANONICALS

    def test_known_variants_classify_to_their_bucket(self):
        assert single_term_classify("charcoal", COLOR_CANONICALS) == "black"
        assert single_term_classify("navy", COLOR_CANONICALS) == "blue"
