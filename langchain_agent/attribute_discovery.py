"""
Attribute discovery service — attribute-agnostic bulk and single-term
classification for building/growing OS-backed attribute taxonomies
(see attribute_mapping_store.py).

Two modes:
  - bulk_discover: scan raw text samples for known variant terms, used once
    to bootstrap a new attribute's taxonomy (e.g. product_material) from the
    real dataset.
  - single_term_classify: classify one unmapped term to its best-fit
    canonical bucket, dictionary match first with an optional LLM fallback
    for novel terms. Used live by the agent enrichment tool when a query
    mentions an attribute value that isn't in the taxonomy yet.

The canonical seed dictionaries here (e.g. MATERIAL_CANONICALS) are a
bootstrapping starting point for the discovery algorithm, not the taxonomy
itself — the OpenSearch-backed mapping store is the actual source of truth
once bulk_discover's output has been written there via
AttributeMappingStore.seed_from_discovery().
"""

import re
from typing import Callable, Dict, List, Optional

# Seed vocabulary for material discovery. Derived from regex analysis of the
# real ESCI product dataset (data/esci_products_sample_10000.parquet) — see
# memory/opensearchcon_material_discovery.md for the frequency counts behind
# this list. Deliberately not exhaustive: gaps in this list are exactly what
# the live agent flywheel discovers and grows via single_term_classify.
MATERIAL_CANONICALS: Dict[str, List[str]] = {
    "leather": ["leather", "genuine leather", "cowhide", "suede", "faux leather"],
    "cotton": ["cotton", "100% cotton", "cotton blend"],
    "wool": ["wool", "woolen", "cashmere"],
    "synthetic": ["polyester", "nylon", "acrylic", "spandex"],
    "denim": ["denim", "jean"],
    "canvas": ["canvas"],
    "wood": ["wood", "wooden", "timber"],
    "metal": ["metal", "stainless steel", "aluminum", "brass", "steel", "iron"],
    "glass_ceramic": ["glass", "ceramic", "porcelain", "stoneware"],
    "rubber": ["rubber", "silicone", "latex"],
}


def bulk_discover(
    texts: List[str],
    canonical_seeds: Dict[str, List[str]],
    existing_lookup: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """
    Scan raw text for seed variant terms, returning every variant found at
    least once in the text, mapped to its canonical bucket.

    Args:
        texts: raw product text (titles, descriptions, bullet points, etc.)
        canonical_seeds: {canonical: [variant, ...]} starting vocabulary
        existing_lookup: variants to skip (already mapped elsewhere)

    Returns:
        {variant (lowercase): canonical} for every seed variant that
        actually appears in the text and isn't already mapped
    """
    existing_lookup = existing_lookup or {}
    discovered: Dict[str, str] = {}

    for canonical, variants in canonical_seeds.items():
        for variant in variants:
            variant_lower = variant.lower()
            if variant_lower in existing_lookup:
                continue

            pattern = re.compile(r"\b" + re.escape(variant_lower) + r"\b", re.IGNORECASE)
            for text in texts:
                if text and pattern.search(text):
                    discovered[variant_lower] = canonical
                    break

    return discovered


def single_term_classify(
    term: str,
    canonical_seeds: Dict[str, List[str]],
    existing_lookup: Optional[Dict[str, str]] = None,
    llm_classify_fn: Optional[Callable[[str, List[str]], Optional[str]]] = None,
) -> Optional[str]:
    """
    Classify one term to its best-fit canonical bucket.

    Resolution order:
        1. Already-known mapping (existing_lookup)
        2. Dictionary/substring match against canonical_seeds
        3. LLM fallback (llm_classify_fn), if provided, for novel terms that
           don't match any seed variant

    Args:
        term: the unmapped term to classify (e.g. "vegan leather")
        canonical_seeds: {canonical: [variant, ...]} known vocabulary
        existing_lookup: {variant: canonical} mappings already known (e.g.
            from the live OS-backed store, so an already-classified term
            short-circuits without re-running discovery logic)
        llm_classify_fn: optional callable(term, canonical_bucket_names) ->
            canonical or None, used only when dictionary matching fails.
            Kept injectable so this module has no LLM/langchain dependency.

    Returns:
        canonical bucket name, or None if unclassifiable
    """
    term_lower = term.lower().strip()
    existing_lookup = existing_lookup or {}

    if term_lower in existing_lookup:
        return existing_lookup[term_lower]

    for canonical, variants in canonical_seeds.items():
        for variant in variants:
            variant_lower = variant.lower()
            if (
                variant_lower == term_lower
                or variant_lower in term_lower
                or term_lower in variant_lower
            ):
                return canonical

    if llm_classify_fn is not None:
        return llm_classify_fn(term_lower, list(canonical_seeds.keys()))

    return None
