"""
trigger_enrichment — the real LangChain tool the agent uses to grow the
color or material taxonomy live, on stage. The calling LLM decides the
attribute_type, the raw variant term, and its canonical bucket itself (the
model already understands materials/colors semantically); the tool just
executes: write the mapping, ensure index fields, regenerate config, trigger
a real Lucille reindex.

Gated by config.ENABLE_ENRICHMENT_TOOL — bind this tool in agent_node only
when that flag is on (see main.py's agent_node gap-signal branch).
"""

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from attribute_discovery import COLOR_CANONICALS, MATERIAL_CANONICALS
from enrichment_service import enrich_attribute

_CANONICAL_BUCKETS_DESCRIPTION = (
    f"Valid canonical buckets by attribute_type: "
    f"color: {sorted(COLOR_CANONICALS.keys())}; "
    f"material: {sorted(MATERIAL_CANONICALS.keys())}."
)


class TriggerEnrichmentInput(BaseModel):
    attribute_type: str = Field(
        description='Which taxonomy the gap belongs to: "color" or "material".'
    )
    variant: str = Field(
        description="The raw, unrecognized term from the user's query, e.g. 'chrome'."
    )
    canonical: str = Field(
        description=(
            "The canonical bucket this variant belongs to, chosen from the "
            f"valid buckets for the given attribute_type. {_CANONICAL_BUCKETS_DESCRIPTION}"
        )
    )


@tool("trigger_enrichment", args_schema=TriggerEnrichmentInput)
def trigger_enrichment(attribute_type: str, variant: str, canonical: str) -> str:
    """
    Add a new color or material variant to the product search taxonomy, OR
    correct one that's already mapped to the wrong canonical bucket, and
    re-index the catalog so the fix takes effect immediately.

    Two distinct situations call this the same way:
    1. GAP: a shopper's query mentions a color/material term not yet
       recognized by the current search filters (search quality gate
       failed, term isn't in the taxonomy at all).
    2. CORRECTION: a shopper points out that a term IS in the taxonomy but
       mapped to the wrong bucket (e.g. "that's not tan, it's yellow" —
       the catalog currently thinks tan means yellow). Pass the variant
       and its CORRECT canonical; the existing wrong mapping is replaced.

    This performs a REAL, live catalog re-index (about 15-25 seconds when
    run locally; on the hosted deployment it is dispatched to a CI workflow
    that finishes in about 8 minutes) — only call it when you're confident the term is a genuine
    color or material and you know what the correct bucket should be, not
    for typos or unrelated query terms.
    """
    result = enrich_attribute(attribute_type, variant, explicit_canonical=canonical)

    if not result.success:
        return f"Could not enrich '{variant}' as {attribute_type}: {result.reason}"

    action = (
        f"Corrected '{variant}' from '{result.corrected_from}' to '{result.canonical}'"
        if result.corrected_from
        else f"Added '{variant}' as a '{result.canonical}' {attribute_type}"
    )

    if not result.reindex_success:
        detail = f" ({result.reindex_error})" if result.reindex_error else ""
        return (
            f"{action} in the taxonomy, but the catalog re-index failed to complete{detail} — "
            f"the mapping is saved and will take effect on the next successful re-index."
        )

    if result.reindex_mode == "github":
        return (
            f"{action}. Catalog re-index dispatched to GitHub Actions "
            f"({result.reindex_run_url}); it takes about 8 minutes and the fix goes "
            f"live when it finishes."
        )

    return (
        f"{action}. Re-indexed {result.docs_processed} products in "
        f"{result.duration_seconds:.1f}s — the fix is now live."
    )
