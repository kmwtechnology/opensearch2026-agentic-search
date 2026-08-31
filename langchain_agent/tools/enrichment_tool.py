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
    Add a new color or material variant to the product search taxonomy and
    re-index the catalog so the fix takes effect immediately. Use this when
    a shopper's query mentions a color or material term that isn't
    recognized by the current search filters — for example, the search
    quality gate failed and the query mentions a plausible color/material
    word not covered by existing canonical categories. This performs a
    REAL, live catalog re-index (takes about 15-25 seconds) — only call it
    when you're confident the term is a genuine color or material the
    catalog should recognize, not for typos or unrelated query terms.
    """
    result = enrich_attribute(attribute_type, variant, explicit_canonical=canonical)

    if not result.success:
        return f"Could not enrich '{variant}' as {attribute_type}: {result.reason}"

    if not result.reindex_success:
        return (
            f"Added '{variant}' as a '{result.canonical}' {attribute_type} to the taxonomy, "
            f"but the catalog re-index failed to complete — the mapping is saved and will "
            f"take effect on the next successful re-index."
        )

    return (
        f"Added '{variant}' as a '{result.canonical}' {attribute_type}. "
        f"Re-indexed {result.docs_processed} products in {result.duration_seconds:.1f}s — "
        f"the fix is now live."
    )
