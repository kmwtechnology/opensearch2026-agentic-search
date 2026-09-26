"""
Health check endpoints for monitoring API and dependencies.
"""

import os
import sys
from pathlib import Path

import psycopg
from fastapi import APIRouter, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

# Add parent directory to path for config import (dynamic, not hardcoded)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from core.config import (
    API_VERSION,
    DATABASE_URL,
    EMBEDDINGS_MODEL,
    JUDGE_MODEL,
    LLM_MODEL,
    OPENSEARCH_INDEX_NAME,
    QUERY_EVAL_MODEL,
    VECTOR_COLLECTION_NAME,
)
from core.llm import missing_ollama_models

router = APIRouter()


def _health_check_sync() -> dict:
    """Synchronous health-check body -- run off the event loop via
    run_in_threadpool (see #25). psycopg.connect and the OpenSearch client's
    .count() are both blocking; called directly from an async def route they
    stall the loop (and every in-flight WebSocket) for up to the 5s connect
    timeout on a Postgres hiccup. This endpoint is also Cloud Run's
    --startup-probe target (see #23), polled on a schedule, so a stall here
    is an availability problem, not just added latency.
    """
    status = {
        "status": "ok",
        "version": API_VERSION,
        "postgres": False,
        "llm": False,
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
        from retrieval.vector_store import get_shared_opensearch_client

        client = get_shared_opensearch_client()
        result = client.count(
            index=OPENSEARCH_INDEX_NAME,
            body={"query": {"term": {"collection_id": VECTOR_COLLECTION_NAME}}},
        )
        doc_count = result["count"]
        status["vector_store"] = doc_count > 0
        status["document_count"] = doc_count
    except Exception:  # noqa: BLE001 # health probe must not raise
        status["vector_store_error"] = "Vector store connection failed"

    # Check the local Ollama server is up and has every model the agent calls
    # (#148). /api/tags is a local, sub-millisecond call -- fine for a probe.
    try:
        missing = missing_ollama_models(
            [LLM_MODEL, QUERY_EVAL_MODEL, JUDGE_MODEL, EMBEDDINGS_MODEL]
        )
        status["llm"] = not missing
        if missing:
            status["llm_error"] = f"Ollama models not pulled: {', '.join(missing)}"
    except Exception:  # noqa: BLE001 # health probe must not raise
        status["llm_error"] = "Ollama not reachable"

    # Overall status
    if not all([status["postgres"], status["llm"]]):
        status["status"] = "degraded"

    return status


@router.get("/health", summary="Full dependency health check (postgres, llm, opensearch)")
async def health_check():
    """
    Comprehensive health check of API and all dependencies.

    **Purpose:** Monitor system health and diagnose dependency failures.

    **Checks:**
        - **PostgreSQL** — Database for conversation checkpoints
        - **Ollama** — local LLM + embedding server (reachable, models pulled)
        - **OpenSearch** — Vector store for product search index

    **Response:** 200 OK
        ```json
        {
            "status": "ok",
            "version": "1.0.0",
            "postgres": true,
            "llm": true,
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
        - `llm` — Ollama reachable with every configured model pulled (bool)
        - `llm_error` — Why the llm check failed (optional)
        - `vector_store` — OpenSearch has documents (bool)
        - `vector_store_error` — Error message if vector_store check failed (optional)
        - `document_count` — Number of indexed documents (int, optional)

    **Use cases:**
        - Load balancer health probes
        - Monitoring alerts
        - Deployment readiness checks

    **Note:** Always returns 200 even if degraded (fail-open for monitoring).
        Runs off the event loop (see #25) -- the underlying checks are
        blocking (psycopg, requests-based OpenSearch client).

    Returns:
        Health status of postgres, llm, vector_store, and overall system.
    """
    return await run_in_threadpool(_health_check_sync)


@router.get("/health/ready", summary="Kubernetes/Cloud Run readiness probe")
async def readiness_check():
    """
    Kubernetes-style readiness probe.

    **Purpose:** Determine if the service is ready to accept traffic. Also
    used as the Cloud Run `--startup-probe` target (see #23): the agent's
    cross-encoder reranker model load is CPU-bound and can take tens of
    seconds on a cold instance. A bare TCP startup probe passes as soon as
    uvicorn binds the port -- long before that load finishes -- so Cloud Run
    was marking cold instances "ready" and routing real concurrent chat
    traffic to them while the reranker was still loading, which starved the
    event loop's ability to answer WebSocket keepalive pings on other
    connections (`1011 keepalive ping timeout`). Gating on this endpoint
    instead means Cloud Run won't route traffic until warmup has actually
    finished.

    **Behavior:**
        - Returns 200 OK if all critical services are healthy AND the agent's
          reranker warmup has completed (or warmup is disabled)
        - Returns 503 Service Unavailable otherwise
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
        or, while the reranker is still warming up:
        ```json
        {
            "ready": false,
            "reason": {"status": "ok", "warmup_complete": false, ...}
        }
        ```

    **Use cases:**
        - Cloud Run `--startup-probe` (gates traffic routing on cold starts)
        - Kubernetes liveness/readiness probes
        - Load balancer traffic routing
        - Deployment validation
        - Service orchestration

    Returns:
        Ready status and full health details if not ready.
    """
    # Local import: avoids a circular import at module load time (chat.py
    # imports from api.services.observable_agent, which is a heavy import
    # chain we don't want to pay unless something actually calls this route).
    from api.routes.chat import manager

    health = await health_check()
    warmup_complete = manager.agent_service._warmup_complete
    health["warmup_complete"] = warmup_complete

    if health["status"] == "ok" and warmup_complete:
        return {"ready": True}
    return JSONResponse(status_code=503, content={"ready": False, "reason": health})


@router.get("/config", summary="Runtime frontend config (API URL discovery)")
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
