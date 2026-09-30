"""Attribute enrichment: the mechanism behind the agent's trigger_enrichment tool and
/api/admin/enrich, generic over attribute type (color, waterproof).

1. Classify the term against the type's canonical buckets, or accept an explicit canonical.
2. Write the variant->canonical mapping to the OpenSearch-backed mapping store.
3. Run a scoped re-tag (pipeline/scoped_retag.py) over the products whose text mentions the
   variant: seconds, no re-embedding, no full-corpus pass.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from pipeline.reindex_trigger import ScopedRetagTrigger
from retrieval.attribute_discovery import CANONICALS_BY_TYPE, single_term_classify
from retrieval.attribute_mapping_store import AttributeMappingStore

logger = logging.getLogger(__name__)


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
    docs_scanned: int = 0  # products re-detected (text mentions the variant)
    duration_seconds: float = 0.0
    reindex_error: Optional[str] = None  # short detail when reindex_success is False
    # The mapping this replaced, when it corrected a wrong one (e.g. "tan"->"yellow") rather than adding.
    corrected_from: Optional[str] = None


def enrich_attribute(
    attribute_type: str,
    variant: str,
    store: Optional[AttributeMappingStore] = None,
    explicit_canonical: Optional[str] = None,
    trigger: Optional[ScopedRetagTrigger] = None,
) -> EnrichmentResult:
    """Classify a variant, write it to the mapping store, and run a scoped re-tag.

    `explicit_canonical` skips classification (still validated against the buckets) and may
    correct an existing mapping. `trigger` lets tests inject a stand-in for the re-tag.

    Returns success=False with a `reason` for an unknown type, an unclassifiable term, or one
    already mapped. A failed re-tag still returns success=True (the taxonomy grew) with
    reindex_success=False.
    """
    canonical_seeds = CANONICALS_BY_TYPE.get(attribute_type)
    if canonical_seeds is None:
        return EnrichmentResult(
            success=False,
            attribute_type=attribute_type,
            variant=variant,
            reason=f"unknown attribute_type '{attribute_type}' (known: {list(CANONICALS_BY_TYPE)})",
        )

    store = store or AttributeMappingStore()
    variant_lower = variant.lower().strip()

    if not variant_lower:
        return EnrichmentResult(
            success=False, attribute_type=attribute_type, variant=variant, reason="empty term"
        )

    existing_lookup = store.get_lookup_table(attribute_type)
    existing_canonical = existing_lookup.get(variant_lower)

    # An existing mapping is a no-op only if it already maps where the caller wants; an
    # explicit *different* canonical is a correction (e.g. shipped "tan"->"yellow").
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

    outcome = (trigger or ScopedRetagTrigger()).trigger(attribute_type, [variant_lower])

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
        reindex_error=outcome.error,
        corrected_from=existing_canonical,
    )
