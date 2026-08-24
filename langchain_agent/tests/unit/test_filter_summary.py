"""Unit tests for _format_filter_summary DSL filter parser."""

import logging

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
    filters = [{"match": {"product_brand": {"query": "Sony"}}}]

    result = agent._format_filter_summary(filters)

    assert result == "brand: Sony"


def test_format_filter_summary_with_color_filter(agent):
    """Test filter summary formatting for color match filter."""
    filters = [{"match": {"product_color": {"query": "black"}}}]

    result = agent._format_filter_summary(filters)

    assert result == "color: black"


def test_format_filter_summary_with_price_range(agent):
    """Test filter summary formatting for price range filter."""
    filters = [{"range": {"price": {"gte": 50.0, "lte": 200.0}}}]

    result = agent._format_filter_summary(filters)

    assert "price: over $50.0" in result
    assert "price: under $200.0" in result


def test_format_filter_summary_with_multiple_filters(agent):
    """Test filter summary formatting with multiple filters."""
    filters = [
        {"match": {"product_brand": {"query": "Sony"}}},
        {"range": {"price": {"lte": 100.0}}},
    ]

    result = agent._format_filter_summary(filters)

    assert "brand: Sony" in result
    assert "price: under $100.0" in result


def test_format_filter_summary_with_empty_filters(agent):
    """Test filter summary formatting with empty filters."""
    filters = []

    result = agent._format_filter_summary(filters)

    assert result is None


def test_format_filter_summary_with_none_filters(agent):
    """Test filter summary formatting with None filters."""
    result = agent._format_filter_summary(None)

    assert result is None


def test_format_filter_summary_with_malformed_filters(agent, caplog):
    """Test filter summary handles malformed filters gracefully."""
    filters = [
        {"match": {"product_brand": None}},  # Malformed: None value
        {"range": {"price": {"invalid_key": 100}}},  # Malformed: invalid key
    ]

    with caplog.at_level(logging.WARNING):
        result = agent._format_filter_summary(filters)

    # Should handle gracefully and return None (or partial result)
    # The warning should be logged
    assert any("filter summary" in record.message.lower() for record in caplog.records)


def test_format_filter_summary_with_corrupted_structure(agent, caplog):
    """Test filter summary handles corrupted data structure."""
    # Deeply corrupted data that will cause iteration issues
    filters = [{"match": {"product_brand": {"query": {"nested": "dict"}}}}]

    with caplog.at_level(logging.WARNING):
        result = agent._format_filter_summary(filters)

    # Should fail gracefully without raising
    assert result is None or isinstance(result, str)
    # If exception occurred, warning should be logged
    if result is None:
        assert any("filter summary" in record.message.lower() for record in caplog.records)
