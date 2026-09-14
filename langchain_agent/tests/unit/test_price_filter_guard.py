"""
A price constraint must never silently empty the result set (#103).

OpenSearch does not error on a range filter against an unmapped field — it
just matches nothing. The ESCI product index has no `price` field, so every
"under $100" query returned zero documents and the user was told no product
matched, as though the catalog held nothing affordable.

The code already carried the comment "(if price field exists in index)"; the
check it described was never written. These tests pin it, in both directions.
"""

import json
from unittest.mock import MagicMock

from main import EcommerceSearchAgent


def _agent_with_index_fields(fields, attributes):
    """Agent whose attribute extractor returns `attributes` verbatim and whose
    index reports exactly `fields` as mapped."""
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.vector_store = MagicMock()
    agent.vector_store.has_field.side_effect = lambda f: f in fields
    agent.alpha_estimator_llm = MagicMock()
    agent.alpha_estimator_llm.invoke.return_value = json.dumps(attributes)
    return agent


def _price_filters(filters):
    return [f for f in filters if "range" in f and "price" in f["range"]]


class TestPriceFilterGuard:
    def test_price_filter_skipped_when_index_has_no_price_field(self):
        agent = _agent_with_index_fields({"title", "product_color_primary"}, {"price_max": 100})

        filters = agent._extract_attributes("wireless headphones under $100")

        assert _price_filters(filters) == [], (
            "filtering on an unmapped field matches nothing, which reads to the "
            "user as 'no such products exist'"
        )

    def test_price_filter_applied_when_the_field_is_mapped(self):
        agent = _agent_with_index_fields({"title", "price"}, {"price_max": 100, "price_min": 20})

        filters = agent._extract_attributes("headphones between $20 and $100")
        price = _price_filters(filters)

        assert {"range": {"price": {"lte": 100.0}}} in price
        assert {"range": {"price": {"gte": 20.0}}} in price

    def test_mapping_is_not_consulted_when_no_price_was_requested(self):
        """The check costs an index-mapping read on first use; queries with no
        price constraint should not pay for it."""
        agent = _agent_with_index_fields({"title", "price"}, {"color": "blue"})

        agent._extract_attributes("show me blue running shoes")

        agent.vector_store.has_field.assert_not_called()


class TestHasFieldFailsClosed:
    def test_unreadable_mapping_reports_field_missing(self):
        """If the mapping cannot be read we skip the filter and return real
        products, rather than applying a filter that might match nothing."""
        from retrieval.vector_store import OpenSearchVectorStore

        store = OpenSearchVectorStore.__new__(OpenSearchVectorStore)
        store.client = MagicMock()
        store.client.indices.get_mapping.side_effect = RuntimeError("connection refused")
        store.index_name = "whatever"
        store._mapped_fields_cache = None

        assert store.has_field("price") is False

    def test_mapping_is_read_once_and_cached(self):
        from retrieval.vector_store import OpenSearchVectorStore

        store = OpenSearchVectorStore.__new__(OpenSearchVectorStore)
        store.client = MagicMock()
        store.client.indices.get_mapping.return_value = {
            "idx": {"mappings": {"properties": {"price": {"type": "float"}, "title": {}}}}
        }
        store.index_name = "idx"
        store._mapped_fields_cache = None

        assert store.has_field("price") is True
        assert store.has_field("title") is True
        assert store.has_field("nope") is False
        assert store.client.indices.get_mapping.call_count == 1
