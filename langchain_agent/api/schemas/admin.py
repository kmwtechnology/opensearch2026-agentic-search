"""
Pydantic models for admin routes.

Only the enrichment endpoint needs typed request/response schemas today —
/api/admin/diagnose and /api/admin/health predate this and return plain
dicts (see api/routes/admin.py's module docstring).
"""

from typing import Optional

from pydantic import BaseModel, Field


class EnrichmentRequest(BaseModel):
    """Request to enrich the product_material taxonomy with a new variant."""

    variant: str = Field(
        ..., min_length=1, max_length=100, description="The unmapped material term, e.g. 'chrome'"
    )


class EnrichmentResponse(BaseModel):
    """Result of an enrichment attempt."""

    success: bool
    variant: str
    canonical: Optional[str] = Field(
        None, description="Canonical material bucket the variant resolved to, if successful"
    )
    docs_updated: int = Field(0, description="Number of documents updated with the new mapping")
    reason: Optional[str] = Field(None, description="Why the attempt failed, when success=False")
