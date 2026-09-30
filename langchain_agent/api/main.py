"""
FastAPI application with WebSocket support for real-time agent streaming.

This is the main entry point for the LangChain Agent API.
Run with: uvicorn api.main:app --reload --port 8080
"""

import warnings

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from api.middleware.origin_auth import get_allowed_origins
from api.routes import admin, chat, health
from core.config import API_VERSION
from core.logging_config import configure_logging, get_logger

# Configure structured logging
configure_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown")
    decorators with a modern async context manager pattern.
    """
    # Initialize the agent (LLM clients, graph, reranker) and wait for
    # warmup to complete *before* the ASGI server starts accepting
    # connections. Uvicorn doesn't begin serving until this lifespan
    # startup event returns, so this closes the race where the process is
    # listening on the port and receives concurrent chat traffic while
    # still loading the cross-encoder model in a background thread. That
    # CPU-bound load can starve the event loop's ability to answer
    # WebSocket keepalive pings on already-open connections, which was
    # showing up as `1011 keepalive ping timeout` under concurrent load on
    # a cold start. See #23.
    await chat.manager.agent_service.ensure_initialized()
    await chat.manager.agent_service._wait_for_warmup()

    logger.info("api_started", rest_api="/api", websocket="/ws/chat", docs="/swagger")

    yield  # Application runs here

    # Shutdown
    logger.info("api_shutting_down")
    try:
        await chat.manager.shutdown()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    logger.info("api_shutdown_complete")


tags_metadata = [
    {
        "name": "health",
        "description": (
            "System and index health probes. `/api/health` reports Postgres + OpenSearch + "
            "Ollama reachability; `/api/admin/health` reports current index document count."
        ),
    },
    {
        "name": "admin",
        "description": (
            "Operational endpoints for index health and diagnostics (same-origin only). "
            "Reindexing is a scoped, in-process re-tag (pipeline/scoped_retag.py) "
            "triggered by the enrichment flywheel — no external ingest pipeline."
        ),
    },
    {
        "name": "chat",
        "description": ("Real-time streaming chat over the WebSocket at `/ws/chat`."),
    },
]

app = FastAPI(
    title="Agentic Hybrid Search API",
    description=(
        "Production-grade RAG agent for Amazon ESCI e-commerce product search, "
        "running local-only (Docker Compose).\n\n"
        "**Features:**\n"
        "- **Hybrid search**: BM25 + vector (RRF fusion, k=60) with dynamic alpha per intent\n"
        "- **Intent routing**: 7 classes (search, comparison, attribute_filter, refinement, "
        "follow_up, summary, clarify)\n"
        "- **Reranking + quality gate**: Cross-encoder (ms-marco-MiniLM-L-12-v2, ~2s for a "
        "40-doc batch, the only reranker) scores 0.0–1.0; on a "
        "low score the gate retries once with a widened retrieval pool (not just a "
        "re-weighted alpha, which alone was measured to not move the reranker's score)\n"
        "- **BM25 tuning**: phrase boosting, field boosting, bounded fuzziness\n"
        "- **Pipeline Summary**: end-of-pipeline `PipelineSummaryEvent` with per-stage latency "
        "and a self-referential confidence proxy (top-1 score, gap, variance, rank churn).\n"
        "- **OpenSearch DSL viewer**: `OpenSearchQueryEvent` carries the full DSL `body` "
        "(with embedding vector scrubbed), `index`, and `params` for the actual request the "
        "retriever sent. `query_type` ∈ {`hybrid`, `quality_gate_retry`} "
        "tags each event so the observability panel can render an eye-icon viewer per query.\n"
        "- **Real-time streaming**: token-by-token output over WebSocket\n\n"
        "**Authentication:** Same-origin check (localhost dev ports) on every route."
    ),
    version=API_VERSION,
    docs_url=None,  # served by the custom route below (#103)
    redoc_url="/redoc",
    openapi_tags=tags_metadata,
    contact={
        "name": "KMW Technology",
        "url": "https://github.com/kmwtechnology/opensearch2026-agentic-search",
    },
    lifespan=lifespan,
)


# ----------------------------------------------------------------------------
# Swagger UI, sized for a projector (#103).
#
# FastAPI's built-in docs_url serves Swagger UI at its stock ~12-13px, which is
# unreadable from the back of a room — and this page is part of the demo, shown
# through an iframe on /swagger in the SPA. The SPA cannot restyle it (the
# iframe is cross-origin), so the size has to come from the server.
#
# Everything here is presentation only: the same generated spec, larger type
# and stronger contrast.
# ----------------------------------------------------------------------------

_SWAGGER_PROJECTOR_CSS = """
<style>
  body, .swagger-ui { font-size: 20px; }
  .swagger-ui .info .title { font-size: 44px; }
  .swagger-ui .info .base-url,
  .swagger-ui .info p,
  .swagger-ui .markdown p { font-size: 21px; line-height: 1.55; }
  .swagger-ui .opblock-tag { font-size: 30px; padding: 14px 20px; }
  .swagger-ui .opblock .opblock-summary-method { font-size: 20px; min-width: 100px; }
  .swagger-ui .opblock .opblock-summary-path,
  .swagger-ui .opblock .opblock-summary-path__deprecated { font-size: 22px; }
  .swagger-ui .opblock .opblock-summary-description { font-size: 20px; }
  .swagger-ui .opblock-description-wrapper p,
  .swagger-ui .opblock-external-docs-wrapper p { font-size: 20px; }
  .swagger-ui table thead tr th,
  .swagger-ui table thead tr td { font-size: 19px; }
  .swagger-ui .parameter__name { font-size: 21px; }
  .swagger-ui .parameter__type { font-size: 18px; }
  .swagger-ui .response-col_status { font-size: 21px; }
  .swagger-ui .btn { font-size: 19px; }
  .swagger-ui .model, .swagger-ui .model-title { font-size: 19px; }
  .swagger-ui .highlight-code, .swagger-ui .microlight { font-size: 18px; line-height: 1.5; }
  .swagger-ui .scheme-container { padding: 16px 0; }
  /* Description markdown: the feature bullets and the per-tag blurbs render
     through .renderedMarkdown and stay at the stock ~12px without this. */
  .swagger-ui .renderedMarkdown p,
  .swagger-ui .renderedMarkdown li,
  .swagger-ui .markdown li { font-size: 20px; line-height: 1.6; }
  .swagger-ui .opblock-tag small,
  .swagger-ui .opblock-tag small p { font-size: 19px; line-height: 1.5; }
  .swagger-ui .renderedMarkdown code,
  .swagger-ui .markdown code { font-size: 18px; padding: 2px 6px; }
  .swagger-ui .info .description code { font-size: 18px; }
  /* Stock Swagger caps the column at ~1460px and centres it; on a 1920 screen
     that wastes half the width on margins. */
  .swagger-ui .wrapper { max-width: 1700px; padding: 0 24px; }
  /* Stock Swagger greys sit around 4:1; darken for projection. */
  .swagger-ui, .swagger-ui .info li, .swagger-ui .info p { color: #14130f; }
  .swagger-ui .opblock .opblock-summary-description,
  .swagger-ui .parameter__type { color: #3d3a33; }
</style>
"""


@app.get("/swagger", include_in_schema=False)
async def projector_swagger_ui() -> HTMLResponse:
    """Swagger UI with projector-sized type. Same spec, bigger text."""
    from fastapi.openapi.docs import get_swagger_ui_html

    html = get_swagger_ui_html(
        openapi_url=app.openapi_url or "/openapi.json",
        title=f"{app.title} — API",
    ).body.decode()
    return HTMLResponse(html.replace("</head>", f"{_SWAGGER_PROJECTOR_CSS}</head>"))


# CORS configuration
# Reuses the same allow-list api/middleware/origin_auth.py's verify_same_origin
# enforces -- these used to be two independently-maintained origin lists (this
# one had its own hardcoded Cloud Run allowance, `get_allowed_origins()` had a
# separate one) that had already drifted apart (this one was missing the
# :5174/:8000/:8080 dev origins the other allows).
cors_origins = get_allowed_origins()

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register REST routes
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(admin.router, tags=["admin"])

# Register WebSocket route
app.include_router(chat.router, tags=["chat"])

# Mount static files for React frontend (if built)
static_dir = Path(__file__).parent.parent / "web" / "dist"
if static_dir.exists():
    # Mount assets directory
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")

    # Serve React app for all non-API routes
    @app.get("/{full_path:path}")
    async def serve_react(full_path: str):
        """Serve React frontend for all non-API routes.

        Note (#105): there is no dedicated `/docs` route, and there should
        not be -- `docs_url=None` above deliberately disables FastAPI's
        built-in one (see test_swagger_route.py). `/docs` returns 200 only
        because this catch-all serves index.html for it like any other
        unknown path; the response is identical to `/nonsense-path-xyz`.
        The real, projector-sized API docs live at `/swagger`.
        """
        # Skip API routes and documentation
        if (
            full_path.startswith("api/")
            or full_path.startswith("ws/")
            or full_path in ("swagger", "redoc", "openapi.json")
        ):
            return JSONResponse({"error": "Not Found"}, status_code=404)

        # Serve index.html for all other routes (React Router will handle)
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(index_file)

        return JSONResponse({"error": "Frontend not built"}, status_code=404)
