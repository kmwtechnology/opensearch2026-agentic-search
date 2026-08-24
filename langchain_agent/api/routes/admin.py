"""
Admin routes for operational tasks: health checks and index diagnostics.

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

from fastapi import APIRouter, HTTPException, Request

from api.middleware.origin_auth import verify_same_origin
from api.middleware.session_auth import verify_admin_token, verify_session

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
    try:
        from config import OPENSEARCH_INDEX_NAME
        from vector_store import create_opensearch_client

        client = create_opensearch_client()

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
    try:
        from config import OPENSEARCH_INDEX_NAME
        from vector_store import create_opensearch_client

        client = create_opensearch_client()

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
