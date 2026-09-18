"""OpenSearch-backed attribute mapping store.

Centralized, mutable source of truth for attribute variant→canonical mappings.
Replaces bundled JSON files (color_mappings.json); allows agent-driven taxonomy growth.
"""

import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

from retrieval.vector_store import get_shared_opensearch_client

INDEX_NAME = "agentic_hybrid_search_attribute_mappings"

# In-process cache for get_lookup_table, keyed on (INDEX_NAME, attribute_type)
# at call time -- not just attribute_type -- so tests that monkeypatch the
# module-level INDEX_NAME to a throwaway index (see
# tests/integration/test_attribute_mapping_store.py) get structurally
# isolated cache entries instead of relying on remembering to clear the
# cache. TTL is short-lived defense-in-depth for multi-instance staleness;
# the real correctness guarantee is write-through invalidation in
# add_mapping below, which is what the live enrichment flywheel's
# read-your-write requirement actually depends on (see #25, #26).
_LOOKUP_CACHE_TTL_SECONDS = 30
_lookup_cache_lock = threading.Lock()
_lookup_cache: Dict[Tuple[str, str], Tuple[Dict[str, str], float]] = {}


def _clear_lookup_cache() -> None:
    """Test hook: drop every cached lookup table immediately."""
    with _lookup_cache_lock:
        _lookup_cache.clear()


# Mapping document schema (for setup/reset only)
INDEX_MAPPING = {
    "mappings": {
        "properties": {
            "attribute_type": {"type": "keyword"},
            "variant": {"type": "keyword"},
            "canonical": {"type": "keyword"},
            "source": {"type": "keyword"},  # "seed", "migrated", "agent"
            "added_at": {"type": "date"},
        }
    }
}


class AttributeMappingStore:
    """Client for attribute variant→canonical mappings stored in OpenSearch."""

    def __init__(self, client: Optional[OpenSearch] = None):
        """Initialize the store.

        Args:
            client: OpenSearch client. If None, uses the shared process-wide
                client (see vector_store.get_shared_opensearch_client). This
                used to build its own client from raw os.getenv() calls with
                defaults that silently diverged from config.py's on 4 of 6
                settings (host, SSL, cert verification, password) -- see #25.
        """
        self.client = client or get_shared_opensearch_client()

    def ensure_index_exists(self) -> None:
        """Create the mapping index if it doesn't exist."""
        if not self.client.indices.exists(index=INDEX_NAME):
            self.client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)

    def get_lookup_table(self, attribute_type: str) -> Dict[str, str]:
        """Get all variant→canonical mappings for an attribute type.

        Cached for _LOOKUP_CACHE_TTL_SECONDS (see module docstring) --
        previously every call (including _classify_attribute's query-time
        read path, hit once for color and once for waterproof on every
        attribute_filter/refinement query, doubling on a quality-gate
        retry) ran a fresh, unfiltered 10k-doc scan. add_mapping()
        invalidates this entry synchronously on write, so the live
        enrichment flywheel still gets read-your-write consistency within
        this process (see #25, #26).

        Args:
            attribute_type: e.g. "color", "waterproof"

        Returns:
            Dict mapping variant (lowercase) to canonical value
        """
        cache_key = (INDEX_NAME, attribute_type)
        with _lookup_cache_lock:
            cached = _lookup_cache.get(cache_key)
            if cached is not None and cached[1] > time.monotonic():
                return cached[0]

        try:
            response = self.client.search(
                index=INDEX_NAME,
                body={
                    "query": {"term": {"attribute_type": attribute_type}},
                    "size": 10000,
                    "_source": ["variant", "canonical"],
                },
            )
        except NotFoundError:
            lookup: Dict[str, str] = {}
        else:
            lookup = {}
            for hit in response["hits"]["hits"]:
                doc = hit["_source"]
                lookup[doc["variant"].lower()] = doc["canonical"]

        with _lookup_cache_lock:
            _lookup_cache[cache_key] = (lookup, time.monotonic() + _LOOKUP_CACHE_TTL_SECONDS)
        return lookup

    def get_all_attribute_types(self) -> List[str]:
        """List every distinct attribute_type registered in the store.

        Used by config_generator.py to discover which text-detected
        attribute types (waterproof, and any future ones) need a Lucille
        stage generated for the next full reindex — including types the
        live agent has registered that no static config ever mentioned.

        Returns:
            Sorted list of attribute_type values, e.g. ["color", "waterproof"]
        """
        try:
            response = self.client.search(
                index=INDEX_NAME,
                body={
                    "size": 0,
                    "aggs": {"types": {"terms": {"field": "attribute_type", "size": 1000}}},
                },
            )
        except NotFoundError:
            return []

        buckets = response.get("aggregations", {}).get("types", {}).get("buckets", [])
        return sorted(bucket["key"] for bucket in buckets)

    def add_mapping(
        self,
        attribute_type: str,
        variant: str,
        canonical: str,
        source: str = "agent",
        refresh: bool = True,
    ) -> bool:
        """Add or update a variant→canonical mapping.

        Args:
            attribute_type: e.g. "color", "waterproof"
            variant: the variant term (e.g. "vegan leather")
            canonical: the canonical value it maps to (e.g. "leather")
            source: origin of the mapping ("seed", "migrated", "agent")
            refresh: force the write to be immediately searchable. Keep True
                for single/live-agent writes (the flywheel needs read-your-
                write consistency); bulk callers pass False per-call and
                refresh once at the end for efficiency.

        Returns:
            True if newly added, False if already existed with same canonical
        """
        self.ensure_index_exists()

        doc_id = f"{attribute_type}#{variant.lower()}"

        # Idempotency: fetch by deterministic id rather than searching, so
        # bulk callers (refresh=False) see their own just-written docs too.
        try:
            existing_doc = self.client.get(index=INDEX_NAME, id=doc_id)["_source"]
            if existing_doc["canonical"] == canonical:
                return False
            is_new = False
        except NotFoundError:
            is_new = True

        self.client.index(
            index=INDEX_NAME,
            id=doc_id,
            body={
                "attribute_type": attribute_type,
                "variant": variant.lower(),
                "canonical": canonical,
                "source": source,
                "added_at": datetime.utcnow().isoformat(),
            },
            refresh=refresh,
        )

        # Invalidate the cached lookup table for this attribute type so the
        # next get_lookup_table() call sees this write immediately, not
        # after the TTL expires. This is the correctness guarantee the live
        # enrichment flywheel's read-your-write requirement depends on
        # (see #25's caching change, and #26's "corrected_from" flow).
        with _lookup_cache_lock:
            _lookup_cache.pop((INDEX_NAME, attribute_type), None)

        return is_new

    def get_mapping(self, attribute_type: str, variant: str) -> Optional[str]:
        """Look up a single variant's canonical value.

        Args:
            attribute_type: e.g. "color", "waterproof"
            variant: the variant term

        Returns:
            Canonical value if found, None otherwise
        """
        lookup = self.get_lookup_table(attribute_type)
        return lookup.get(variant.lower())

    def migrate_from_dict(self, attribute_type: str, mapping_dict: Dict[str, list]) -> int:
        """Bulk-migrate mappings from a dict (e.g., color_mappings.json's base_colors).

        Args:
            attribute_type: e.g. "color"
            mapping_dict: dict with canonical keys and variant list values
                         e.g. {"black": ["black", "jet", "charcoal"], "white": [...]}

        Returns:
            Count of new mappings added
        """
        self.ensure_index_exists()
        count = 0

        for canonical, variants in mapping_dict.items():
            for variant in variants:
                if self.add_mapping(
                    attribute_type, variant, canonical, source="migrated", refresh=False
                ):
                    count += 1

        self.client.indices.refresh(index=INDEX_NAME)
        return count

    def seed_from_discovery(self, attribute_type: str, discovered_mappings: Dict[str, str]) -> int:
        """Bulk-add discovered mappings (e.g., from attribute_discovery.bulk_discover).

        Args:
            attribute_type: e.g. "waterproof"
            discovered_mappings: dict mapping variant → canonical

        Returns:
            Count of new mappings added
        """
        self.ensure_index_exists()
        count = 0

        for variant, canonical in discovered_mappings.items():
            if self.add_mapping(attribute_type, variant, canonical, source="seed", refresh=False):
                count += 1

        self.client.indices.refresh(index=INDEX_NAME)
        return count
