"""
Re-arm the two self-consuming demos: taxonomy self-correction (#103) and
schema-evolution growth (issue #142).

Both demos destroy their own preconditions, in opposite ways:

* **Correction** (color): the catalog mis-tags tan products as ``yellow``;
  succeeding rewrites the mapping to ``brown`` and re-indexes every product
  to match. Run it twice without resetting and turn 1 looks perfectly
  normal — nothing to notice, nothing to dispute, nothing to correct.
* **Growth** (waterproof): the taxonomy starts with a genuine gap (zero
  seed variants — see attribute_discovery.py's WATERPROOF_CANONICALS);
  succeeding teaches it a real variant->canonical mapping and tags matching
  products. Run it twice without resetting and turn 1 finds the gap already
  filled — nothing missing to notice.

Neither failure errors. Both just quietly stop demonstrating anything, which
is the worst way to find out mid-talk. reset_demo_taxonomy() restores BOTH
to their "before" state unconditionally on every call — it's cheap and
idempotent, so there's no need for the caller to know which demo is
currently selected; see web/src/components/Layout.tsx's armCatalog.

Two ways back for the color demo, and the difference matters when a
presenter is clicking about between rehearsals:

* **fast** (default) — flip the mapping row and re-tag only the handful of
  products whose listed color is "tan", with one ``_update_by_query``.
  Milliseconds. This is a surgical undo of what the demo did, not a rebuild.
* **full** — flip the mapping row and re-run the real Lucille ingest over all
  9,618 products, exactly as the demo itself does. ~20s. Use it when the index
  may have drifted for reasons beyond this demo.

The waterproof demo only has a fast path: delete its mapping row(s) and
strip the field back off any products it tagged, both scoped ``_by_query``
operations. There's no "full" mode for it because, unlike color, there's no
correct steady-state mapping to restore — the taxonomy is supposed to be
empty until the live flywheel (re-)grows it.

Both fast paths are deliberately narrow: each only knows how to undo its own
demo's state. Neither is a general-purpose taxonomy repair, and neither
pretends to be — anything broader belongs in a re-ingest / re-seed.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The mis-tagging the correction demo exists to catch and fix.
DEMO_ATTRIBUTE_TYPE = "color"
DEMO_VARIANT = "tan"
DEMO_BROKEN_CANONICAL = "yellow"

# The attribute type the growth demo teaches the catalog from scratch.
WATERPROOF_ATTRIBUTE_TYPE = "waterproof"
_WATERPROOF_FIELDS = (
    "product_waterproof",
    "product_waterproof_primary",
    "product_waterproof_secondary",
)


def reset_demo_taxonomy(full_reindex: bool = False) -> Dict[str, Any]:
    """
    Put both self-consuming demos back to their "before" state.

    Returns a summary describing what changed, suitable for an API response.
    """
    color = _reset_color_demo(full_reindex=full_reindex)
    waterproof = _reset_waterproof_demo()
    return {**color, "waterproof": waterproof}


def _reset_color_demo(full_reindex: bool) -> Dict[str, Any]:
    from core.config import OPENSEARCH_INDEX_NAME
    from retrieval.attribute_mapping_store import AttributeMappingStore
    from retrieval.vector_store import get_shared_opensearch_client

    AttributeMappingStore().add_mapping(
        attribute_type=DEMO_ATTRIBUTE_TYPE,
        variant=DEMO_VARIANT,
        canonical=DEMO_BROKEN_CANONICAL,
        # Reset restores the SHIPPED state, so the row should not claim the
        # agent learned it — otherwise the next run's "corrected_from" story
        # is told against a mapping that looks agent-authored already.
        source="seed",
    )
    logger.info("Demo reset: mapping restored to %s -> %s", DEMO_VARIANT, DEMO_BROKEN_CANONICAL)

    if full_reindex:
        from pipeline.reindex_trigger import build_reindex_trigger

        # "Full" means a real re-detection of the demo's variant against the
        # restored mapping, not the fast path's surgical flip. A literal full
        # Lucille run re-embeds ~158K products (30+ min) -- see #147.
        outcome = build_reindex_trigger("scoped").trigger(DEMO_ATTRIBUTE_TYPE, [DEMO_VARIANT])
        logger.info(
            "Demo reset (full): reindex success=%s docs=%s", outcome.success, outcome.docs_processed
        )
        return {
            "mode": "full",
            "restored": {
                "attribute_type": DEMO_ATTRIBUTE_TYPE,
                "variant": DEMO_VARIANT,
                "canonical": DEMO_BROKEN_CANONICAL,
            },
            "reindex_success": outcome.success,
            "docs_processed": outcome.docs_processed,
            "duration_seconds": outcome.duration_seconds,
            "error": outcome.error,
        }

    client = get_shared_opensearch_client()
    # Re-tag only the products whose LISTED color is tan. Matching on the
    # listed value rather than on the current indexed category means this is
    # correct whichever direction the index is currently in, and it cannot
    # touch products that are genuinely yellow or genuinely brown.
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
    logger.info("Demo reset (fast): re-tagged %s tan-listed products", updated)

    return {
        "mode": "fast",
        "restored": {
            "attribute_type": DEMO_ATTRIBUTE_TYPE,
            "variant": DEMO_VARIANT,
            "canonical": DEMO_BROKEN_CANONICAL,
        },
        "products_retagged": updated,
        "reindex_success": True,
        "error": None,
    }


def _reset_waterproof_demo() -> Dict[str, Any]:
    """
    Delete any "waterproof" taxonomy rows the live flywheel has grown and
    strip the fields it tagged onto products — restores the schema-evolution
    demo's "before" state (a genuine gap), not a wrong-but-present mapping
    to revert like the color demo.

    Both operations are scoped ``_by_query`` calls (delete on the mapping
    store, update on the products index), not a full reindex — milliseconds,
    safe to call on every restart/demo-select regardless of which demo is
    currently selected.
    """
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
    # A raw delete_by_query bypasses add_mapping's own cache invalidation, so
    # the in-process lookup cache would otherwise keep serving the deleted
    # rows until its TTL expires.
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
