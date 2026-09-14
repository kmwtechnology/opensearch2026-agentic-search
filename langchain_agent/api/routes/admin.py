"""
Admin routes for operational tasks: health checks, index diagnostics, and
the live material enrichment flywheel.

Re-indexing is handled externally by ``lucille_ingest.sh`` (local dev) or the
``reindex.yml`` GitHub Actions workflow (Lucille ETL on the runner). There is no
in-container ingest path.

Protected by two-layer auth:
1. Origin check (``verify_same_origin``) — blocks cross-site usage
2. Session cookie OR admin token:
   - Session: normal authenticated user via LoginScreen
   - Admin token: automation (GitHub Actions) via X-Admin-Token header
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool

from api.middleware.origin_auth import verify_same_origin
from api.middleware.session_auth import verify_admin_token, verify_session
from api.schemas.admin import EnrichmentRequest, EnrichmentResponse

logger = logging.getLogger(__name__)

# Debug: Verify router is being created
router = APIRouter(prefix="/api/admin", tags=["admin"])
logger.info(f"Admin router created with prefix: {router.prefix}")


@router.get("/diagnose")
async def diagnose(request: Request, q: str = "sony") -> dict:
    """
    Probe the live index for a query across multiple fields.

    **Authentication:** Requires session (user login) OR X-Admin-Token header (automation).

    Diagnostic-only: answers "is there Sony data in the index, and which fields
    index it?" Compares hit counts for the suggest fields (title_suggest /
    brand_suggest) against the primary lexical fields (title / product_brand).
    If primary fields return hits while suggest fields don't, the mapping
    pre-dates the suggest fields and a re-index with reset_index=true is
    required.

    Also returns whether the mapping includes the suggest fields at all.
    """
    await verify_same_origin(request)
    try:
        await verify_session(request)
    except HTTPException:
        await verify_admin_token(request)
    return await run_in_threadpool(_diagnose_sync, q)


def _diagnose_sync(q: str) -> dict:
    """Blocking OpenSearch calls for /diagnose, run off the event loop via
    run_in_threadpool (see #25) so a slow/hanging index probe never stalls
    concurrent chat WebSocket traffic."""
    try:
        from core.config import OPENSEARCH_INDEX_NAME
        from retrieval.vector_store import get_shared_opensearch_client

        client = get_shared_opensearch_client()

        def count(field: str) -> dict:
            try:
                body = {"query": {"match": {field: q}}}
                res = client.count(index=OPENSEARCH_INDEX_NAME, body=body)
                return {"count": res.get("count", 0)}
            except Exception as exc:  # noqa: BLE001
                return {"error": f"{type(exc).__name__}: {exc}"}

        # Inspect mapping for suggest fields.
        mapping_fields: dict = {}
        try:
            mapping = client.indices.get_mapping(index=OPENSEARCH_INDEX_NAME)
            index_key = next(iter(mapping))
            properties = mapping[index_key].get("mappings", {}).get("properties", {})
            for f in ("title", "product_brand", "title_suggest", "brand_suggest"):
                mapping_fields[f] = f in properties
        except Exception as exc:  # noqa: BLE001
            mapping_fields = {"error": f"{type(exc).__name__}: {exc}"}

        return {
            "query": q,
            "index": OPENSEARCH_INDEX_NAME,
            "field_counts": {
                "title": count("title"),
                "product_brand": count("product_brand"),
                "title_suggest": count("title_suggest"),
                "brand_suggest": count("brand_suggest"),
            },
            "mapping_has_field": mapping_fields,
        }
    except Exception as e:  # noqa: BLE001
        return {"error": f"{type(e).__name__}: {e}"}


@router.get("/health")
async def admin_health(request: Request) -> dict:
    """Index-level health probe for the OpenSearch product index.

    **Authentication:** Requires session (user login) OR X-Admin-Token header (automation).

    Distinct from ``/api/health`` (which probes Postgres + OpenSearch
    cluster + Google AI reachability) — this endpoint reports the state
    of the application's primary index: whether it exists, whether
    OpenSearch is reachable, and the current document count.

    Used by the GitHub Actions reindex workflow to confirm the index has
    documents after a re-ingestion run.

    **Status values:**
        - ``healthy`` — index exists and is queryable; ``documents`` reflects
          the current count.
        - ``degraded`` — OpenSearch reachable but the index is missing
          (typical after a fresh deploy before ingestion runs).
        - ``unhealthy`` — OpenSearch is unreachable; ``error`` carries the
          exception message for debugging.
    """
    await verify_same_origin(request)
    try:
        await verify_session(request)
    except HTTPException:
        await verify_admin_token(request)
    return await run_in_threadpool(_admin_health_sync)


def _admin_health_sync() -> dict:
    """Blocking OpenSearch calls for /admin/health, run off the event loop
    via run_in_threadpool (see #25)."""
    try:
        from core.config import OPENSEARCH_INDEX_NAME
        from retrieval.vector_store import get_shared_opensearch_client

        client = get_shared_opensearch_client()

        # Check index exists and get stats
        if client.indices.exists(index=OPENSEARCH_INDEX_NAME):
            stats = client.count(index=OPENSEARCH_INDEX_NAME)
            doc_count = stats.get("count", 0)

            return {
                "status": "healthy",
                "opensearch": {
                    "connected": True,
                    "index": OPENSEARCH_INDEX_NAME,
                    "documents": doc_count,
                },
            }
        else:
            return {
                "status": "degraded",
                "opensearch": {
                    "connected": True,
                    "index": OPENSEARCH_INDEX_NAME,
                    "error": "Index does not exist",
                },
            }

    except Exception as e:
        return {
            "status": "unhealthy",
            "opensearch": {
                "connected": False,
                "error": str(e),
            },
        }


@router.post("/enrich", response_model=EnrichmentResponse)
async def enrich(request: Request, body: EnrichmentRequest) -> EnrichmentResponse:
    """
    Enrich a color or material taxonomy with a new variant term: write the
    mapping, ensure the index has the right fields, regenerate the Lucille
    config, and trigger a real full reindex. This is the same
    discover -> write -> reindex mechanism the live agent enrichment tool
    uses (enrichment_service.enrich_attribute), exposed here so it can be
    exercised and verified independently of the LLM loop.

    **Authentication:** Requires session (user login) OR X-Admin-Token header (automation).

    Gated by ``ENABLE_ENRICHMENT_TOOL`` (default off) — returns 403 when disabled.

    Classification is dictionary-only by default (no LLM fallback) — a term
    that doesn't match an existing variant in the given attribute_type's
    taxonomy returns ``success: false`` with a reason. Pass ``canonical`` to
    skip dictionary classification and supply the bucket directly, the same
    way the live agent tool supplies its own LLM-classified canonical.
    """
    await verify_same_origin(request)
    try:
        await verify_session(request)
    except HTTPException:
        await verify_admin_token(request)

    from core.config import ENABLE_ENRICHMENT_TOOL

    if not ENABLE_ENRICHMENT_TOOL:
        raise HTTPException(
            status_code=403, detail="Enrichment is disabled (ENABLE_ENRICHMENT_TOOL=false)"
        )

    result = await run_in_threadpool(
        _enrich_sync, body.attribute_type, body.variant, body.canonical
    )

    return EnrichmentResponse(
        success=result.success,
        attribute_type=result.attribute_type,
        variant=result.variant,
        canonical=result.canonical,
        reason=result.reason,
        reindex_triggered=result.reindex_triggered,
        reindex_success=result.reindex_success,
        docs_processed=result.docs_processed,
        duration_seconds=result.duration_seconds,
        reindex_mode=result.reindex_mode,
        reindex_run_url=result.reindex_run_url,
        reindex_error=result.reindex_error,
    )


def _enrich_sync(attribute_type: str, variant: str, canonical: Optional[str]):
    """enrich_attribute triggers a real catalog reindex -- locally a Lucille
    subprocess measured at ~17-20s, on Cloud Run a workflow dispatch that still
    makes blocking HTTP calls (see reindex_trigger.py). Called directly on the event loop
    this would freeze every in-flight WebSocket chat stream for the whole
    duration; run_in_threadpool (see #25) keeps it off the loop. The live
    agent's own trigger_enrichment tool call is unaffected by this bug --
    it already runs inside a LangGraph node, which astream_events dispatches
    to an executor thread, not the event loop."""
    from quality.enrichment_service import enrich_attribute

    return enrich_attribute(attribute_type, variant, explicit_canonical=canonical)
