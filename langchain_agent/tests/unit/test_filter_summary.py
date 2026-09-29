"""Unit tests for _format_filter_summary DSL filter parser."""

import pytest


@pytest.fixture
def agent():
    """Create an EcommerceSearchAgent instance for testing."""
    # Create a minimal agent without full initialization (mocks not needed for filter summary)
    import unittest.mock as mock

    from main import EcommerceSearchAgent

    agent = mock.MagicMock(spec=EcommerceSearchAgent)
    # Bind the real _format_filter_summary method
    agent._format_filter_summary = EcommerceSearchAgent._format_filter_summary.__get__(
        agent, EcommerceSearchAgent
    )
    return agent


def test_format_filter_summary_with_brand_filter(agent):
    """Test filter summary formatting for brand match filter."""
    filters = [{"match": {"product_brand_normalized": {"query": "Sony"}}}]

    result = agent._format_filter_summary(filters)

    assert result == "brand: Sony"


def test_format_filter_summary_with_color_filter(agent):
    """Test filter summary formatting for color match filter.

    Regression test: _extract_attribute_filters builds color filters keyed
    on "product_color_primary" (see pipeline_nodes.py), not the bare
    "product_color" this test asserted against prior to 2026-09-14. That
    mismatch meant this test was silently locking in a bug where no color
    filter's summary text ever rendered in the UI, even though the filter
    itself worked correctly against OpenSearch.
    """
    filters = [{"match": {"product_color_primary": {"query": "black"}}}]

    result = agent._format_filter_summary(filters)

    assert result == "color: black"


def test_format_filter_summary_with_waterproof_filter(agent):
    """Test filter summary formatting for a resolved waterproof match filter.

    Regression test: this branch didn't exist at all prior to 2026-09-14 --
    a resolved attribute filter on this field (product_material_primary at
    the time; product_waterproof_primary since the material->waterproof
    swap) silently vanished from the summary with no branch to catch it.
    """
    filters = [{"match": {"product_waterproof_primary": {"query": "waterproof"}}}]

    result = agent._format_filter_summary(filters)

    assert result == "waterproof: waterproof"


def test_format_filter_summary_with_multiple_filters(agent):
    """Test filter summary formatting with multiple filters."""
    filters = [
        {"match": {"product_brand_normalized": {"query": "Sony"}}},
        {"multi_match": {"query": "mesh", "fields": ["title", "chunk_text"]}},
    ]

    result = agent._format_filter_summary(filters)

    assert "brand: Sony" in result
    assert "feature: mesh" in result


def test_format_filter_summary_with_empty_filters(agent):
    """Test filter summary formatting with empty filters."""
    filters = []

    result = agent._format_filter_summary(filters)

    assert result is None


def test_format_filter_summary_with_none_filters(agent):
    """Test filter summary formatting with None filters."""
    result = agent._format_filter_summary(None)

    assert result is None
