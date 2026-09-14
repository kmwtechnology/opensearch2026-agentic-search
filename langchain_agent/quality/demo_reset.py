"""
Re-arm the taxonomy self-correction demo (#103).

The demo destroys its own preconditions. It works because the catalog mis-tags
tan products as ``yellow``; succeeding rewrites the mapping to ``brown`` and
re-indexes every product to match. Run it twice without resetting and turn 1
looks perfectly normal — nothing to notice, nothing to dispute, nothing to
correct. It does not error. It just stops demonstrating anything.

Two ways back, and the difference matters when a presenter is clicking about
between rehearsals:

* **fast** (default) — flip the mapping row and re-tag only the handful of
  products whose listed color is "tan", with one ``_update_by_query``.
  Milliseconds. This is a surgical undo of what the demo did, not a rebuild.
* **full** — flip the mapping row and re-run the real Lucille ingest over all
  9,618 products, exactly as the demo itself does. ~20s. Use it when the index
  may have drifted for reasons beyond this demo.

The fast path is deliberately narrow: it only knows how to undo THIS demo's
one mapping. It is not a general-purpose taxonomy repair, and it does not
pretend to be — anything broader belongs in a re-ingest.
"""

import logging
from typing import Any, Dict

logger = logging.getLogger(__name__)

# The mis-tagging the demo exists to catch and fix.
DEMO_ATTRIBUTE_TYPE = "color"
DEMO_VARIANT = "tan"
DEMO_BROKEN_CANONICAL = "yellow"


def reset_demo_taxonomy(full_reindex: bool = False) -> Dict[str, Any]:
    """
    Put the mapping and the products back to the demo's "before" state.

    Returns a summary describing what changed, suitable for an API response.
    """
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

        outcome = build_reindex_trigger().trigger()
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
