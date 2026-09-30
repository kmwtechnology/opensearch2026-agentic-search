"""Bounded cache for query embeddings, so a repeated query skips the Ollama call."""

import hashlib
import logging
import threading
from typing import List, Optional

logger = logging.getLogger(__name__)


class EmbeddingCache:
    """Thread-safe cache of embeddings keyed by the normalized query; evicts the oldest
    entry (insertion order) once `max_size` is reached."""

    def __init__(self, max_size: int = 100, enabled: bool = True) -> None:
        """
        Initialize the embedding cache.

        Args:
            max_size: Maximum number of embeddings to cache (default: 100)
            enabled: Whether caching is enabled (default: True)
        """
        self.max_size = max_size
        self.enabled = enabled
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
            return self._cache.get(key)

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
            if len(self._cache) >= self.max_size and key not in self._cache:
                self._cache.pop(next(iter(self._cache)))  # oldest insertion

            self._cache[key] = embedding
