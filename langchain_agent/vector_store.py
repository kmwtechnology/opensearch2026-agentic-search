"""
OpenSearch-based vector store with hybrid search capabilities.

Provides:
- OpenSearchVectorStore: Main vector store with native hybrid search
- OpenSearchRetriever: LangChain-compatible retriever interface
"""

import logging
import time
from typing import Any, Dict, List, Optional, Union

import urllib3
from langchain_core.documents import Document
from langchain_google_genai import GoogleGenerativeAIEmbeddings
from opensearchpy import OpenSearch, RequestsHttpConnection

from config import (
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
from embedding_cache import EmbeddingCache
from exceptions import EmbeddingError, SearchFailureError, SearchTimeoutError, SearchValidationError

# Suppress InsecureRequestWarning for self-signed certs
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)


def _scrub_body_for_display(body: Any) -> Any:
    """Walk an OpenSearch query body and replace embedding vectors with a placeholder.

    The 768-dim float vector is faithful but useless to a human reader and would
    bloat the WebSocket frame for the observability panel. Replace any list of
    floats found at a ``"vector"`` key with a sentinel string so the rest of
    the DSL stays copy-pasteable into Dashboards Dev Tools.
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
                "phonetic_filter": {
                    "type": "phonetic",
                    "encoder": "double_metaphone",
                    "replace": False,
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
                "english_phonetic_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "phonetic_filter"],
                },
                "autocomplete_analyzer": {
                    "tokenizer": "standard",
                    "filter": ["lowercase", "edge_ngram_filter"],
                },
                "autocomplete_search_analyzer": {
                    "tokenizer": "standard",
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
                "fields": {"heavy": {"type": "text", "analyzer": "heavy_english_analyzer"}},
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
            # E-commerce product fields (dual-mapped: text for BM25 search + keyword for faceting/filtering)
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
            "product_locale": {"type": "keyword"},
            "esci_labels": {"type": "keyword"},
            "collection": {"type": "keyword"},
            # Autocomplete suggest fields
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
            # Phrase matching field (boosts multi-word phrase matches in titles)
            "title_phrase": {
                "type": "text",
                "analyzer": "english_shingle_analyzer",
            },
            # Phonetic matching fields (handles sound-alike typos in brand/title)
            "title_phonetic": {
                "type": "text",
                "analyzer": "english_phonetic_analyzer",
            },
            "brand_phonetic": {
                "type": "text",
                "analyzer": "english_phonetic_analyzer",
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


class OpenSearchVectorStore:
    """
    OpenSearch-based vector store for semantic and hybrid document search.

    Uses OpenSearch's native hybrid query with normalization-processor
    search pipeline for score fusion. Falls back to client-side RRF
    if the hybrid query type is not available.

    Attributes:
        embeddings: GoogleGenerativeAIEmbeddings instance for generating query embeddings
        collection_id: Collection ID for document filtering
        client: OpenSearch client instance
        index_name: Name of the OpenSearch index
        search_pipeline: Name of the search pipeline for hybrid search
    """

    def __init__(
        self,
        embeddings: GoogleGenerativeAIEmbeddings,
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
        self._hybrid_supported: Optional[bool] = None
        # Instance-level cache for embeddings
        self._embedding_cache = EmbeddingCache(
            max_size=EMBEDDING_CACHE_MAX_SIZE,
            enabled=ENABLE_EMBEDDING_CACHE,
        )

    def _check_hybrid_support(self) -> bool:
        """Check if OpenSearch supports native hybrid queries (2.10+ with neural-search)."""
        if self._hybrid_supported is not None:
            return self._hybrid_supported

        try:
            info = self.client.info()
            version = info["version"]["number"]
            major, minor = int(version.split(".")[0]), int(version.split(".")[1])
            if major < 2 or (major == 2 and minor < 10):
                self._hybrid_supported = False
                logger.warning(f"OpenSearch {version} does not support hybrid queries (need 2.10+)")
                return False

            plugins = self.client.cat.plugins(format="json")
            has_neural = any("neural" in p.get("component", "").lower() for p in plugins)
            self._hybrid_supported = has_neural
            if not has_neural:
                logger.warning("OpenSearch neural-search plugin not found, using fallback RRF")
            return has_neural
        except Exception as e:
            logger.warning(f"Could not check hybrid support: {e}, using fallback RRF")
            self._hybrid_supported = False
            return False

    def _get_embedding(self, query: str) -> List[float]:
        """Get embedding for query, using cache if available. Retries on 429 rate-limit errors."""
        cached = self._embedding_cache.get(query)
        if cached is not None:
            return cached

        max_retries = 3
        retry_delay = 1
        last_error = None

        for attempt in range(max_retries):
            try:
                embedding = self.embeddings.embed_query(query)
                self._embedding_cache.set(query, embedding)
                return embedding
            except Exception as e:
                last_error = e
                error_str = str(e)
                is_rate_limit = "429" in error_str or "RESOURCE_EXHAUSTED" in error_str

                if is_rate_limit and attempt < max_retries - 1:
                    logger.warning(
                        f"Embedding API rate limited (attempt {attempt + 1}/{max_retries}), "
                        f"retrying in {retry_delay}s"
                    )
                    time.sleep(retry_delay)
                    retry_delay *= 2
                    continue

                recoverable = is_rate_limit
                raise EmbeddingError(
                    f"Failed to generate embedding: {e}", recoverable=recoverable
                ) from e

        raise EmbeddingError(
            f"Failed to generate embedding after {max_retries} retries"
        ) from last_error

    def as_retriever(
        self,
        search_type: str = "similarity",
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
            search_type=search_type,
            k=search_kwargs.get("k", RETRIEVER_K),
            fetch_k=search_kwargs.get("fetch_k", RETRIEVER_FETCH_K),
            alpha=search_kwargs.get("alpha", RETRIEVER_ALPHA),
            filters=search_kwargs.get("filters"),
            optimizations=search_kwargs.get("optimizations"),
            capture_body=search_kwargs.get("capture_body"),
        )

    @staticmethod
    def _truncate_query_terms(query: str, max_terms: int = 40) -> str:
        """
        Truncate a query to a maximum number of terms.

        Prevents maxClauseCount errors (Lucene hard cap: 1024 clauses).
        A 40-term query × 8 fields (with .heavy sub-fields) = 320 clauses,
        well under the limit. Issue #85.

        Args:
            query: The query string to truncate
            max_terms: Maximum number of terms to keep (default: 40)

        Returns:
            Truncated query or original if already short enough
        """
        terms = query.split()
        if len(terms) <= max_terms:
            return query
        truncated = " ".join(terms[:max_terms])
        logger.warning(
            f"Query truncated from {len(terms)} to {max_terms} terms (issue #85): "
            f"{query[:80]}... → {truncated[:80]}..."
        )
        return truncated

    @staticmethod
    def _build_multi_match(
        query: str,
        optimizations: Optional[Dict[str, bool]] = None,
    ) -> Dict[str, Any]:
        """
        Build a multi_match clause that respects per-feature optimization toggles.

        Toggle semantics (all default True when key missing):
          - phonetic: include `title_phonetic`/`brand_phonetic` fields
          - phrase_boost: include `title_phrase` field
          - field_boost: keep per-field `^N` weights; when False, all fields equal
          - fuzzy: include `"fuzziness": "AUTO"` on the multi_match
          - synonyms: keep default (`light_english_analyzer` with kstem); when False, force the
            query through the `standard` analyzer to suppress query-time
            synonym expansion (index-time tokens are unaffected)

        Primary fields use `light_english_analyzer` (kstem) for precision. Sub-fields
        (e.g., `chunk_text.heavy`) use `heavy_english_analyzer` (snowball) at ^0.3
        for recall insurance, leveraging dense vectors for morphological coverage.
        """
        # Truncate query to prevent maxClauseCount errors (issue #85)
        query = OpenSearchVectorStore._truncate_query_terms(query)
        opts = optimizations or {}
        phonetic = opts.get("phonetic", True)
        phrase_boost = opts.get("phrase_boost", True)
        field_boost = opts.get("field_boost", True)
        fuzzy = opts.get("fuzzy", True)
        synonyms = opts.get("synonyms", True)

        # (field_name, default_boost) — boost is dropped when field_boost is off
        candidate_fields: List[tuple] = [
            ("chunk_text", 1.0),
            ("title", 3.0),
        ]
        if phrase_boost:
            candidate_fields.append(("title_phrase", 2.5))
        candidate_fields.extend(
            [
                ("product_brand", 2.0),
                ("product_color", 1.5),
            ]
        )
        if phonetic:
            candidate_fields.extend(
                [
                    ("title_phonetic", 1.5),
                    ("brand_phonetic", 1.5),
                ]
            )
        # Add .heavy sub-fields for recall insurance (snowball stemmer, low weight)
        candidate_fields.extend(
            [
                ("chunk_text.heavy", 0.3),
                ("product_brand.heavy", 0.3),
                ("product_color.heavy", 0.3),
            ]
        )

        if field_boost:
            fields = [
                f"{name}^{boost}" if boost != 1.0 else name for name, boost in candidate_fields
            ]
        else:
            fields = [name for name, _ in candidate_fields]

        clause: Dict[str, Any] = {
            "query": query,
            "fields": fields,
            "type": "best_fields",
            "tie_breaker": 0.3,
        }
        if fuzzy:
            clause["fuzziness"] = "AUTO"
        if not synonyms:
            # `standard` analyzer skips the synonym_filter applied by english_analyzer
            clause["analyzer"] = "standard"

        return {"multi_match": clause}

    def similarity_search(self, query: str, k: int = 4) -> List[Document]:
        """
        Pure knn vector search.

        Args:
            query: The search query string
            k: Number of similar documents to return

        Returns:
            List of k most similar LangChain Document objects with metadata
        """
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
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """
        Hybrid search combining vector similarity and full-text search.

        Uses OpenSearch's native hybrid query with normalization-processor
        search pipeline. Falls back to client-side RRF if not supported.

        Args:
            query: Search query string
            k: Number of final results to return
            fetch_k: Number of candidates to fetch from each method
            alpha: Weight for vector vs text (0.0=pure BM25, 1.0=pure vector)
            filters: Optional list of OpenSearch filter clauses for attribute filtering
                     (filters in a list are implicitly AND'd)

        Returns:
            List of Document objects ranked by combined score
        """
        if k <= 0:
            raise SearchValidationError(f"k must be > 0, got {k}")
        if fetch_k < k:
            raise SearchValidationError(f"fetch_k ({fetch_k}) must be >= k ({k})")

        # Honor the `hybrid` toggle: when off, fall through to pure BM25 lexical
        # search regardless of the alpha the query evaluator chose.
        opts = optimizations or {}
        if opts.get("hybrid", True) is False:
            return self._text_search(
                query, k, filters, optimizations=optimizations, capture_body=capture_body
            )

        if alpha == 0.0:
            return self._text_search(
                query, k, filters, optimizations=optimizations, capture_body=capture_body
            )

        if alpha == 1.0:
            return self.similarity_search(query, k)

        if not 0.0 <= alpha <= 1.0:
            raise SearchValidationError(f"alpha must be in [0.0, 1.0], got {alpha}")

        try:
            query_embedding = self._get_embedding(query)

            if self._check_hybrid_support():
                return self._hybrid_search_native(
                    query,
                    query_embedding,
                    k,
                    fetch_k,
                    alpha,
                    filters,
                    optimizations,
                    capture_body=capture_body,
                )
            else:
                return self._hybrid_search_rrf(
                    query,
                    query_embedding,
                    k,
                    fetch_k,
                    alpha,
                    filters,
                    optimizations,
                    capture_body=capture_body,
                )

        except EmbeddingError:
            raise
        except TimeoutError as e:
            raise SearchTimeoutError(f"Search timed out: {e}", operation="hybrid_search") from e
        except Exception as e:
            raise SearchFailureError(f"Hybrid search failed: {e}") from e

    def _hybrid_search_native(
        self,
        query: str,
        query_embedding: List[float],
        k: int,
        fetch_k: int,
        alpha: float,
        filters: Optional[List[Dict[str, Any]]] = None,
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Native OpenSearch hybrid search using search pipeline with optional attribute filters."""
        # Build filter lists - combine collection_id with attribute filters
        # Filters in an array are implicitly AND'd together
        knn_filter_list = [{"term": {"collection_id": self.collection_id}}]
        text_filter_list = [{"term": {"collection_id": self.collection_id}}]

        if filters:
            knn_filter_list.extend(filters)
            text_filter_list.extend(filters)

        body = {
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
                                    "filter": (
                                        {"bool": {"must": knn_filter_list}}
                                        if len(knn_filter_list) > 1
                                        else knn_filter_list[0]
                                    ),
                                }
                            }
                        },
                        {
                            "bool": {
                                "must": [self._build_multi_match(query, optimizations)],
                                "filter": text_filter_list,
                            }
                        },
                    ]
                }
            },
        }

        # Use search_pipeline parameter to apply normalization
        params = {"search_pipeline": self.search_pipeline}
        if capture_body is not None:
            capture_body["body"] = _scrub_body_for_display(body)
            capture_body["params"] = dict(params)
            capture_body["index"] = self.index_name
        try:
            response = self.client.search(index=self.index_name, body=body, params=params)
        except Exception as e:
            # Catch maxClauseCount errors and retry with aggressive truncation (issue #85)
            if "max_clause_count" in str(e).lower() and "already_retried" not in getattr(
                e, "_ahs_context", ""
            ):
                logger.warning(
                    f"maxClauseCount error on first attempt, retrying with aggressive truncation: {e}"
                )
                truncated_query = self._truncate_query_terms(query, max_terms=20)
                if truncated_query != query:
                    # Rebuild the DSL with the truncated query
                    body["query"]["hybrid"]["queries"][1]["bool"]["must"] = [
                        self._build_multi_match(truncated_query, optimizations)
                    ]
                    try:
                        response = self.client.search(
                            index=self.index_name, body=body, params=params
                        )
                    except Exception as retry_error:
                        # Mark it so we don't retry again
                        retry_error._ahs_context = "already_retried"
                        raise
                else:
                    raise
            else:
                raise
        return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]

    def _hybrid_search_rrf(
        self,
        query: str,
        query_embedding: List[float],
        k: int,
        fetch_k: int,
        alpha: float,
        filters: Optional[List[Dict[str, Any]]] = None,
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Client-side RRF fallback for older OpenSearch versions."""
        RRF_K = 60

        # Build filter lists
        filter_list = [{"term": {"collection_id": self.collection_id}}]
        if filters:
            filter_list.extend(filters)

        # Vector search
        vector_body = {
            "size": fetch_k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [{"knn": {"embedding": {"vector": query_embedding, "k": fetch_k}}}],
                    "filter": filter_list,
                }
            },
        }
        vector_response = self.client.search(index=self.index_name, body=vector_body)

        # Text search
        text_body = {
            "size": fetch_k,
            "_source": {"excludes": ["embedding"]},
            "query": {
                "bool": {
                    "must": [self._build_multi_match(query, optimizations)],
                    "filter": filter_list,
                }
            },
        }
        if capture_body is not None:
            capture_body["body"] = _scrub_body_for_display(
                {"_rrf_fallback": True, "vector_body": vector_body, "text_body": text_body}
            )
            capture_body["index"] = self.index_name
        try:
            text_response = self.client.search(index=self.index_name, body=text_body)
        except Exception as e:
            # Catch maxClauseCount errors and retry with aggressive truncation (issue #85)
            if "max_clause_count" in str(e).lower() and "already_retried" not in getattr(
                e, "_ahs_context", ""
            ):
                logger.warning(
                    f"maxClauseCount error on first attempt, retrying with aggressive truncation: {e}"
                )
                truncated_query = self._truncate_query_terms(query, max_terms=20)
                if truncated_query != query:
                    text_body["query"]["bool"]["must"] = [
                        self._build_multi_match(truncated_query, optimizations)
                    ]
                    try:
                        text_response = self.client.search(index=self.index_name, body=text_body)
                    except Exception as retry_error:
                        retry_error._ahs_context = "already_retried"
                        raise
                else:
                    raise
            else:
                raise

        # Build rank maps
        vector_ranks = {}
        for rank, hit in enumerate(vector_response["hits"]["hits"], 1):
            vector_ranks[hit["_id"]] = (rank, hit)

        text_ranks = {}
        for rank, hit in enumerate(text_response["hits"]["hits"], 1):
            text_ranks[hit["_id"]] = (rank, hit)

        # Compute RRF scores
        all_ids = set(vector_ranks.keys()) | set(text_ranks.keys())
        vector_weight = alpha
        text_weight = 1.0 - alpha

        scored = []
        for doc_id in all_ids:
            v_rank = vector_ranks[doc_id][0] if doc_id in vector_ranks else 999999
            t_rank = text_ranks[doc_id][0] if doc_id in text_ranks else 999999
            rrf_score = (vector_weight / (RRF_K + v_rank)) + (text_weight / (RRF_K + t_rank))
            hit = vector_ranks.get(doc_id, text_ranks.get(doc_id))[1]
            scored.append((rrf_score, hit))

        scored.sort(key=lambda x: x[0], reverse=True)
        # Use the fused RRF score as the retrieval_score so the UI shows the
        # actual rank-fusion value, not the raw kNN/BM25 score from one half.
        return [self._hit_to_document(hit, retrieval_score=score) for score, hit in scored[:k]]

    def _text_search(
        self,
        query: str,
        k: int = 4,
        filters: Optional[List[Dict[str, Any]]] = None,
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Pure BM25 text search for alpha=0.0."""
        try:
            filter_list = [{"term": {"collection_id": self.collection_id}}]
            if filters:
                filter_list.extend(filters)

            body = {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [self._build_multi_match(query, optimizations)],
                        "filter": filter_list,
                    }
                },
            }

            if capture_body is not None:
                capture_body["body"] = _scrub_body_for_display(body)
                capture_body["index"] = self.index_name

            try:
                response = self.client.search(index=self.index_name, body=body)
            except Exception as e:
                # Catch maxClauseCount errors and retry with aggressive truncation (issue #85)
                if "max_clause_count" in str(e).lower() and "already_retried" not in getattr(
                    e, "_ahs_context", ""
                ):
                    logger.warning(
                        f"maxClauseCount error on first attempt, retrying with aggressive truncation: {e}"
                    )
                    truncated_query = self._truncate_query_terms(query, max_terms=20)
                    if truncated_query != query:
                        body["query"]["bool"]["must"] = [
                            self._build_multi_match(truncated_query, optimizations)
                        ]
                        try:
                            response = self.client.search(index=self.index_name, body=body)
                        except Exception as retry_error:
                            retry_error._ahs_context = "already_retried"
                            raise
                    else:
                        raise
                else:
                    raise
            return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]

        except Exception as e:
            logger.error(f"Error during text search: {e}")
            return []

    def bm25_only_search(
        self,
        query: str,
        k: int = 20,
        filters: Optional[List[Dict[str, Any]]] = None,
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> List[Document]:
        """Public BM25-only search used as the baseline for relevancy metrics.

        Honors the same per-feature optimization toggles as hybrid so the
        comparison is apples-to-apples (e.g. fuzzy + synonyms still apply
        if they're on for the active hybrid query). The ``hybrid`` toggle
        itself is ignored — this method is the BM25 baseline.
        """
        return self._text_search(
            query,
            k=k,
            filters=filters,
            optimizations=optimizations,
            capture_body=capture_body,
        )

    def stock_bm25_search(
        self,
        query: str,
        k: int = 20,
        filters: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Document]:
        """Vanilla BM25 reference — ignores all optimization toggles.

        Standard analyzer (no stemming, no synonyms), multi_match against
        ``title`` + ``chunk_text`` only, no fuzziness, no phonetic fields,
        no phrase boost, no field boost. This is the fixed anchor row of
        the Pipeline Quality Summary card so users can see what their
        BM25 toggles actually buy them on top of vanilla.
        """
        try:
            filter_list = [{"term": {"collection_id": self.collection_id}}]
            if filters:
                filter_list.extend(filters)

            body = {
                "size": k,
                "_source": {"excludes": ["embedding"]},
                "query": {
                    "bool": {
                        "must": [
                            {
                                "multi_match": {
                                    "query": query,
                                    "fields": ["title", "chunk_text"],
                                    "type": "best_fields",
                                    "analyzer": "standard",
                                }
                            }
                        ],
                        "filter": filter_list,
                    }
                },
            }

            response = self.client.search(index=self.index_name, body=body)
            return [self._hit_to_document(hit) for hit in response["hits"]["hits"]]
        except Exception as e:
            logger.error(f"Error during stock BM25 search: {e}")
            return []

    def lookup_judgments(
        self,
        query: str,
        *,
        index_name: str = "esci_judgments",
        locale: str = "us",
    ) -> Optional[Dict[str, float]]:
        """Look up ESCI ground-truth judgments for ``query``.

        Returns ``{product_id: relevance_score}`` when a matching query
        exists in the judgments index, else ``None``. Matching is exact
        on the lowercased keyword so a missing match silently fails over
        to the self-referential confidence proxy in the UI.
        """
        if not query:
            return None
        try:
            response = self.client.search(
                index=index_name,
                body={
                    "size": 1,
                    "query": {
                        "bool": {
                            "must": [
                                {"term": {"query.keyword": query.strip().lower()}},
                                {"term": {"locale": locale}},
                            ]
                        }
                    },
                },
            )
        except Exception as exc:
            # Index may not exist yet (e.g. local dev without ingestion).
            # Treat as a fallback signal, not an error.
            logger.debug("Judgments lookup failed: %s", exc)
            return None

        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        source = hits[0].get("_source", {})
        return {
            entry["product_id"]: float(entry.get("relevance", 0.0))
            for entry in source.get("judgments", [])
            if entry.get("product_id")
        }

    @staticmethod
    def _hit_to_document(hit: dict, retrieval_score: Optional[float] = None) -> Document:
        """Convert an OpenSearch hit to a LangChain Document.

        ``retrieval_score`` overrides ``hit["_score"]`` and is used by the RRF
        fallback path to surface the fused rank score instead of the raw
        per-subquery BM25/kNN score.
        """
        src = hit["_source"]
        score = retrieval_score if retrieval_score is not None else hit.get("_score")
        metadata = {
            "source": src.get("source", ""),
            "title": src.get("title", ""),
            "doc_type": src.get("doc_type", ""),
            "url": src.get("url", ""),
            "collection_id": src.get("collection_id", ""),
            "product_id": src.get("product_id", ""),
            "product_brand": src.get("product_brand", ""),
            "product_color": src.get("product_color", ""),
        }
        if score is not None:
            metadata["retrieval_score"] = float(score)
        return Document(page_content=src.get("chunk_text", ""), metadata=metadata)


class OpenSearchRetriever:
    """
    LangChain-compatible retriever for hybrid vector/BM25 search in OpenSearch.

    Bridges OpenSearchVectorStore and LangGraph/LangChain's BaseRetriever interface.
    Supports pure vector similarity search or hybrid search combining vector + lexical
    (BM25) via Reciprocal Rank Fusion (RRF).

    ## Hybrid Search Strategy

    Hybrid mode (`search_type="hybrid"`) merges two ranking lists:
    1. **Vector Search**: kNN (HNSW) on 768-dim embeddings → scored by cosine similarity
    2. **Lexical Search**: BM25 on English analyzer tokenization → term frequency scoring

    **Reciprocal Rank Fusion (RRF)**:
    - Formula: `score = Σ 1/(rank + k)` where k=60 (RRF constant)
    - Normalizes ranks from both search methods and blends them
    - Robust to outliers; doesn't require probability calibration

    **Alpha Parameter** (0.0 to 1.0):
    - 0.0 = Pure lexical (BM25): exact term matching, no semantic understanding
    - 0.5 = Balanced: keyword + meaning
    - 1.0 = Pure semantic (vector): conceptual matching, ignores exact terms

    The `fetch_k` parameter is key: fetch more candidates before deduplication and
    reranking. `k` is the final count returned to the agent.

    ## Product Deduplication

    ESCI products (the default collection) may have multiple index chunks from a single
    product (if chunked). `collapse_by_document()` deduplicates to one result per product.
    This is automatically applied when `collection_id="esci_products"`.

    ## Parameters

    Args:
        vector_store: OpenSearchVectorStore instance to query
        search_type: "similarity" (kNN only) or "hybrid" (kNN + BM25 via RRF)
        k: Number of final documents to return after filtering/dedup/reranking
        fetch_k: Number of candidates to fetch before deduplication/reranking.
                 Should be >= k. Larger fetch_k = more thorough but slower.
        alpha: Hybrid search weighting (0.0–1.0). Controls semantic/lexical balance.
               Only used if search_type="hybrid".
        filters: Optional list of OpenSearch filter clauses (AND'd together).
                 Example: [{"match": {"product_brand": {"query": "Sony"}}}]

    ## Usage Example

        # Create retriever with hybrid search, alpha=0.35 (lexical-heavy)
        retriever = vector_store.as_retriever(
            search_type="hybrid",
            search_kwargs={
                "k": 10,
                "fetch_k": 40,
                "alpha": 0.35,
                "filters": [{"match": {"product_color": {"query": "blue"}}}]
            }
        )

        # Retrieve documents
        docs = retriever.invoke("wireless headphones")
        for doc in docs:
            print(f"{doc.metadata['title']}: {doc.page_content[:100]}")

    ## Extension Points

    **Modify the search algorithm**:
    - Subclass OpenSearchRetriever and override `invoke()` for custom fusion logic
    - Replace RRF with other rank fusion methods (Borda count, Condorcet fusion, etc.)

    **Add custom scoring**:
    - Extend `invoke()` to apply post-search rescoring (e.g., popularity boost, recency)
    - Modify `collapse_by_document()` to use custom aggregation (e.g., max score vs first chunk)

    **Use different vector DB**:
    - Replace OpenSearchVectorStore with Pinecone, Milvus, Weaviate, etc.
    - Implement same `similarity_search()` and `hybrid_search()` interface
    """

    def __init__(
        self,
        vector_store: OpenSearchVectorStore,
        search_type: str = "similarity",
        k: int = 4,
        fetch_k: int = 20,
        alpha: float = 0.5,
        filters: Optional[List[Dict[str, Any]]] = None,
        optimizations: Optional[Dict[str, bool]] = None,
        capture_body: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.vector_store = vector_store
        self.search_type = search_type
        self.k = k
        self.fetch_k = fetch_k
        self.alpha = alpha
        self.filters = filters
        self.optimizations = optimizations
        # Optional sink for the actual DSL body sent to OpenSearch — populated
        # in-place during ``invoke()`` so the observability layer can echo
        # the exact query the cluster saw (with embedding scrubbed).
        self.capture_body = capture_body

    @staticmethod
    def collapse_by_document(
        documents: List[Document],
        collapse_field: str = "product_id",
    ) -> List[Document]:
        """
        Collapse multiple chunks from the same document into one result.

        Keeps only the first (highest-scored) chunk per unique document.
        Applied to product collections where chunks are redundant fragments
        of the same product, not distinct perspectives.

        Args:
            documents: Retrieved documents (assumed ranked by relevance)
            collapse_field: Metadata field to deduplicate by

        Returns:
            Documents with at most one per unique collapse_field value
        """
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
        """
        Retrieve documents for a query.

        Args:
            input_dict: Either a dictionary with 'input' or 'query' key,
                       or a string query directly

        Returns:
            List of Document objects matching the query
        """
        if isinstance(input_dict, dict):
            query = input_dict.get("input") or input_dict.get("query", "")
        else:
            query = str(input_dict)

        if self.search_type == "hybrid":
            documents = self.vector_store.hybrid_search(
                query,
                k=self.k,
                fetch_k=self.fetch_k,
                alpha=self.alpha,
                filters=self.filters,
                optimizations=self.optimizations,
                capture_body=self.capture_body,
            )
        elif self.search_type == "similarity":
            documents = self.vector_store.similarity_search(query, k=self.k)
        else:
            raise ValueError(f"Unknown search_type: {self.search_type}")

        # Deduplicate product chunks — keep only the top-scoring chunk per product
        if self.vector_store.collection_id == "esci_products":
            documents = self.collapse_by_document(documents, "product_id")

        return documents
