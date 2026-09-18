"""
Pydantic models for admin routes.

Only the enrichment endpoint needs typed request/response schemas today —
/api/admin/diagnose and /api/admin/health predate this and return plain
dicts (see api/routes/admin.py's module docstring).
"""

from typing import Optional

from pydantic import BaseModel, Field


class EnrichmentRequest(BaseModel):
    """Request to enrich a color or waterproof taxonomy with a new variant."""

    attribute_type: str = Field(
        ..., description="Which taxonomy the variant belongs to: 'color' or 'waterproof'"
    )
    variant: str = Field(
        ..., min_length=1, max_length=100, description="The unmapped term, e.g. 'chrome'"
    )
    canonical: Optional[str] = Field(
        None,
        description=(
            "Skip dictionary classification and use this canonical bucket directly "
            "(e.g. 'brown' for color, 'waterproof' for waterproof), the same way the "
            "live agent tool supplies its own LLM-classified canonical. Required for "
            "terms the dictionary can't match."
        ),
    )


class EnrichmentResponse(BaseModel):
    """Result of an enrichment attempt."""

    success: bool
    attribute_type: str
    variant: str
    canonical: Optional[str] = Field(
        None, description="Canonical bucket the variant resolved to, if successful"
    )
    reason: Optional[str] = Field(None, description="Why the attempt failed, when success=False")
    reindex_triggered: bool = False
    reindex_success: bool = False
    docs_processed: int = Field(0, description="Documents processed by the triggered reindex")
    duration_seconds: float = Field(0.0, description="Wall-clock time of the triggered reindex")
    reindex_mode: str = Field(
        "local",
        description="Which reindex mechanism ran: always 'local' (Lucille subprocess, synchronous)",
    )
    reindex_run_url: Optional[str] = Field(
        None, description="Unused by the local trigger; kept for schema compat"
    )
    reindex_error: Optional[str] = Field(
        None, description="Short failure detail when reindex_success is False"
    )
