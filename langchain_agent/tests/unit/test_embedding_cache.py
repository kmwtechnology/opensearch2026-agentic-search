"""
Unit tests for EmbeddingCache — thread-safe LRU cache for query embeddings.
"""

import threading

import pytest

from embedding_cache import EmbeddingCache

EMBEDDING = [0.1] * 768


@pytest.mark.unit
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


@pytest.mark.unit
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


@pytest.mark.unit
class TestEmbeddingCacheDisabled:
    def test_disabled_get_always_returns_none(self):
        cache = EmbeddingCache(enabled=False)
        cache.set("headphones", EMBEDDING)  # Should be a no-op
        assert cache.get("headphones") is None

    def test_disabled_set_is_noop(self):
        cache = EmbeddingCache(enabled=False)
        cache.set("headphones", EMBEDDING)
        stats = cache.get_stats()
        assert stats["cache_size"] == 0


@pytest.mark.unit
class TestEmbeddingCacheClear:
    def test_clear_removes_all_entries(self):
        cache = EmbeddingCache()
        cache.set("headphones", EMBEDDING)
        cache.set("laptop", EMBEDDING)
        cache.clear()
        assert cache.get("headphones") is None
        assert cache.get_stats()["cache_size"] == 0

    def test_clear_resets_stats(self):
        cache = EmbeddingCache()
        cache.set("headphones", EMBEDDING)
        cache.get("headphones")  # hit
        cache.get("missing")  # miss
        cache.clear()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0


@pytest.mark.unit
class TestEmbeddingCacheStats:
    def test_stats_track_hits_and_misses(self):
        cache = EmbeddingCache()
        cache.set("headphones", EMBEDDING)
        cache.get("headphones")  # hit
        cache.get("headphones")  # hit
        cache.get("missing")  # miss
        stats = cache.get_stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 1
        assert stats["total_requests"] == 3
        assert stats["hit_rate_percent"] == pytest.approx(66.7, abs=0.1)

    def test_stats_zero_on_empty_cache(self):
        cache = EmbeddingCache()
        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["hit_rate_percent"] == 0.0


@pytest.mark.unit
class TestEmbeddingCacheThreadSafety:
    def test_concurrent_set_get_no_corruption(self):
        cache = EmbeddingCache(max_size=50)
        errors = []

        def worker(i):
            try:
                key = f"query_{i % 10}"
                emb = [float(i)] * 10
                cache.set(key, emb)
                cache.get(key)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert errors == [], f"Thread safety errors: {errors}"
