"""Tests for attribute filter relaxation in the retriever node.

When an attribute_filter query returns very few results because a feature
(multi_match) filter is too narrow, the retriever drops those multi_match
filters and retries with only the hard filters (color, waterproof, brand)
that the user explicitly asked for.

Filter shapes (as returned by _extract_attributes):
  color:      {"match": {"product_color": ...}}
  waterproof: {"match": {"product_waterproof_primary": ...}}
  brand:      {"match": {"product_brand": ...}}
  feature:    {"multi_match": {"fields": ["title", "chunk_text"], ...}}
  size:       {"multi_match": {"fields": ["title", "chunk_text"], ...}}

The relaxation logic drops filters with a "multi_match" key.
"""

from __future__ import annotations

import pytest

COLOR_FILTER = {"match": {"product_color": {"query": "red"}}}
WATERPROOF_FILTER = {"match": {"product_waterproof_primary": {"query": "waterproof"}}}
BRAND_FILTER = {"match": {"product_brand": {"query": "Nike"}}}
FEATURE_FILTER = {
    "multi_match": {
        "query": "athletic",
        "fields": ["title", "chunk_text"],
        "type": "best_fields",
    }
}
SIZE_FILTER = {
    "multi_match": {
        "query": "size 10",
        "fields": ["title", "chunk_text"],
        "type": "best_fields",
    }
}


def _hard_filters(filters: list) -> list:
    """Mirror of the relaxation logic: keep only non-multi_match filters."""
    return [f for f in filters if "multi_match" not in f]


@pytest.mark.unit
class TestFilterRelaxationLogic:
    def test_identifies_feature_filter_as_soft(self):
        filters = [COLOR_FILTER, FEATURE_FILTER]
        hard = _hard_filters(filters)
        assert hard == [COLOR_FILTER]
        assert len(hard) < len(filters)

    def test_identifies_size_filter_as_soft(self):
        filters = [COLOR_FILTER, SIZE_FILTER]
        hard = _hard_filters(filters)
        assert hard == [COLOR_FILTER]

    def test_keeps_color_and_brand_as_hard(self):
        filters = [COLOR_FILTER, BRAND_FILTER]
        hard = _hard_filters(filters)
        assert hard == [COLOR_FILTER, BRAND_FILTER]
        assert len(hard) == len(filters), "Color + brand should never be relaxed away"

    def test_keeps_waterproof_as_hard(self):
        """Deliberately unlike the old material field: waterproof always
        hard-filters (resolved or not, see _extract_attributes), so it must
        survive relaxation exactly like color does — this is load-bearing
        for the live gap-fill demo, which depends on a zero-result query
        staying at zero results rather than getting relaxed back to a
        non-empty result set."""
        filters = [WATERPROOF_FILTER, BRAND_FILTER]
        hard = _hard_filters(filters)
        assert hard == [WATERPROOF_FILTER, BRAND_FILTER]
        assert len(hard) == len(filters)

    def test_no_multi_match_means_no_relaxation_needed(self):
        filters = [COLOR_FILTER, BRAND_FILTER]
        hard = _hard_filters(filters)
        assert len(hard) == len(filters), "No relaxation when only hard filters present"

    def test_all_soft_filters_cleared_on_full_relaxation(self):
        filters = [FEATURE_FILTER, SIZE_FILTER]
        hard = _hard_filters(filters)
        assert hard == [], "All soft filters removed; caller should pass None to retriever"

    def test_mixed_filters_keeps_only_hard(self):
        filters = [COLOR_FILTER, WATERPROOF_FILTER, BRAND_FILTER, FEATURE_FILTER, SIZE_FILTER]
        hard = _hard_filters(filters)
        assert hard == [COLOR_FILTER, WATERPROOF_FILTER, BRAND_FILTER]

    def test_empty_filter_list_no_op(self):
        assert _hard_filters([]) == []

    def test_relaxation_triggered_only_when_multi_match_present(self):
        only_hard = [COLOR_FILTER, BRAND_FILTER]
        hard = _hard_filters(only_hard)
        should_relax = len(hard) < len(only_hard)
        assert not should_relax, "Should not relax when no multi_match filters"

    def test_relaxation_triggered_when_multi_match_present(self):
        mixed = [COLOR_FILTER, FEATURE_FILTER]
        hard = _hard_filters(mixed)
        should_relax = len(hard) < len(mixed)
        assert should_relax, "Should relax when multi_match filters present"
