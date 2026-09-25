"""
Attribute enrichment service — the mechanism the live agent enrichment tool
calls when a query mentions a color or waterproof term that isn't in its
taxonomy yet. Generic over attribute_type (color, waterproof, or any future
type), not waterproof-specific.

Flow (real, not mocked — measured ~17-20s locally, fast enough for a live
on-stage trigger):
  1. Classify the gap term against the attribute type's canonical buckets
     (attribute_discovery.single_term_classify, with an optional LLM
     fallback for terms that don't dictionary-match), or accept an
     explicit_canonical override.
  2. Write the new variant->canonical mapping to the OS-backed attribute
     mapping store (AttributeMappingStore.add_mapping).
  3. Ensure the OpenSearch index mapping has product_<attribute_type>
     (dual-mapped text) + product_<attribute_type>_primary/_secondary
     (keyword) fields — additive, only when the attribute type is new.
  4. Trigger a REAL full catalog reindex through reindex_trigger, which runs
     scripts/lucille_ingest.sh as a subprocess and waits (~20s).
     scripts/lucille_ingest.sh regenerates products.generated.conf
     (config_generator.py) itself as part of every ingest run -- this
     service never writes that file directly, since it lives alongside
     the Lucille ETL source.

This supersedes an earlier scoped update_by_query design — a real reindex
was measured fast enough (~17-20s) to run live, so there's no need for a
narrower, faster-but-less-authentic patch mechanism.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Dict, Optional

from pipeline.reindex_trigger import ReindexTrigger, build_reindex_trigger
from retrieval.attribute_discovery import (
    COLOR_CANONICALS,
    WATERPROOF_CANONICALS,
    single_term_classify,
)
from retrieval.attribute_mapping_store import AttributeMappingStore

logger = logging.getLogger(__name__)

# Canonical bucket vocabularies by attribute type. Add an entry here when a
# new attribute type gets a discovery seed dict in attribute_discovery.py.
_CANONICAL_SEEDS_BY_TYPE: Dict[str, Dict[str, list]] = {
    "color": COLOR_CANONICALS,
    "waterproof": WATERPROOF_CANONICALS,
}


@dataclass
class EnrichmentResult:
    """Result of an attribute enrichment attempt."""

    success: bool
    attribute_type: str
    variant: str
    canonical: Optional[str] = None
    reason: Optional[str] = None  # set when success=False
    reindex_triggered: bool = False
    reindex_success: bool = False
    docs_processed: int = 0  # products whose tags the reindex changed
    docs_scanned: int = 0  # scoped mode: products re-detected (text mentions the variant)
    duration_seconds: float = 0.0
    reindex_mode: str = "scoped"
    reindex_run_url: Optional[str] = None  # unused by the local trigger; kept for schema compat
    reindex_error: Optional[str] = None  # short detail when reindex_success is False
    # Set when this replaced an existing (wrong) mapping rather than adding a
    # new one — e.g. correcting the shipped "tan"->"yellow" mis-mapping to
    # "tan"->"brown". Lets callers say "corrected X: was A, now B" instead of
    # the misleading "added X".
    corrected_from: Optional[str] = None


def enrich_attribute(
    attribute_type: str,
    variant: str,
    llm_classify_fn: Optional[Callable[[str, list], Optional[str]]] = None,
    store: Optional[AttributeMappingStore] = None,
    explicit_canonical: Optional[str] = None,
    trigger: Optional[ReindexTrigger] = None,
) -> EnrichmentResult:
    """
    Classify a new attribute variant, write it to the mapping store, ensure
    the index mapping supports it, and trigger a real Lucille reindex.

    Args:
        attribute_type: "color", "waterproof", or any future registered type
        variant: the unmapped term (e.g. "chrome")
        llm_classify_fn: optional callable(term, canonical_names) -> canonical
            or None, used only when dictionary matching can't classify the
            term. This is where the agent's own LLM gets plugged in.
        store: AttributeMappingStore instance (constructed from env if None)
        explicit_canonical: skip classification entirely and use this
            canonical directly (e.g. admin/ops use). Still validated against
            the attribute type's canonical buckets.
        trigger: ReindexTrigger to run after the mapping is written
            (built from config.REINDEX_TRIGGER if None).

    Returns:
        EnrichmentResult — success=False with a `reason` if the attribute
        type is unknown, the term can't be classified, or it's already mapped.
        reindex_success reflects whether the triggered Lucille run completed
        cleanly; a classification/mapping success with a failed reindex is
        still success=True (the taxonomy grew) but reindex_success=False.
    """
    canonical_seeds = _CANONICAL_SEEDS_BY_TYPE.get(attribute_type)
    if canonical_seeds is None:
        return EnrichmentResult(
            success=False,
            attribute_type=attribute_type,
            variant=variant,
            reason=f"unknown attribute_type '{attribute_type}' (known: {list(_CANONICAL_SEEDS_BY_TYPE)})",
        )

    store = store or AttributeMappingStore()
    variant_lower = variant.lower().strip()

    if not variant_lower:
        return EnrichmentResult(
            success=False, attribute_type=attribute_type, variant=variant, reason="empty term"
        )

    existing_lookup = store.get_lookup_table(attribute_type)
    existing_canonical = existing_lookup.get(variant_lower)

    # A variant already in the taxonomy is only a no-op if it maps where the
    # caller wants it to. If the caller explicitly asks for a *different*
    # canonical, that's a correction of a wrong mapping — the whole point of
    # the flywheel when a taxonomy is mis-modelled rather than incomplete
    # (e.g. the shipped "tan"->"yellow", which makes "tan coat" return a
    # yellow raincoat). Without this, a wrong mapping could never be fixed.
    if existing_canonical is not None:
        if explicit_canonical is None or explicit_canonical == existing_canonical:
            return EnrichmentResult(
                success=False,
                attribute_type=attribute_type,
                variant=variant,
                canonical=existing_canonical,
                reason="already mapped",
            )

    if explicit_canonical is not None:
        if explicit_canonical not in canonical_seeds:
            return EnrichmentResult(
                success=False,
                attribute_type=attribute_type,
                variant=variant,
                reason=f"'{explicit_canonical}' is not a known canonical {attribute_type} bucket",
            )
        canonical = explicit_canonical
    else:
        canonical = single_term_classify(
            variant_lower,
            canonical_seeds,
            existing_lookup=existing_lookup,
            llm_classify_fn=llm_classify_fn,
        )

    if canonical is None:
        return EnrichmentResult(
            success=False,
            attribute_type=attribute_type,
            variant=variant,
            reason=f"could not classify to a known {attribute_type} bucket",
        )

    store.add_mapping(attribute_type, variant_lower, canonical, source="agent")
    if existing_canonical is not None:
        logger.info(
            "Enrichment: CORRECTED '%s' (%s) -> '%s' (was '%s')",
            variant_lower,
            attribute_type,
            canonical,
            existing_canonical,
        )
    else:
        logger.info(
            "Enrichment: mapped '%s' (%s) -> '%s'", variant_lower, attribute_type, canonical
        )

    _ensure_attribute_fields_mapped(store, attribute_type)

    outcome = (trigger or build_reindex_trigger()).trigger(attribute_type, [variant_lower])

    return EnrichmentResult(
        success=True,
        attribute_type=attribute_type,
        variant=variant,
        canonical=canonical,
        reindex_triggered=outcome.triggered,
        reindex_success=outcome.success,
        docs_processed=outcome.docs_processed,
        docs_scanned=outcome.docs_scanned,
        duration_seconds=outcome.duration_seconds,
        reindex_mode=outcome.mode,
        reindex_run_url=outcome.run_url,
        reindex_error=outcome.error,
        corrected_from=existing_canonical,
    )


def _ensure_attribute_fields_mapped(store: AttributeMappingStore, attribute_type: str) -> None:
    """
    Additively PUT the OpenSearch index mapping fields for a new attribute
    type (product_<type> dual-mapped text + product_<type>_primary/_secondary
    keyword), mirroring product_waterproof's mapping. No-op if already present
    — safe to call every time.
    """
    from core.config import OPENSEARCH_INDEX_NAME

    client = store.client
    current_mapping = client.indices.get_mapping(index=OPENSEARCH_INDEX_NAME)
    index_key = next(iter(current_mapping))
    properties = current_mapping[index_key].get("mappings", {}).get("properties", {})

    primary_field = f"product_{attribute_type}_primary"
    if primary_field in properties:
        return  # Already mapped, nothing to do.

    client.indices.put_mapping(
        index=OPENSEARCH_INDEX_NAME,
        body={
            "properties": {
                f"product_{attribute_type}": {
                    "type": "text",
                    "analyzer": "light_english_analyzer",
                    "fields": {
                        "keyword": {"type": "keyword"},
                        "heavy": {"type": "text", "analyzer": "heavy_english_analyzer"},
                    },
                },
                f"product_{attribute_type}_primary": {"type": "keyword"},
                f"product_{attribute_type}_secondary": {"type": "keyword"},
            }
        },
    )
    logger.info("Enrichment: added index mapping fields for attribute_type '%s'", attribute_type)
