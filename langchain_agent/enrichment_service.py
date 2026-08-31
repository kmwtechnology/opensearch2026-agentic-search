"""
Synchronous material enrichment service — the mechanism the live agent
enrichment tool calls when a query mentions a material term that isn't in
the taxonomy yet.

Flow (all in seconds, no GitHub/CI involved):
  1. Classify the gap term against the canonical material buckets
     (attribute_discovery.single_term_classify, with an optional LLM
     fallback for terms that don't dictionary-match).
  2. Write the new variant->canonical mapping to the OS-backed attribute
     mapping store (AttributeMappingStore.add_mapping).
  3. Scoped update_by_query: find documents whose chunk_text actually
     contains the new variant term and don't yet have
     product_material_primary set, and set it (and product_material,
     product_material_secondary where applicable) directly — mirrors what
     the Lucille MaterialNormalizerStage does at ingest time, but scoped to
     only the newly-relevant documents instead of a full reindex.

Lucille + reindex.yml remains the batch/full-reindex path (off-stage); this
service is purely for the live, synchronous on-stage trigger.
"""

import logging
from dataclasses import dataclass
from typing import Callable, Optional

from attribute_discovery import MATERIAL_CANONICALS, single_term_classify
from attribute_mapping_store import AttributeMappingStore

logger = logging.getLogger(__name__)


@dataclass
class EnrichmentResult:
    """Result of a material enrichment attempt."""

    success: bool
    variant: str
    canonical: Optional[str] = None
    docs_updated: int = 0
    reason: Optional[str] = None  # set when success=False


def enrich_material(
    variant: str,
    llm_classify_fn: Optional[Callable[[str, list], Optional[str]]] = None,
    store: Optional[AttributeMappingStore] = None,
    explicit_canonical: Optional[str] = None,
) -> EnrichmentResult:
    """
    Classify a new material variant, write it to the mapping store, and
    apply it to matching documents already in the index.

    Args:
        variant: the unmapped material term (e.g. "chrome")
        llm_classify_fn: optional callable(term, canonical_names) -> canonical
            or None, used only when dictionary matching can't classify the
            term. This is where the agent's own LLM gets plugged in.
        store: AttributeMappingStore instance (constructed from env if None)
        explicit_canonical: skip classification entirely and use this
            canonical directly, e.g. for admin/ops use where a human already
            knows the right bucket. Still validated against
            MATERIAL_CANONICALS — an unknown canonical is rejected the same
            as a classification failure, keeping the taxonomy bounded.

    Returns:
        EnrichmentResult — success=False with a `reason` if the term can't
        be classified, is already mapped, or no documents match.
    """
    store = store or AttributeMappingStore()
    variant_lower = variant.lower().strip()

    if not variant_lower:
        return EnrichmentResult(success=False, variant=variant, reason="empty term")

    existing_lookup = store.get_lookup_table("material")

    if variant_lower in existing_lookup:
        return EnrichmentResult(
            success=False,
            variant=variant,
            canonical=existing_lookup[variant_lower],
            reason="already mapped",
        )

    if explicit_canonical is not None:
        if explicit_canonical not in MATERIAL_CANONICALS:
            return EnrichmentResult(
                success=False,
                variant=variant,
                reason=f"'{explicit_canonical}' is not a known canonical material bucket",
            )
        canonical = explicit_canonical
    else:
        canonical = single_term_classify(
            variant_lower,
            MATERIAL_CANONICALS,
            existing_lookup=existing_lookup,
            llm_classify_fn=llm_classify_fn,
        )

    if canonical is None:
        return EnrichmentResult(
            success=False, variant=variant, reason="could not classify to a known material bucket"
        )

    store.add_mapping("material", variant_lower, canonical, source="agent")
    logger.info("Enrichment: mapped '%s' -> '%s'", variant_lower, canonical)

    docs_updated = _apply_to_matching_documents(store, variant_lower, canonical)

    return EnrichmentResult(
        success=True, variant=variant, canonical=canonical, docs_updated=docs_updated
    )


def _apply_to_matching_documents(store: AttributeMappingStore, variant: str, canonical: str) -> int:
    """
    Scoped update: find documents whose chunk_text mentions the new variant
    but don't yet have product_material_primary set, and populate it.

    Scoped by an actual text match (never an unscoped update_by_query) —
    both for speed and to avoid touching unrelated documents.
    """
    from config import OPENSEARCH_INDEX_NAME

    client = store.client

    query = {
        "bool": {
            "must": [{"match_phrase": {"chunk_text": variant}}],
            "must_not": [{"exists": {"field": "product_material_primary"}}],
        }
    }

    response = client.update_by_query(
        index=OPENSEARCH_INDEX_NAME,
        body={
            "query": query,
            "script": {
                "source": (
                    "ctx._source.product_material = params.variant; "
                    "ctx._source.product_material_primary = params.canonical;"
                ),
                "lang": "painless",
                "params": {"variant": variant, "canonical": canonical},
            },
        },
        refresh=True,
    )

    updated = response.get("updated", 0)
    logger.info(
        "Enrichment: applied '%s' -> '%s' to %d matching document(s)", variant, canonical, updated
    )
    return updated
