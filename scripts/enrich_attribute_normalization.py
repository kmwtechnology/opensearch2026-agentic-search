#!/usr/bin/env python3
"""
Post-ingest enrichment: add normalized color and brand fields to indexed products.

Run after `lucille_ingest.sh` completes.

Usage:
    PYTHONPATH=langchain_agent python scripts/enrich_attribute_normalization.py

Adds these fields to each document in OpenSearch:
    - product_color_primary (normalized primary color for filtering)
    - product_color_secondary (normalized secondary color if present)
    - product_brand_normalized (normalized brand for filtering)
"""

import logging
import os
import sys

from opensearchpy import OpenSearch
from opensearchpy.helpers import bulk

# Add langchain_agent to path so we can import attribute_normalizer
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "langchain_agent"))

from attribute_normalizer import AttributeNormalizer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_opensearch_client() -> OpenSearch:
    """Create OpenSearch client from environment."""
    host = os.getenv("OPENSEARCH_HOST", "localhost")
    port = int(os.getenv("OPENSEARCH_PORT", 9200))
    use_ssl = os.getenv("OPENSEARCH_USE_SSL", "false").lower() == "true"
    verify_certs = os.getenv("OPENSEARCH_VERIFY_CERTS", "false").lower() == "true"
    user = os.getenv("OPENSEARCH_USER", "")
    password = os.getenv("OPENSEARCH_PASSWORD", "")

    auth = (user, password) if user and password else None

    client = OpenSearch(
        hosts=[{"host": host, "port": port}],
        http_auth=auth,
        use_ssl=use_ssl,
        verify_certs=verify_certs,
        ssl_show_warn=False,
    )
    return client


def enrich_documents(index_name: str = "agentic_hybrid_search_docs"):
    """Enrich indexed documents with normalized attributes."""
    logger.info(f"Starting attribute normalization enrichment for index: {index_name}")

    client = get_opensearch_client()
    normalizer = AttributeNormalizer()

    # Count total documents
    total_docs = client.count(index=index_name)["count"]
    logger.info(f"Total documents to enrich: {total_docs}")

    # Fetch and enrich documents using search with pagination
    batch_size = 250
    enriched_count = 0
    actions = []
    scroll_size = batch_size

    # Use search_after pagination
    search_after = None

    while True:
        # Query to get all documents
        search_body = {
            "size": scroll_size,
            "sort": [{"_id": "asc"}],
        }
        if search_after:
            search_body["search_after"] = search_after

        response = client.search(index=index_name, body=search_body)
        hits = response.get("hits", {}).get("hits", [])

        if not hits:
            break

        for hit in hits:
            doc_id = hit["_id"]
            source = hit["_source"]

            # Normalize colors
            product_color = source.get("product_color")
            color_primary, color_secondary = normalizer.normalize_color(product_color)

            # Normalize brand
            product_brand = source.get("product_brand")
            brand_normalized = normalizer.normalize_brand(product_brand)

            # Build update action
            update_doc = {
                "doc": {
                    "product_color_primary": color_primary,
                    "product_brand_normalized": brand_normalized,
                }
            }

            # Only add secondary if present
            if color_secondary:
                update_doc["doc"]["product_color_secondary"] = color_secondary

            actions.append(
                {
                    "_op_type": "update",
                    "_index": index_name,
                    "_id": doc_id,
                    "doc": update_doc["doc"],
                }
            )

            enriched_count += 1

            # Log progress
            if enriched_count % 1000 == 0:
                logger.info(f"Processed {enriched_count}/{total_docs} documents")

            # Send batch
            if len(actions) >= batch_size:
                success, failed = bulk(client, actions, raise_on_error=False)
                logger.info(f"Bulk update: {success} succeeded, {failed} failed")
                actions = []

        # Set search_after for next iteration
        if hits:
            last_hit = hits[-1]
            search_after = last_hit["sort"]

    # Send remaining
    if actions:
        success, failed = bulk(client, actions, raise_on_error=False)
        logger.info(f"Final batch: {success} succeeded, {failed} failed")

    logger.info(f"✓ Enrichment complete. {enriched_count} documents processed.")


if __name__ == "__main__":
    try:
        index_name = os.getenv("OPENSEARCH_INDEX_NAME", "agentic_hybrid_search_docs")
        enrich_documents(index_name)
    except Exception as e:
        logger.error(f"Enrichment failed: {e}", exc_info=True)
        sys.exit(1)
