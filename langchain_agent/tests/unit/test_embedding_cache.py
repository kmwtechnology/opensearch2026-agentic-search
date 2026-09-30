"""
Unit tests for EmbeddingCache — thread-safe LRU cache for query embeddings.
"""

import threading

from observability.embedding_cache import EmbeddingCache

EMBEDDING = [0.1] * 768


class TestEmbeddingCacheBasics:
    def test_cold_cache_returns_none(self):
        cache = EmbeddingCache()
        assert cache.get("headphones") is None

    def test_set_then_get_returns_embedding(self):
        cache = EmbeddingCache()
        cache.set("headphones", EMBEDDING)
        result = cache.get("headphones")
        assert result == EMBEDDING

    def test_normalization_uppercase_same_key(self):
        cache = EmbeddingCache()
        cache.set("Headphones", EMBEDDING)
        assert cache.get("headphones") == EMBEDDING
        assert cache.get("HEADPHONES") == EMBEDDING

    def test_normalization_whitespace_same_key(self):
        cache = EmbeddingCache()
        cache.set("  headphones  ", EMBEDDING)
        assert cache.get("headphones") == EMBEDDING

    def test_different_queries_are_distinct(self):
        cache = EmbeddingCache()
        emb_a = [0.1] * 768
        emb_b = [0.9] * 768
        cache.set("headphones", emb_a)
        cache.set("laptop", emb_b)
        assert cache.get("headphones") == emb_a
        assert cache.get("laptop") == emb_b


class TestEmbeddingCacheLRUEviction:
    def test_lru_eviction_removes_oldest_on_overflow(self):
        cache = EmbeddingCache(max_size=3)
        cache.set("a", [0.1] * 768)
        cache.set("b", [0.2] * 768)
        cache.set("c", [0.3] * 768)
        # Fill up — add one more to evict oldest ("a")
        cache.set("d", [0.4] * 768)
        assert cache.get("a") is None
        assert cache.get("b") is not None
        assert cache.get("d") is not None

    def test_overwrite_existing_key_no_eviction(self):
        cache = EmbeddingCache(max_size=2)
        cache.set("a", [0.1] * 768)
        cache.set("b", [0.2] * 768)
        # Update existing key — should not evict anything
        updated = [0.9] * 768
        cache.set("a", updated)
        assert cache.get("a") == updated
        assert cache.get("b") is not None


class TestEmbeddingCacheDisabled:
    def test_disabled_get_always_returns_none(self):
        cache = EmbeddingCache(enabled=False)
        cache.set("headphones", EMBEDDING)  # Should be a no-op
        assert cache.get("headphones") is None

    def test_disabled_set_is_noop(self):
        cache = EmbeddingCache(enabled=False)
        cache.set("headphones", EMBEDDING)
        assert cache._cache == {}
