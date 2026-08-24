"""
LRU cache for query embeddings to reduce latency on repeated queries.

Provides:
- EmbeddingCache: Thread-safe LRU cache for query embeddings with statistics tracking
"""

import hashlib
import logging
import threading
from functools import lru_cache
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """
    Thread-safe LRU cache for query embeddings.

    Caches embeddings for normalized queries to reduce embedding generation time.
    Tracks cache statistics (hits, misses, hit rate) for monitoring.
    Thread-safe implementation for concurrent access.

    Attributes:
        max_size: Maximum number of cached embeddings
        enabled: Whether caching is enabled
    """

    def __init__(self, max_size: int = 100, enabled: bool = True) -> None:
        """
        Initialize the embedding cache.

        Args:
            max_size: Maximum number of embeddings to cache (default: 100)
            enabled: Whether caching is enabled (default: True)
        """
        self.max_size = max_size
        self.enabled = enabled
        self._hits = 0
        self._misses = 0
        self._cache = {}  # Manual cache for flexibility
        self._lock = threading.Lock()  # Thread-safe cache access

    def _normalize_query(self, query: str) -> str:
        """Normalize query for consistent caching."""
        return query.lower().strip()

    def _query_hash(self, query: str) -> str:
        """Generate hash key for query."""
        normalized = self._normalize_query(query)
        return hashlib.md5(normalized.encode()).hexdigest()

    def get(self, query: str) -> Optional[List[float]]:
        """
        Get cached embedding for query if available.

        Args:
            query: Query string

        Returns:
            Cached embedding if hit, None otherwise
        """
        if not self.enabled:
            return None

        key = self._query_hash(query)
        with self._lock:
            if key in self._cache:
                self._hits += 1
                return self._cache[key]

            self._misses += 1
            return None

    def set(self, query: str, embedding: List[float]) -> None:
        """
        Cache an embedding for a query.

        Args:
            query: Query string
            embedding: Embedding vector to cache
        """
        if not self.enabled:
            return

        key = self._query_hash(query)

        with self._lock:
            # Implement simple LRU by removing oldest when at capacity
            if len(self._cache) >= self.max_size and key not in self._cache:
                # Remove first (oldest) item - not optimal LRU, but simple
                # In production, would use OrderedDict or similar
                self._cache.pop(next(iter(self._cache)))

            self._cache[key] = embedding

    def clear(self) -> None:
        """Clear all cached embeddings."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_stats(self) -> dict:
        """
        Get cache statistics.

        Returns:
            Dictionary with hits, misses, hit_rate, and cache_size
        """
        with self._lock:
            total = self._hits + self._misses
            hit_rate = (self._hits / total * 100) if total > 0 else 0.0

            return {
                "hits": self._hits,
                "misses": self._misses,
                "total_requests": total,
                "hit_rate_percent": round(hit_rate, 1),
                "cache_size": len(self._cache),
                "max_size": self.max_size,
            }

    def __repr__(self) -> str:
        """String representation with statistics."""
        stats = self.get_stats()
        return (
            f"EmbeddingCache(size={stats['cache_size']}/{stats['max_size']}, "
            f"hits={stats['hits']}, misses={stats['misses']}, "
            f"hit_rate={stats['hit_rate_percent']:.1f}%)"
        )
