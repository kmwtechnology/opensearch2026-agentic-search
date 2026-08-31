"""OpenSearch-backed attribute mapping store.

Centralized, mutable source of truth for attribute variant→canonical mappings.
Replaces bundled JSON files (color_mappings.json); allows agent-driven taxonomy growth.
"""

import os
from datetime import datetime
from typing import Dict, Optional

from opensearchpy import OpenSearch
from opensearchpy.exceptions import NotFoundError

INDEX_NAME = "agentic_hybrid_search_attribute_mappings"

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
            client: OpenSearch client. If None, creates one from env config.
        """
        self.client = client or self._create_client()

    @staticmethod
    def _create_client() -> OpenSearch:
        """Create OpenSearch client from environment."""
        host = os.getenv("OPENSEARCH_HOST", "localhost")
        port = int(os.getenv("OPENSEARCH_PORT", "9200"))
        use_ssl = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
        verify_certs = os.getenv("OPENSEARCH_VERIFY_CERTS", "true").lower() == "true"
        user = os.getenv("OPENSEARCH_USER", "admin")
        password = os.getenv("OPENSEARCH_PASSWORD", "admin")

        return OpenSearch(
            hosts=[{"host": host, "port": port}],
            http_auth=(user, password),
            use_ssl=use_ssl,
            verify_certs=verify_certs,
            ssl_show_warn=False,
        )

    def ensure_index_exists(self) -> None:
        """Create the mapping index if it doesn't exist."""
        if not self.client.indices.exists(index=INDEX_NAME):
            self.client.indices.create(index=INDEX_NAME, body=INDEX_MAPPING)

    def get_lookup_table(self, attribute_type: str) -> Dict[str, str]:
        """Get all variant→canonical mappings for an attribute type.

        Args:
            attribute_type: e.g. "color", "material"

        Returns:
            Dict mapping variant (lowercase) to canonical value
        """
        try:
            response = self.client.search(
                index=INDEX_NAME,
                body={
                    "query": {"term": {"attribute_type": attribute_type}},
                    "size": 10000,
                },
            )
        except NotFoundError:
            return {}

        lookup = {}
        for hit in response["hits"]["hits"]:
            doc = hit["_source"]
            lookup[doc["variant"].lower()] = doc["canonical"]

        return lookup

    def get_all_attribute_types(self) -> List[str]:
        """List every distinct attribute_type registered in the store.

        Used by config_generator.py to discover which text-detected
        attribute types (material, and any future ones) need a Lucille
        stage generated for the next full reindex — including types the
        live agent has registered that no static config ever mentioned.

        Returns:
            Sorted list of attribute_type values, e.g. ["color", "material"]
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
            attribute_type: e.g. "color", "material"
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

        return is_new

    def get_mapping(self, attribute_type: str, variant: str) -> Optional[str]:
        """Look up a single variant's canonical value.

        Args:
            attribute_type: e.g. "color", "material"
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
            attribute_type: e.g. "material"
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
