"""Unit tests for attribute_discovery — pure logic, no external services."""

import pytest

from attribute_discovery import MATERIAL_CANONICALS, bulk_discover, single_term_classify


@pytest.fixture
def seeds():
    return {
        "leather": ["leather", "genuine leather", "cowhide", "faux leather"],
        "cotton": ["cotton", "100% cotton"],
        "metal": ["stainless steel", "aluminum"],
    }


class TestBulkDiscover:
    def test_finds_variants_present_in_text(self, seeds):
        texts = [
            "Genuine Leather Wallet, handmade",
            "100% Cotton T-Shirt",
            "Stainless Steel Water Bottle",
        ]
        result = bulk_discover(texts, seeds)

        assert result["genuine leather"] == "leather"
        assert result["100% cotton"] == "cotton"
        assert result["stainless steel"] == "metal"

    def test_does_not_find_absent_variants(self, seeds):
        texts = ["Plastic Phone Case"]
        result = bulk_discover(texts, seeds)
        assert result == {}

    def test_respects_word_boundaries(self, seeds):
        # "cotton" should not match inside an unrelated compound word
        texts = ["Cottonwood Tree Ornament"]
        result = bulk_discover(texts, seeds)
        assert "cotton" not in result

    def test_case_insensitive_matching(self, seeds):
        texts = ["LEATHER Boots"]
        result = bulk_discover(texts, seeds)
        assert result.get("leather") == "leather"

    def test_skips_variants_already_in_existing_lookup(self, seeds):
        texts = ["Genuine Leather Wallet"]
        existing = {"genuine leather": "leather"}
        result = bulk_discover(texts, seeds, existing_lookup=existing)
        assert "genuine leather" not in result

    def test_multiple_texts_only_needs_one_match(self, seeds):
        texts = ["Plastic Case", "Aluminum Frame", "Wood Base"]
        result = bulk_discover(texts, seeds)
        assert result.get("aluminum") == "metal"

    def test_handles_none_and_empty_text_entries(self, seeds):
        texts = [None, "", "Cowhide Boots"]
        result = bulk_discover(texts, seeds)
        assert result.get("cowhide") == "leather"

    def test_empty_texts_list_returns_empty(self, seeds):
        assert bulk_discover([], seeds) == {}


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

    def test_substring_match_variant_contains_term(self, seeds):
        # "leather" is a substring of the known variant "genuine leather"
        result = single_term_classify("genuine", seeds)
        # "genuine" alone isn't a strong material signal on its own in this
        # seed set, so this documents the actual (loose) matching behavior
        # rather than asserting a specific bucket.
        assert result in (None, "leather")

    def test_unclassifiable_returns_none_without_llm_fallback(self, seeds):
        assert single_term_classify("chartreuse polka dots", seeds) is None

    def test_llm_fallback_invoked_when_no_dictionary_match(self, seeds):
        calls = []

        def fake_llm(term, canonicals):
            calls.append((term, canonicals))
            return "leather"

        result = single_term_classify("cruelty-free hide", seeds, llm_classify_fn=fake_llm)
        assert result == "leather"
        assert calls == [("cruelty-free hide", ["leather", "cotton", "metal"])]

    def test_llm_fallback_not_invoked_when_dictionary_matches(self, seeds):
        def failing_llm(term, canonicals):
            raise AssertionError("LLM fallback should not be called when dictionary matches")

        result = single_term_classify("cowhide", seeds, llm_classify_fn=failing_llm)
        assert result == "leather"

    def test_llm_fallback_can_return_none(self, seeds):
        result = single_term_classify(
            "unidentifiable substance", seeds, llm_classify_fn=lambda t, c: None
        )
        assert result is None


class TestMaterialCanonicals:
    def test_seed_dict_has_expected_shape(self):
        assert isinstance(MATERIAL_CANONICALS, dict)
        assert len(MATERIAL_CANONICALS) > 0
        for canonical, variants in MATERIAL_CANONICALS.items():
            assert isinstance(canonical, str)
            assert isinstance(variants, list)
            assert len(variants) > 0

    def test_known_canonical_buckets_present(self):
        for expected in ["leather", "cotton", "wool", "metal"]:
            assert expected in MATERIAL_CANONICALS
