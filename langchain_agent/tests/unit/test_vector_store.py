"""Unit tests for key methods in vector_store.py."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from vector_store import OpenSearchRetriever, OpenSearchVectorStore, _scrub_body_for_display

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_doc(product_id=None, score=None, source="", title=""):
    metadata = {"source": source, "title": title}
    if product_id is not None:
        metadata["product_id"] = product_id
    if score is not None:
        metadata["retrieval_score"] = score
    return Document(page_content="content", metadata=metadata)


def _make_store():
    mock_client = MagicMock()
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 768
    store = OpenSearchVectorStore.__new__(OpenSearchVectorStore)
    store.client = mock_client
    store.index_name = "test_index"
    store.embedding_function = mock_embeddings
    store.collection_id = "esci_products"
    return store, mock_client


def _make_search_response(judgments):
    """Build a mock OpenSearch search response with the given judgments list."""
    return {
        "hits": {
            "hits": [
                {
                    "_source": {
                        "judgments": judgments,
                    }
                }
            ]
        }
    }


# ---------------------------------------------------------------------------
# TestCollapseByDocument
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCollapseByDocument:

    def test_deduplicates_by_product_id(self):
        docs = [_make_doc("A"), _make_doc("A"), _make_doc("B")]
        result = OpenSearchRetriever.collapse_by_document(docs)
        assert len(result) == 2
        assert result[0].metadata["product_id"] == "A"
        assert result[1].metadata["product_id"] == "B"

    def test_keeps_first_occurrence(self):
        doc_high = _make_doc("A", score=0.9)
        doc_low = _make_doc("A", score=0.5)
        result = OpenSearchRetriever.collapse_by_document([doc_high, doc_low])
        assert len(result) == 1
        assert result[0].metadata["retrieval_score"] == 0.9

    def test_docs_without_product_id_pass_through(self):
        doc_no_id = Document(page_content="no id", metadata={"title": "x"})
        doc_with_id = _make_doc("A")
        result = OpenSearchRetriever.collapse_by_document([doc_no_id, doc_with_id])
        assert len(result) == 2

    def test_empty_list_returns_empty(self):
        assert OpenSearchRetriever.collapse_by_document([]) == []

    def test_different_collapse_field(self):
        docs = [
            Document(page_content="a", metadata={"source": "s1"}),
            Document(page_content="b", metadata={"source": "s1"}),
            Document(page_content="c", metadata={"source": "s2"}),
        ]
        result = OpenSearchRetriever.collapse_by_document(docs, collapse_field="source")
        assert len(result) == 2
        assert result[0].metadata["source"] == "s1"
        assert result[1].metadata["source"] == "s2"

    def test_preserves_order(self):
        docs = [_make_doc("A"), _make_doc("B"), _make_doc("A"), _make_doc("C")]
        result = OpenSearchRetriever.collapse_by_document(docs)
        assert [d.metadata["product_id"] for d in result] == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# TestLookupJudgments
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLookupJudgments:

    def test_returns_none_for_empty_query(self):
        store, mock_client = _make_store()
        result = store.lookup_judgments("")
        assert result is None
        mock_client.search.assert_not_called()

    def test_returns_none_when_no_hits(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = {"hits": {"hits": []}}
        result = store.lookup_judgments("blue shoes")
        assert result is None

    def test_returns_judgment_dict_on_hit(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = _make_search_response(
            [{"product_id": "p1", "relevance": 0.8}]
        )
        result = store.lookup_judgments("blue shoes")
        assert result == {"p1": 0.8}

    def test_filters_entries_without_product_id(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = _make_search_response(
            [
                {"product_id": "p1", "relevance": 1.0},
                {"relevance": 0.5},  # no product_id
            ]
        )
        result = store.lookup_judgments("query")
        assert result == {"p1": 1.0}
        assert len(result) == 1

    def test_returns_none_on_client_exception(self):
        store, mock_client = _make_store()
        mock_client.search.side_effect = Exception("connection refused")
        result = store.lookup_judgments("query")
        assert result is None

    def test_relevance_defaults_to_zero_when_missing(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = _make_search_response(
            [{"product_id": "p1"}]  # no relevance key
        )
        result = store.lookup_judgments("query")
        assert result == {"p1": 0.0}


# ---------------------------------------------------------------------------
# TestHitToDocument
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHitToDocument:

    def _make_hit(self, chunk_text="hello world", score=0.75, **extra_src):
        src = {
            "chunk_text": chunk_text,
            "source": "test_source",
            "title": "Test Title",
            "doc_type": "product",
            "url": "http://example.com",
            "collection_id": "esci_products",
            "product_id": "ASIN123",
            "product_brand": "BrandX",
            "product_color": "blue",
            **extra_src,
        }
        return {"_source": src, "_score": score}

    def test_converts_hit_to_document(self):
        hit = self._make_hit()
        doc = OpenSearchVectorStore._hit_to_document(hit)
        assert isinstance(doc, Document)
        assert doc.page_content == "hello world"
        assert doc.metadata["title"] == "Test Title"
        assert doc.metadata["product_id"] == "ASIN123"
        assert doc.metadata["product_brand"] == "BrandX"
        assert doc.metadata["product_color"] == "blue"
        assert doc.metadata["collection_id"] == "esci_products"

    def test_retrieval_score_from_hit_score(self):
        hit = self._make_hit(score=0.42)
        doc = OpenSearchVectorStore._hit_to_document(hit)
        assert doc.metadata["retrieval_score"] == pytest.approx(0.42)

    def test_retrieval_score_override(self):
        hit = self._make_hit(score=0.42)
        doc = OpenSearchVectorStore._hit_to_document(hit, retrieval_score=0.99)
        assert doc.metadata["retrieval_score"] == pytest.approx(0.99)

    def test_missing_fields_default_to_empty_string(self):
        hit = {"_source": {"chunk_text": "text"}, "_score": 0.5}
        doc = OpenSearchVectorStore._hit_to_document(hit)
        assert doc.metadata["title"] == ""
        assert doc.metadata["source"] == ""
        assert doc.metadata["product_id"] == ""

    def test_no_score_when_both_none(self):
        hit = {"_source": {"chunk_text": "text"}}  # no _score key
        doc = OpenSearchVectorStore._hit_to_document(hit, retrieval_score=None)
        assert "retrieval_score" not in doc.metadata


# ---------------------------------------------------------------------------
# Helpers shared by search tests
# ---------------------------------------------------------------------------


def _make_full_store():
    """Return an OpenSearchVectorStore with all required attrs mocked."""
    mock_client = MagicMock()
    mock_embeddings = MagicMock()
    mock_embeddings.embed_query.return_value = [0.1] * 768

    store = OpenSearchVectorStore.__new__(OpenSearchVectorStore)
    store.client = mock_client
    store.index_name = "test_index"
    store.collection_id = "esci_products"
    store.search_pipeline = "hybrid-search-pipeline"
    store.embeddings = mock_embeddings
    store._hybrid_supported = None

    # Attach a disabled embedding cache so _get_embedding always hits the mock
    from embedding_cache import EmbeddingCache

    store._embedding_cache = EmbeddingCache(enabled=False)
    return store, mock_client, mock_embeddings


def _hit(doc_id="doc1", score=0.8, title="Product A"):
    return {
        "_id": doc_id,
        "_score": score,
        "_source": {
            "chunk_text": f"text for {title}",
            "title": title,
            "source": "s",
            "product_id": doc_id,
            "collection_id": "esci_products",
        },
    }


def _search_resp(*hits):
    return {"hits": {"hits": list(hits)}}


# ---------------------------------------------------------------------------
# TestGetEmbedding
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestGetEmbedding:
    def test_calls_embed_query(self):
        store, _, mock_emb = _make_full_store()
        result = store._get_embedding("blue shoes")
        mock_emb.embed_query.assert_called_once_with("blue shoes")
        assert len(result) == 768

    def test_raises_embedding_error_on_failure(self):
        from exceptions import EmbeddingError

        store, _, mock_emb = _make_full_store()
        mock_emb.embed_query.side_effect = Exception("API down")
        with pytest.raises(EmbeddingError):
            store._get_embedding("query")


# ---------------------------------------------------------------------------
# TestCheckHybridSupport
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestCheckHybridSupport:
    def test_returns_cached_value(self):
        store, _, _ = _make_full_store()
        store._hybrid_supported = True
        assert store._check_hybrid_support() is True
        store.client.info.assert_not_called()

    def test_returns_false_for_old_version(self):
        store, mock_client, _ = _make_full_store()
        mock_client.info.return_value = {"version": {"number": "2.9.0"}}
        assert store._check_hybrid_support() is False

    def test_returns_false_when_neural_plugin_missing(self):
        store, mock_client, _ = _make_full_store()
        mock_client.info.return_value = {"version": {"number": "2.10.0"}}
        mock_client.cat.plugins.return_value = [{"component": "other-plugin"}]
        assert store._check_hybrid_support() is False

    def test_returns_true_when_neural_plugin_present(self):
        store, mock_client, _ = _make_full_store()
        mock_client.info.return_value = {"version": {"number": "2.19.1"}}
        mock_client.cat.plugins.return_value = [{"component": "neural-search"}]
        assert store._check_hybrid_support() is True

    def test_returns_false_on_exception(self):
        store, mock_client, _ = _make_full_store()
        mock_client.info.side_effect = Exception("connection error")
        assert store._check_hybrid_support() is False


# ---------------------------------------------------------------------------
# TestSimilaritySearch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestSimilaritySearch:
    def test_returns_documents(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit("p1"), _hit("p2"))
        results = store.similarity_search("headphones", k=2)
        assert len(results) == 2
        assert results[0].metadata["product_id"] == "p1"

    def test_passes_k_to_query(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp()
        store.similarity_search("query", k=5)
        body = mock_client.search.call_args[1]["body"]
        assert body["size"] == 5

    def test_returns_empty_on_exception(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.side_effect = Exception("down")
        results = store.similarity_search("query")
        assert results == []


# ---------------------------------------------------------------------------
# TestHybridSearch — routing logic
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHybridSearch:
    def test_raises_on_invalid_k(self):
        from exceptions import SearchValidationError

        store, _, _ = _make_full_store()
        with pytest.raises(SearchValidationError):
            store.hybrid_search("query", k=0)

    def test_raises_when_fetch_k_less_than_k(self):
        from exceptions import SearchValidationError

        store, _, _ = _make_full_store()
        with pytest.raises(SearchValidationError):
            store.hybrid_search("query", k=10, fetch_k=5)

    def test_alpha_zero_uses_text_search(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit())
        results = store.hybrid_search("query", k=1, fetch_k=10, alpha=0.0)
        assert len(results) == 1
        # Text-only: only one search call
        assert mock_client.search.call_count == 1

    def test_alpha_one_uses_similarity_search(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit())
        results = store.hybrid_search("query", k=1, fetch_k=10, alpha=1.0)
        assert len(results) == 1

    def test_hybrid_disabled_via_optimizations_uses_text(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit())
        store.hybrid_search("q", k=1, fetch_k=10, alpha=0.5, optimizations={"hybrid": False})
        assert mock_client.search.call_count == 1

    def test_raises_search_validation_error_for_bad_alpha(self):
        from exceptions import SearchValidationError

        store, _, _ = _make_full_store()
        store._hybrid_supported = False  # skip native path
        with pytest.raises(SearchValidationError):
            store.hybrid_search("query", k=1, fetch_k=10, alpha=1.5)


# ---------------------------------------------------------------------------
# TestHybridSearchRrf
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestHybridSearchRrf:
    def test_fuses_vector_and_text_results(self):
        store, mock_client, mock_emb = _make_full_store()
        store._hybrid_supported = False
        mock_client.search.side_effect = [
            _search_resp(_hit("p1", 0.9), _hit("p2", 0.7)),  # vector
            _search_resp(_hit("p2", 0.8), _hit("p3", 0.6)),  # text
        ]
        results = store.hybrid_search("query", k=3, fetch_k=10, alpha=0.5)
        ids = [r.metadata["product_id"] for r in results]
        assert "p2" in ids  # appears in both → highest RRF score

    def test_top_k_limit_respected(self):
        store, mock_client, _ = _make_full_store()
        store._hybrid_supported = False
        mock_client.search.side_effect = [
            _search_resp(*[_hit(f"v{i}") for i in range(5)]),
            _search_resp(*[_hit(f"t{i}") for i in range(5)]),
        ]
        results = store.hybrid_search("query", k=3, fetch_k=10, alpha=0.5)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# TestTextSearch
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTextSearch:
    def test_returns_documents(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit("p1"))
        results = store._text_search("headphones", k=1)
        assert len(results) == 1
        assert results[0].metadata["product_id"] == "p1"

    def test_returns_empty_on_exception(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.side_effect = Exception("down")
        assert store._text_search("query") == []

    def test_applies_extra_filters(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp()
        store._text_search("query", filters=[{"term": {"product_brand": "Sony"}}])
        body = mock_client.search.call_args[1]["body"]
        filter_terms = body["query"]["bool"]["filter"]
        brands = [f.get("term", {}).get("product_brand") for f in filter_terms]
        assert "Sony" in brands


# ---------------------------------------------------------------------------
# TestBm25OnlyAndStockBm25
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBm25Searches:
    def test_bm25_only_delegates_to_text_search(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit())
        results = store.bm25_only_search("query", k=1)
        assert len(results) == 1
        assert mock_client.search.call_count == 1

    def test_stock_bm25_returns_documents(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp(_hit("p1"), _hit("p2"))
        results = store.stock_bm25_search("query", k=2)
        assert len(results) == 2

    def test_stock_bm25_uses_standard_analyzer(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.return_value = _search_resp()
        store.stock_bm25_search("query")
        body = mock_client.search.call_args[1]["body"]
        mm = body["query"]["bool"]["must"][0]["multi_match"]
        assert mm["analyzer"] == "standard"

    def test_stock_bm25_returns_empty_on_exception(self):
        store, mock_client, _ = _make_full_store()
        mock_client.search.side_effect = Exception("down")
        assert store.stock_bm25_search("query") == []


# ---------------------------------------------------------------------------
# TestOpenSearchRetrieverInvoke
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenSearchRetrieverInvoke:
    def _make_retriever(self, search_type="hybrid"):
        store, mock_client, _ = _make_full_store()
        store._hybrid_supported = False
        mock_client.search.return_value = _search_resp(_hit("p1"), _hit("p2"))
        retriever = OpenSearchRetriever(
            vector_store=store,
            search_type=search_type,
            k=2,
            fetch_k=10,
            alpha=0.5,
        )
        return retriever, mock_client

    def test_invoke_with_dict_input(self):
        retriever, _ = self._make_retriever()
        results = retriever.invoke({"input": "query"})
        assert len(results) > 0

    def test_invoke_with_string_input(self):
        retriever, _ = self._make_retriever()
        results = retriever.invoke("headphones")
        assert len(results) > 0

    def test_invoke_similarity_type(self):
        retriever, mock_client = self._make_retriever(search_type="similarity")
        mock_client.search.return_value = _search_resp(_hit("p1"))
        results = retriever.invoke("query")
        assert len(results) > 0

    def test_invoke_unknown_search_type_raises(self):
        retriever, _ = self._make_retriever()
        retriever.search_type = "unknown"
        with pytest.raises(ValueError):
            retriever.invoke("query")

    def test_collapses_duplicates_for_esci(self):
        store, mock_client, _ = _make_full_store()
        store._hybrid_supported = False
        # Two hits with same product_id → should collapse to 1
        mock_client.search.side_effect = [
            _search_resp(_hit("p1", 0.9), _hit("p1", 0.7)),
            _search_resp(),
        ]
        retriever = OpenSearchRetriever(
            vector_store=store, search_type="hybrid", k=4, fetch_k=10, alpha=0.5
        )
        results = retriever.invoke("query")
        assert all(r.metadata["product_id"] == "p1" for r in results)
        assert len(results) == 1


# ---------------------------------------------------------------------------
# TestScrubBodyForDisplay
# ---------------------------------------------------------------------------


class TestScrubBodyForDisplay:
    """The DSL viewer in the observability panel needs a copy-pasteable body
    without the 768-dim embedding vector that bloats the WebSocket frame and
    is useless to a human reader."""

    def test_replaces_vector_with_placeholder(self):
        body = {"query": {"knn": {"embedding": {"vector": [0.1, 0.2, 0.3], "k": 30}}}}
        scrubbed = _scrub_body_for_display(body)
        assert scrubbed["query"]["knn"]["embedding"]["vector"] == "<EMBEDDING_OMITTED_3_DIMS>"
        assert scrubbed["query"]["knn"]["embedding"]["k"] == 30

    def test_preserves_non_embedding_keys(self):
        body = {
            "size": 4,
            "query": {"bool": {"must": [{"multi_match": {"query": "shoes", "fuzziness": "AUTO"}}]}},
        }
        scrubbed = _scrub_body_for_display(body)
        assert scrubbed == body

    def test_does_not_mutate_input(self):
        body = {"vector": [1.0, 2.0]}
        _scrub_body_for_display(body)
        assert body["vector"] == [1.0, 2.0]

    def test_handles_nested_lists(self):
        body = {
            "query": {
                "hybrid": {
                    "queries": [
                        {"knn": {"embedding": {"vector": [0.5] * 768}}},
                        {"bool": {"must": [{"match": {"title": "x"}}]}},
                    ]
                }
            }
        }
        scrubbed = _scrub_body_for_display(body)
        assert (
            scrubbed["query"]["hybrid"]["queries"][0]["knn"]["embedding"]["vector"]
            == "<EMBEDDING_OMITTED_768_DIMS>"
        )
        assert scrubbed["query"]["hybrid"]["queries"][1]["bool"]["must"][0]["match"]["title"] == "x"

    def test_only_scrubs_float_vectors_not_arbitrary_lists(self):
        body = {"fields": ["title", "chunk_text"], "vector": [0.1, 0.2]}
        scrubbed = _scrub_body_for_display(body)
        assert scrubbed["fields"] == ["title", "chunk_text"]
        assert scrubbed["vector"] == "<EMBEDDING_OMITTED_2_DIMS>"


# ---------------------------------------------------------------------------
# TestCaptureBody
# ---------------------------------------------------------------------------


class TestCaptureBody:
    """Verify that the optional `capture_body` sink is filled with the actual
    DSL sent to OpenSearch, with embedding vectors scrubbed."""

    def test_text_search_captures_body(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = {"hits": {"hits": []}}

        capture: dict = {}
        store._text_search("shoes", k=4, capture_body=capture)

        assert capture, "capture dict should be filled"
        body = capture["body"]
        assert body["size"] == 4
        assert "query" in body
        assert capture["index"] == "test_index"

    def test_bm25_only_search_captures_body(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = {"hits": {"hits": []}}

        capture: dict = {}
        store.bm25_only_search("blue widgets", k=10, capture_body=capture)

        body = capture["body"]
        # Pure BM25 has no embedding — body should echo the multi_match clause.
        must = body["query"]["bool"]["must"]
        assert any("multi_match" in clause for clause in must)

    def test_hybrid_native_captures_body_with_scrubbed_vector(self):
        store, mock_client = _make_store()
        store.search_pipeline = "hybrid_search_pipeline"
        store._hybrid_supported = True
        mock_client.search.return_value = {"hits": {"hits": []}}

        capture: dict = {}
        store._hybrid_search_native(
            "wireless headphones",
            query_embedding=[0.42] * 768,
            k=4,
            fetch_k=20,
            alpha=0.5,
            capture_body=capture,
        )

        body = capture["body"]
        # The full body is captured but the 768-dim vector is replaced.
        knn_clause = body["query"]["hybrid"]["queries"][0]["knn"]
        assert knn_clause["embedding"]["vector"] == "<EMBEDDING_OMITTED_768_DIMS>"
        assert capture["params"]["search_pipeline"] == "hybrid_search_pipeline"
        assert capture["index"] == "test_index"

    def test_capture_body_is_pure_dsl(self):
        """The body field must contain ONLY valid OpenSearch DSL — no internal
        sentinels — so users can paste it into Dashboards Dev Tools."""
        store, mock_client = _make_store()
        mock_client.search.return_value = {"hits": {"hits": []}}

        capture: dict = {}
        store._text_search("query", k=4, capture_body=capture)

        body = capture["body"]
        # No keys starting with `__` (those would be internal capture metadata).
        assert not any(k.startswith("__") for k in body.keys())

    def test_capture_body_optional_no_op_when_none(self):
        store, mock_client = _make_store()
        mock_client.search.return_value = {"hits": {"hits": []}}
        # Should not raise when capture_body is None (default path).
        store._text_search("query", k=4)
