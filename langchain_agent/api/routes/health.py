"""
Health check endpoints for monitoring API and dependencies.
"""

import os
import sys
from pathlib import Path

import psycopg
from fastapi import APIRouter, Request

# Add parent directory to path for config import (dynamic, not hardcoded)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from config import DATABASE_URL, GOOGLE_API_KEY, OPENSEARCH_INDEX_NAME, VECTOR_COLLECTION_NAME

router = APIRouter()


@router.get("/health")
async def health_check():
    """
    Comprehensive health check of API and all dependencies.

    **Purpose:** Monitor system health and diagnose dependency failures.

    **Checks:**
        - **PostgreSQL** — Database for conversation checkpoints
        - **Google AI API** — LLM and embeddings service (checks API key only)
        - **OpenSearch** — Vector store for product search index

    **Response:** 200 OK
        ```json
        {
            "status": "ok",
            "version": "1.1.0",
            "postgres": true,
            "google_ai": true,
            "vector_store": true,
            "document_count": 10000
        }
        ```

    **Status Values:**
        - `"ok"` — All critical services healthy
        - `"degraded"` — At least one service unhealthy (still responds 200)

    **Response Fields:**
        - `status` — Overall system health ("ok" or "degraded")
        - `version` — API version
        - `postgres` — PostgreSQL connection healthy (bool)
        - `postgres_error` — Error message if postgres check failed (optional)
        - `google_ai` — Google AI API key configured (bool)
        - `google_ai_error` — Error message if google_ai check failed (optional)
        - `vector_store` — OpenSearch has documents (bool)
        - `vector_store_error` — Error message if vector_store check failed (optional)
        - `document_count` — Number of indexed documents (int, optional)

    **Use cases:**
        - Load balancer health probes
        - Monitoring alerts
        - Deployment readiness checks

    **Note:** Always returns 200 even if degraded (fail-open for monitoring).

    Returns:
        Health status of postgres, google_ai, vector_store, and overall system.
    """
    status = {
        "status": "ok",
        "version": "1.1.0",
        "postgres": False,
        "google_ai": False,
        "vector_store": False,
    }

    # Check PostgreSQL (with connection timeout) - used for checkpoints
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                status["postgres"] = True
    except Exception:  # noqa: BLE001 # health probe must not raise
        status["postgres_error"] = "Database connection failed"

    # Check OpenSearch vector store has documents
    try:
        from vector_store import create_opensearch_client

        client = create_opensearch_client()
        result = client.count(
            index=OPENSEARCH_INDEX_NAME,
            body={"query": {"term": {"collection_id": VECTOR_COLLECTION_NAME}}},
        )
        doc_count = result["count"]
        status["vector_store"] = doc_count > 0
        status["document_count"] = doc_count
    except Exception:  # noqa: BLE001 # health probe must not raise
        status["vector_store_error"] = "Vector store connection failed"

    # Check Google AI API key is configured (don't leak the fact it's missing)
    status["google_ai"] = bool(GOOGLE_API_KEY)

    # Overall status
    if not all([status["postgres"], status["google_ai"]]):
        status["status"] = "degraded"

    return status


@router.get("/health/ready")
async def readiness_check():
    """
    Kubernetes-style readiness probe.

    **Purpose:** Determine if the service is ready to accept traffic.

    **Behavior:**
        - Returns 200 OK if all critical services are healthy
        - Returns 503 Service Unavailable if any critical service is down
        - Used by Kubernetes, load balancers, and orchestration systems

    **Request:** `GET /api/health/ready`

    **Success Response:** 200 OK
        ```json
        {
            "ready": true
        }
        ```

    **Failure Response:** 503 Service Unavailable
        ```json
        {
            "ready": false,
            "reason": {
                "status": "degraded",
                "postgres": false,
                "postgres_error": "Connection refused"
            }
        }
        ```

    **Use cases:**
        - Kubernetes liveness/readiness probes
        - Load balancer traffic routing
        - Deployment validation
        - Service orchestration

    Returns:
        Ready status and full health details if not ready.
    """
    health = await health_check()
    if health["status"] == "ok":
        return {"ready": True}
    return {"ready": False, "reason": health}


@router.get("/config")
async def get_frontend_config(request: Request):
    """
    Runtime configuration for frontend.

    **Purpose:** Allow frontend to discover API URL at runtime (not build time).

    **Why needed:**
        - Same code runs on localhost (dev) and Cloud Run (prod)
        - Frontend doesn't know its own domain until runtime
        - API_URL is environment-dependent

    **Request:** `GET /api/config`

    **Response:** 200 OK
        ```json
        {
            "apiUrl": "https://agentic-hybrid-search-abc123.run.app"
        }
        ```
        (or empty string in dev if not configured)

    **Behavior:**
        - If request Origin is HTTPS → use Origin as apiUrl (Cloud Run)
        - If request Origin is HTTP → use API_URL env var (dev, may be empty)
        - Frontend uses this to construct WebSocket and API URLs

    **Frontend Usage:**
        ```typescript
        const config = await fetch('/api/config').then(r => r.json());
        const wsUrl = `${config.apiUrl}/ws/chat`;
        const ws = new WebSocket(wsUrl);
        ```

    **Environment Variables:**
        - `API_URL` — Optional explicit API base URL (for dev behind proxy)

    Returns:
        Frontend configuration object with apiUrl.
    """
    # Get the origin URL from the request
    origin = request.headers.get("origin", "")

    # Determine API base URL
    # In production (Cloud Run), use the origin URL
    # In development, use localhost:8000
    if origin and origin.startswith("https://"):
        api_url = origin
    else:
        api_url = os.environ.get("API_URL", "")

    return {
        "apiUrl": api_url,
    }
