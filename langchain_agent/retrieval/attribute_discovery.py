"""
Attribute classification for the OS-backed attribute taxonomies (see
attribute_mapping_store.py): single_term_classify maps one unmapped term to
its best-fit canonical bucket, dictionary match first with an optional LLM
fallback for novel terms. Used live by the agent enrichment tool when a query
mentions an attribute value that isn't in the taxonomy yet.

The canonical seed dictionaries here (e.g. WATERPROOF_CANONICALS) are the
bounded set of buckets a term may be classified into, not the taxonomy
itself — the OpenSearch-backed mapping store (loaded from the committed
data/precomputed dump) is the source of truth.
"""

from typing import Callable, Dict, List, Optional

# Seed vocabulary for the waterproof attribute type. Deliberately a single
# bucket with NO seed variants (unlike COLOR_CANONICALS below) — this is the
# schema-growth demo's attribute type, and it needs single_term_classify("
# waterproof", WATERPROOF_CANONICALS) to genuinely return None until the live
# enrichment flywheel writes a real mapping to the OS-backed store. A
# pre-seeded variant list would make "waterproof hiking boots" resolve on day
# one, with no gap left to demonstrate. The canonical key itself ("waterproof")
# still has to exist so trigger_enrichment has a known, bounded bucket to
# write into (see enrichment_service.enrich_attribute's explicit_canonical
# check) — only its variants start empty.
WATERPROOF_CANONICALS: Dict[str, List[str]] = {
    "waterproof": [],
}

# Seed vocabulary for color: the canonical buckets and their common variants.
# Like WATERPROOF_CANONICALS, a classification seed, not the taxonomy itself —
# the live color taxonomy lives in the OpenSearch mapping store.
COLOR_CANONICALS: Dict[str, List[str]] = {
    "black": ["black", "jet", "charcoal", "ebony", "onyx"],
    "white": ["white", "ivory", "cream", "off-white", "ecru", "beige", "bone"],
    "blue": ["blue", "navy", "cyan", "turquoise", "teal", "aqua", "indigo", "cobalt", "denim"],
    "red": ["red", "crimson", "scarlet", "maroon", "burgundy", "wine", "rust", "brick"],
    "green": ["green", "lime", "emerald", "sage", "olive", "mint", "forest", "moss", "hunter"],
    "yellow": ["yellow", "gold", "amber", "tan", "khaki", "mustard", "champagne"],
    "pink": ["pink", "rose", "mauve", "salmon", "blush", "coral", "fuchsia", "magenta"],
    "purple": ["purple", "violet", "lavender", "plum", "lilac", "eggplant"],
    "brown": [
        "brown",
        "chocolate",
        "bronze",
        "copper",
        "cognac",
        "taupe",
        "mocha",
        "espresso",
        "coffee",
        "caramel",
    ],
    "gray": [
        "gray",
        "grey",
        "silver",
        "ash",
        "slate",
        "pewter",
        "graphite",
        "nickel",
        "chrome",
        "titanium",
    ],
    "orange": ["orange", "coral", "peach", "tangerine", "apricot"],
    "clear": ["clear", "transparent", "translucent", "crystal"],
    "multicolor": [
        "multicolor",
        "multicolored",
        "multi-color",
        "multi-colored",
        "multi",
        "rainbow",
        "colorful",
    ],
    "natural": ["natural", "wood", "natural wood", "unfinished", "raw"],
    "mixed": ["assorted", "mixed", "various", "pattern"],
}


# Canonical bucket vocabularies by attribute type; add an entry when a new type gets a seed dict.
CANONICALS_BY_TYPE: Dict[str, Dict[str, List[str]]] = {
    "color": COLOR_CANONICALS,
    "waterproof": WATERPROOF_CANONICALS,
}


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
