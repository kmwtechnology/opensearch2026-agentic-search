"""Re-arm the two self-consuming demos: taxonomy correction (color) and schema growth (waterproof).

Both destroy their own preconditions, quietly:

* **Correction**: the catalog mis-tags tan products as ``yellow``; succeeding rewrites the
  mapping to ``brown`` and re-tags the products. Run twice without a reset and turn 1 has
  nothing to dispute.
* **Growth**: the waterproof taxonomy starts with zero variants (WATERPROOF_CANONICALS);
  succeeding teaches it a mapping and tags products. Run twice and the gap is already filled.

reset_demo_taxonomy() restores both unconditionally; it is cheap and idempotent, so callers
need not know which demo is selected. Each reset is narrow: it only undoes its own demo's
state and is not a general taxonomy repair.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The mis-tagging the correction demo exists to catch and fix.
DEMO_ATTRIBUTE_TYPE = "color"
DEMO_VARIANT = "tan"
DEMO_BROKEN_CANONICAL = "yellow"

WATERPROOF_ATTRIBUTE_TYPE = "waterproof"
_WATERPROOF_FIELDS = (
    "product_waterproof",
    "product_waterproof_primary",
    "product_waterproof_secondary",
)


def reset_demo_taxonomy() -> Dict[str, Any]:
    """Put both demos back to their "before" state; returns a summary for the API response."""
    color = _reset_color_demo()
    waterproof = _reset_waterproof_demo()
    return {**color, "waterproof": waterproof}


def _reset_color_demo() -> Dict[str, Any]:
    from core.config import OPENSEARCH_INDEX_NAME
    from retrieval.attribute_mapping_store import AttributeMappingStore
    from retrieval.vector_store import get_shared_opensearch_client

    AttributeMappingStore().add_mapping(
        attribute_type=DEMO_ATTRIBUTE_TYPE,
        variant=DEMO_VARIANT,
        canonical=DEMO_BROKEN_CANONICAL,
        # The shipped state, so the row must not claim the agent learned it.
        source="seed",
    )
    logger.info("Demo reset: mapping restored to %s -> %s", DEMO_VARIANT, DEMO_BROKEN_CANONICAL)

    client = get_shared_opensearch_client()
    # Match the LISTED color, not the current indexed category: correct in whichever direction
    # the index currently is, and it cannot touch genuinely yellow or brown products.
    response = client.update_by_query(
        index=OPENSEARCH_INDEX_NAME,
        refresh=True,
        body={
            "query": {"match_phrase": {"product_color": DEMO_VARIANT}},
            "script": {
                "source": "ctx._source.product_color_primary = params.c",
                "params": {"c": DEMO_BROKEN_CANONICAL},
            },
        },
    )
    updated = response.get("updated", 0)
    logger.info("Demo reset: re-tagged %s tan-listed products", updated)

    return {
        "restored": {
            "attribute_type": DEMO_ATTRIBUTE_TYPE,
            "variant": DEMO_VARIANT,
            "canonical": DEMO_BROKEN_CANONICAL,
        },
        "products_retagged": updated,
    }


def _reset_waterproof_demo() -> Dict[str, Any]:
    """Delete the waterproof mapping rows the flywheel grew and strip the fields it tagged
    onto products, restoring a genuine gap. Both are scoped ``_by_query`` calls."""
    from core.config import OPENSEARCH_INDEX_NAME
    from retrieval.attribute_mapping_store import INDEX_NAME as MAPPING_INDEX_NAME
    from retrieval.attribute_mapping_store import AttributeMappingStore, _clear_lookup_cache
    from retrieval.vector_store import get_shared_opensearch_client

    store = AttributeMappingStore()
    store.ensure_index_exists()
    delete_response = store.client.delete_by_query(
        index=MAPPING_INDEX_NAME,
        refresh=True,
        body={"query": {"term": {"attribute_type": WATERPROOF_ATTRIBUTE_TYPE}}},
    )
    mappings_deleted = delete_response.get("deleted", 0)
    # delete_by_query bypasses add_mapping's cache invalidation.
    _clear_lookup_cache()

    client = get_shared_opensearch_client()
    update_response = client.update_by_query(
        index=OPENSEARCH_INDEX_NAME,
        refresh=True,
        body={
            "query": {"exists": {"field": "product_waterproof_primary"}},
            "script": {
                "source": " ".join(
                    f"if (ctx._source.containsKey('{field}')) {{ ctx._source.remove('{field}'); }}"
                    for field in _WATERPROOF_FIELDS
                ),
            },
        },
    )
    products_untagged = update_response.get("updated", 0)
    logger.info(
        "Demo reset: cleared %s waterproof mapping(s), untagged %s product(s)",
        mappings_deleted,
        products_untagged,
    )

    return {
        "mappings_deleted": mappings_deleted,
        "products_untagged": products_untagged,
    }
