"""
OpenSearch-based vector store with hybrid search capabilities.

Provides:
- OpenSearchVectorStore: Main vector store with native hybrid search
- OpenSearchRetriever: LangChain-compatible retriever interface
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional, Union

import urllib3
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from opensearchpy import OpenSearch, RequestsHttpConnection

from core.config import (
    EMBEDDING_CACHE_MAX_SIZE,
    ENABLE_EMBEDDING_CACHE,
    OPENSEARCH_HOST,
    OPENSEARCH_INDEX_NAME,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_PORT,
    OPENSEARCH_SEARCH_PIPELINE,
    OPENSEARCH_TIMEOUT,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_USER,
    OPENSEARCH_VERIFY_CERTS,
    RETRIEVER_ALPHA,
    RETRIEVER_FETCH_K,
    RETRIEVER_K,
)
from core.exceptions import (
    EmbeddingError,
    SearchFailureError,
    SearchTimeoutError,
    SearchValidationError,
)
from observability.embedding_cache import EmbeddingCache

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def _scrub_body_for_display(body: Any) -> Any:
    """Walk an OpenSearch query body and replace embedding vectors with a placeholder.

    The 768-dim float vector is faithful but useless to a human reader and would
    bloat the WebSocket frame for the observability panel. Replace any list of
    floats found at a ``"vector"`` key with a sentinel string so the rest of
    the DSL stays copy-pasteable into OpenSearch's Dev Tools or any REST client.
    """
    if isinstance(body, dict):
        out: Dict[str, Any] = {}
        for k, v in body.items():
            if k == "vector" and isinstance(v, list) and v and isinstance(v[0], (int, float)):
                out[k] = f"<EMBEDDING_OMITTED_{len(v)}_DIMS>"
            else:
                out[k] = _scrub_body_for_display(v)
        return out
    if isinstance(body, list):
        return [_scrub_body_for_display(item) for item in body]
    return body


# OpenSearch index mapping definition
INDEX_MAPPING = {
    "settings": {
        "index": {
            "number_of_shards": 1,
            "number_of_replicas": 0,
            "knn": True,
            "knn.algo_param.ef_search": 100,
        },
        "analysis": {
            # Splits on every non-[A-Za-z0-9] character -- the same word
            # boundaries as Java 21's ASCII \b in AttributeDetectorStage. The
            # standard tokenizer keeps "Color:black" / "Brown.All" as ONE token
            # (Unicode MidLetter rules), so a phrase query on chunk_text misses
            # text the detector regex matches; chunk_text.words doesn't. Used
            # only to find scoped re-tag candidates (pipeline/scoped_retag.py).
            "tokenizer": {
                "ascii_word_tokenizer": {"type": "pattern", "pattern": "[^A-Za-z0-9]+"},
            },
            "filter": {
                "edge_ngram_filter": {
                    "type": "edge_ngram",
                    "min_gram": 2,
                    "max_gram": 20,
                },
                "shingle_filter": {
                    "type": "shingle",
                    "min_shingle_size": 2,
                    "max_shingle_size": 3,
                },
                "synonym_filter": {
                    "type": "synonym",
                    "synonyms": [
                        "headphones, earphones, earbuds, headset",
                        "laptop, notebook, chromebook",
                        "wireless, bluetooth",
                        "tv, television",
                        "phone, smartphone, mobile",
                        "smartwatch, smart watch",
                        "shoes, sneakers, trainers, footwear",
                        "charger, adapter, power adapter",
                        "monitor, display, screen",
                        "tablet, e-reader",
                        "camera, dslr, camcorder",
                        "speaker, speakers, soundbar",
                        "keyboard, mechanical keyboard",
                        "mouse, mice, trackpad",
                    ],
                },
            },
            "analyzer": {
                "light_english_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "synonym_filter", "stop", "kstem"],
                },
                "heavy_english_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "snowball"],
                },
                "english_shingle_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "stop", "shingle_filter"],
                },
                "autocomplete_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "edge_ngram_filter"],
                },
                "autocomplete_search_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase"],
                },
                "ascii_words_analyzer": {
                    "tokenizer": "ascii_word_tokenizer",
                    "filter": ["lowercase"],
                },
            },
        },
    },
    "mappings": {
        "properties": {
            "embedding": {
                "type": "knn_vector",
                "dimension": 768,
                "method": {
                    "name": "hnsw",
                    "space_type": "cosinesimil",
                    "engine": "lucene",
                    "parameters": {"ef_construction": 512, "m": 16},
                },
            },
            "chunk_text": {
                "type": "text",
                "analyzer": "light_english_analyzer",
                "fields": {
                    "heavy": {"type": "text", "analyzer": "heavy_english_analyzer"},
                    "words": {"type": "text", "analyzer": "ascii_words_analyzer"},
                },
            },
            "document_id": {"type": "keyword"},
            "chunk_index": {"type": "integer"},
            "collection_id": {"type": "keyword"},
            "source": {"type": "keyword"},
            "title": {
                "type": "text",
                "fields": {"keyword": {"type": "keyword"}},
            },
            "doc_type": {"type": "keyword"},
            "url": {"type": "keyword"},
            # Product fields, dual-mapped: text for BM25, keyword for filtering.
            "product_id": {"type": "keyword"},
            "product_brand": {
                "type": "text",
                "analyzer": "light_english_analyzer",
                "fields": {
                    "keyword": {"type": "keyword"},
                    "heavy": {"type": "text", "analyzer": "heavy_english_analyzer"},
                },
            },
            "product_color": {
                "type": "text",
                "analyzer": "light_english_analyzer",
                "fields": {
                    "keyword": {"type": "keyword"},
                    "heavy": {"type": "text", "analyzer": "heavy_english_analyzer"},
                },
            },
            "product_waterproof": {
                "type": "text",
                "analyzer": "light_english_analyzer",
                "fields": {
                    "keyword": {"type": "keyword"},
                    "heavy": {"type": "text", "analyzer": "heavy_english_analyzer"},
                },
            },
            # Attribute fields tagged when the corpus was built (preserved in the precomputed
            # dump; pipeline/scoped_retag.py handles live changes). Declared explicitly so a
            # fresh index maps them as keyword; product_color_primary and
            # product_brand_normalized arrive via dynamic mapping.
            "product_waterproof_primary": {"type": "keyword"},
            "product_waterproof_secondary": {"type": "keyword"},
            "product_locale": {"type": "keyword"},
            # SQID image URL: displayed, never searched, so kept out of the inverted index.
            "product_image_url": {"type": "keyword", "index": False},
            "esci_labels": {"type": "keyword"},
            "collection": {"type": "keyword"},
            # Unused since typeahead was removed; kept because the precomputed dump
            # carries them and the loader checks this mapping's hash.
            "title_suggest": {
                "type": "text",
                "analyzer": "autocomplete_analyzer",
                "search_analyzer": "autocomplete_search_analyzer",
            },
            "brand_suggest": {
                "type": "text",
                "analyzer": "autocomplete_analyzer",
                "search_analyzer": "autocomplete_search_analyzer",
            },
            # Boosts multi-word phrase matches in titles.
            "title_phrase": {
                "type": "text",
                "analyzer": "english_shingle_analyzer",
            },
        }
    },
}

# Search pipeline definition for hybrid search
SEARCH_PIPELINE = {
    "description": "Hybrid search with min-max normalization and weighted combination",
    "phase_results_processors": [
        {
            "normalization-processor": {
                "normalization": {"technique": "min_max"},
                "combination": {
                    "technique": "arithmetic_mean",
                    "parameters": {"weights": [0.5, 0.5]},
                },
            }
        }
    ],
}


def create_opensearch_client(
    host: str = OPENSEARCH_HOST,
    port: int = OPENSEARCH_PORT,
    user: str = OPENSEARCH_USER,
    password: str = OPENSEARCH_PASSWORD,
    use_ssl: bool = OPENSEARCH_USE_SSL,
    verify_certs: bool = OPENSEARCH_VERIFY_CERTS,
    timeout: int = OPENSEARCH_TIMEOUT,
) -> OpenSearch:
    """Create an OpenSearch client with connection resilience."""
    kwargs = {
        "hosts": [{"host": host, "port": port}],
        "use_ssl": use_ssl,
        "verify_certs": verify_certs,
        "ssl_show_warn": False,
        "connection_class": RequestsHttpConnection,
        "timeout": timeout,
        "retry_on_timeout": True,
        "max_retries": 3,
    }
    if user and password:
        kwargs["http_auth"] = (user, password)
    return OpenSearch(**kwargs)


_shared_client: Optional[OpenSearch] = None
_shared_client_lock = threading.Lock()


def get_shared_opensearch_client() -> OpenSearch:
    """Process-wide client for health, admin and attribute-mapping paths; it pools sockets,
    so this avoids a TCP(+TLS) handshake per call."""
    global _shared_client
    if _shared_client is None:
        with _shared_client_lock:
            if _shared_client is None:
                _shared_client = create_opensearch_client()
    return _shared_client


def reset_shared_opensearch_client() -> None:
    """Test hook: drop the cached client so the next call picks up a patched create_opensearch_client()."""
    global _shared_client
    with _shared_client_lock:
        _shared_client = None


class OpenSearchVectorStore:
    """kNN, BM25 and hybrid search over the products index.

    Hybrid uses OpenSearch's native `hybrid` query with the min-max normalization search
    pipeline (created by setup.py).
    """

    def __init__(
        self,
        embeddings: Embeddings,
        collection_id: str,
        client: Optional[OpenSearch] = None,
    ) -> None:
        if not collection_id:
            raise ValueError("collection_id must be a non-empty string")
        self.embeddings = embeddings
        self.collection_id = collection_id
        self.client = client or create_opensearch_client()
        self.index_name = OPENSEARCH_INDEX_NAME
        self.search_pipeline = OPENSEARCH_SEARCH_PIPELINE
        self._embedding_cache = EmbeddingCache(
            max_size=EMBEDDING_CACHE_MAX_SIZE,
            enabled=ENABLE_EMBEDDING_CACHE,
        )

    def _get_embedding(self, query: str) -> List[float]:
        """Query embedding, cached."""
        cached = self._embedding_cache.get(query)
        if cached is not None:
            return cached
        try:
            embedding = self.embeddings.embed_query(query)
        except Exception as e:
            raise EmbeddingError(f"Failed to generate embedding: {e}") from e
        self._embedding_cache.set(query, embedding)
        return embedding

    def as_retriever(
        self,
        search_kwargs: Optional[Dict[str, Any]] = None,
    ) -> "OpenSearchRetriever":
        """Return a retriever interface with optional attribute filters."""
        if search_kwargs is None:
            search_kwargs = {
                "k": RETRIEVER_K,
                "fetch_k": RETRIEVER_FETCH_K,
                "alpha": RETRIEVER_ALPHA,
            }

        return OpenSearchRetriever(
            self,
            k=search_kwargs.get("k", RETRIEVER_K),
            fetch_k=search_kwargs.get("fetch_k", RETRIEVER_FETCH_K),
            alpha=search_kwargs.get("alpha", RETRIEVER_ALPHA),
            filters=search_kwargs.get("filters"),
            capture_body=search_kwargs.get("capture_body"),
        )

    @staticmethod
    def _truncate_query_terms(query: str, max_terms: int = 40) -> str:
        """Cap a query at `max_terms` terms to stay under Lucene's 1024-clause limit."""
        terms = query.split()
        if len(terms) <= max_terms:
            return query
        truncated = " ".join(terms[:max_terms])
        logger.warning(
            f"Query truncated from {len(terms)} to {max_terms} terms: "
            f"{query[:80]}... → {truncated[:80]}..."
        )
        return truncated

    @staticmethod
    def _build_multi_match(query: str) -> Dict[str, Any]:
        """BM25 multi_match with per-field boosts, a title phrase field and bounded fuzziness.

        Primary fields use the kstem analyzer for precision; the `.heavy` (snowball)
        sub-fields add recall at ^0.3.
        """
        query = OpenSearchVectorStore._truncate_query_terms(query)

        fields = [
            "chunk_text",
            "title^3.0",
            "title_phrase^2.5",
            "product_brand^2.0",
            "product_color^1.5",
            "product_waterproof^2.0",
            "chunk_text.heavy^0.3",
            "product_brand.heavy^0.3",
            "product_color.heavy^0.3",
            "product_waterproof.heavy^0.3",
        ]
        return {
            "multi_match": {
                "query": query,
                "fields": fields,
                "type": "best_fields",
                "tie_breaker": 0.3,
                "fuzziness": "AUTO",
                # Unbounded AUTO fuzziness expands each term into up to 50 variants per
                # field, which blew the 1024-clause limit on ordinary 8-10 word queries.
                "prefix_length": 1,
                "max_expansions": 10,
            }
        }

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """Pure kNN search; returns [] on any error."""
        try:
            query_embedding = self._get_embedding(query)

            body = {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": k,
                                    }
                                }
                            }
                        ],
                        "filter": [{"term": {"collection_id": self.collection_id}}],
                    }
                },
            }

            response = self.client.search(index=self.index_name, body=body)
            return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.error(f"Error during similarity search: {e}")
            return []

    def hybrid_search(
        self,
        query: str,
        k: int = 4,
        fetch_k: int = 20,
        alpha: float = 0.5,
        filters: Optional[List[Dict[str, Any]]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Hybrid kNN + BM25 search. alpha 0.0 is pure BM25, 1.0 pure vector.

        `filters` are OpenSearch clauses, implicitly AND'd.
        """
        if k <= 0:
            raise SearchValidationError(f"k must be > 0, got {k}")
        if fetch_k < k:
            raise SearchValidationError(f"fetch_k ({fetch_k}) must be >= k ({k})")

        if alpha == 0.0:
            return self._text_search(query, k, filters, capture_body=capture_body)

        if alpha == 1.0:
            return self.similarity_search(query, k)

        if not 0.0 <= alpha <= 1.0:
            raise SearchValidationError(f"alpha must be in [0.0, 1.0], got {alpha}")

        try:
            query_embedding = self._get_embedding(query)

            return self._hybrid_search_native(
                query, query_embedding, k, fetch_k, alpha, filters, capture_body=capture_body
            )

        except EmbeddingError:
            raise
        except TimeoutError as e:
            raise SearchTimeoutError(f"Search timed out: {e} (operation=hybrid_search)") from e
        except Exception as e:
            raise SearchFailureError(f"Hybrid search failed: {e}") from e

    def _search(
        self,
        query: str,
        build_body: Callable[[str], Dict[str, Any]],
        params: Optional[Dict[str, Any]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Run the search built by `build_body(query)`.

        On a maxClauseCount error, retries once with the query cut to 20 terms. When
        `capture_body` is given it receives the first body (embedding scrubbed), the
        search params and the index name, for the observability panel.
        """
        body = build_body(query)
        if capture_body is not None:
            capture_body["body"] = _scrub_body_for_display(body)
            if params is not None:
                capture_body["params"] = dict(params)
            capture_body["index"] = self.index_name
        try:
            return self.client.search(index=self.index_name, body=body, params=params)
        except Exception as e:
            if "max_clause_count" not in str(e).lower():
                raise
            shorter = self._truncate_query_terms(query, max_terms=20)
            if shorter == query:
                raise
            logger.warning(f"maxClauseCount error, retrying with a shorter query: {e}")
            return self.client.search(
                index=self.index_name, body=build_body(shorter), params=params
            )

    def _hybrid_search_native(
        self,
        query: str,
        query_embedding: List[float],
        k: int,
        fetch_k: int,
        alpha: float,
        filters: Optional[List[Dict[str, Any]]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """OpenSearch `hybrid` query fused by the search pipeline."""
        filter_list = [{"term": {"collection_id": self.collection_id}}, *(filters or [])]
        knn_filter = {"bool": {"must": filter_list}} if len(filter_list) > 1 else filter_list[0]

        def build_body(q: str) -> Dict[str, Any]:
            return {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "hybrid": {
                        "queries": [
                            {
                                "knn": {
                                    "embedding": {
                                        "vector": query_embedding,
                                        "k": fetch_k,
                                        "filter": knn_filter,
                                    }
                                }
                            },
                            {
                                "bool": {
                                    "must": [self._build_multi_match(q)],
                                    "filter": filter_list,
                                }
                            },
                        ]
                    }
                },
            }

        response = self._search(
            query,
            build_body,
            params={"search_pipeline": self.search_pipeline},
            capture_body=capture_body,
        )
        return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]

    def _text_search(
        self,
        query: str,
        k: int = 4,
        filters: Optional[List[Dict[str, Any]]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Pure BM25 search (alpha=0.0); returns [] on any error."""
        filter_list = [{"term": {"collection_id": self.collection_id}}, *(filters or [])]

        def build_body(q: str) -> Dict[str, Any]:
            return {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [self._build_multi_match(q)],
                        "filter": filter_list,
                    }
                },
            }

        try:
            response = self._search(query, build_body, capture_body=capture_body)
            return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Error during text search: {e}")
            return []

    @staticmethod
    def _hit_to_document(hit: dict, retrieval_score: Optional[float] = None) -> Document:
        """Convert an OpenSearch hit to a Document; ``retrieval_score`` overrides ``hit["_score"]``."""
        src = hit["_source"]
        score = retrieval_score if retrieval_score is not None else hit.get("_score")
        # The dump stores the ASIN as the document _id and never writes it into _source
        # as product_id, so _id is the source of truth.
        product_id = hit.get("_id") or src.get("id") or src.get("product_id", "")
        metadata = {
            "source": src.get("source", ""),
            "title": src.get("title", ""),
            "doc_type": src.get("doc_type", ""),
            "url": src.get("url", ""),
            "collection_id": src.get("collection_id", ""),
            "product_id": product_id,
            "product_brand": src.get("product_brand", ""),
            "product_color": src.get("product_color", ""),
            "product_color_primary": src.get("product_color_primary", ""),
            "image_url": src.get("product_image_url", "") or "",
        }
        if score is not None:
            metadata["retrieval_score"] = float(score)
        return Document(page_content=src.get("chunk_text", ""), metadata=metadata)


class OpenSearchRetriever:
    """Hybrid retriever over OpenSearchVectorStore (kNN + BM25; alpha 0 is pure BM25, 1 pure
    vector).

    `fetch_k` is the per-method candidate pool, `k` the count returned; `filters` are
    OpenSearch clauses, AND'd. Chunks of one product collapse to the top-scoring one.
    """

    def __init__(
        self,
        vector_store: OpenSearchVectorStore,
        k: int = 4,
        fetch_k: int = 20,
        alpha: float = 0.5,
        filters: Optional[List[Dict[str, Any]]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.vector_store = vector_store
        self.k = k
        self.fetch_k = fetch_k
        self.alpha = alpha
        self.filters = filters
        # Filled in place by invoke() with the DSL body sent to OpenSearch.
        self.capture_body = capture_body

    @staticmethod
    def collapse_by_document(
        documents: List[Document],
        collapse_field: str = "product_id",
    ) -> List[Document]:
        """Keep the first (highest-ranked) document per `collapse_field` value; documents without one pass through."""
        seen_ids: set = set()
        collapsed: List[Document] = []
        for doc in documents:
            doc_id = doc.metadata.get(collapse_field)
            if not doc_id or doc_id not in seen_ids:
                if doc_id:
                    seen_ids.add(doc_id)
                collapsed.append(doc)
        return collapsed

    def invoke(
        self,
        input_dict: Union[Dict[str, Any], str],
    ) -> List[Document]:
        """Retrieve for a query string or a dict with an 'input' or 'query' key."""
        if isinstance(input_dict, dict):
            query = input_dict.get("input") or input_dict.get("query", "")
        else:
            query = str(input_dict)

        documents = self.vector_store.hybrid_search(
            query,
            k=self.k,
            fetch_k=self.fetch_k,
            alpha=self.alpha,
            filters=self.filters,
            capture_body=self.capture_body,
        )

        if self.vector_store.collection_id == "esci_products":
            documents = self.collapse_by_document(documents, "product_id")

        return documents
