"""
FastAPI application with WebSocket support for real-time agent streaming.

This is the main entry point for the LangChain Agent API.
Run with: uvicorn api.main:app --reload --port 8000
"""

import warnings

# Suppress Pydantic V1 compatibility warning on Python 3.14+
# langchain-core imports pydantic.v1 for backward compatibility, but we use Pydantic V2
warnings.filterwarnings(
    "ignore",
    message="Core Pydantic V1 functionality isn't compatible with Python 3.14",
    category=UserWarning,
)

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from api.middleware.client_ip import get_client_ip
from api.routes import admin, chat, conversations, health, suggest
from core.config import API_VERSION, ENABLE_ENRICHMENT_TOOL, RATE_LIMIT_ENABLED
from core.logging_config import configure_logging, get_logger
from observability.otel import setup_tracing, shutdown_tracing
from pipeline.reindex_trigger import build_reindex_trigger

# Configure structured logging
configure_logging()
logger = get_logger(__name__)


def _get_api_base_url() -> str:
    """Get API base URL for logging, detecting environment automatically."""
    # Try to use VITE_API_URL from environment (set by frontend build)
    api_url = os.getenv("VITE_API_URL", "").strip()
    if api_url:
        return api_url
    # Fallback: detect from hostname
    hostname = os.getenv("HOSTNAME", "localhost")
    if "localhost" in hostname or "127.0.0.1" in hostname:
        return "http://localhost:8000"
    # Cloud Run or remote hostname
    return f"https://{hostname.split(':')[0]}"


# Initialize rate limiter
limiter = Limiter(
    key_func=get_client_ip,
    enabled=RATE_LIMIT_ENABLED,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager for startup and shutdown.

    Replaces deprecated @app.on_event("startup") and @app.on_event("shutdown")
    decorators with a modern async context manager pattern.
    """
    # Startup
    # Before the agent's first LLM call, so every call is traced (no-op
    # unless OTEL_EXPORTER_OTLP_ENDPOINT is set).
    setup_tracing()

    if ENABLE_ENRICHMENT_TOOL:
        # Fail fast on REINDEX_TRIGGER misconfiguration (e.g. github mode with no
        # token) instead of discovering it on the first live enrichment.
        build_reindex_trigger()

    # Initialize the agent (LLM clients, graph, reranker) and wait for
    # warmup to complete *before* the ASGI server starts accepting
    # connections. Uvicorn doesn't begin serving until this lifespan
    # startup event returns, so this blocks Cloud Run's startup probe from
    # succeeding until the instance can actually serve a chat request --
    # closing the race where a cold instance is marked ready (its container
    # just needs to be listening on the port) and receives concurrent chat
    # traffic while still loading the cross-encoder model in a background
    # thread. That CPU-bound load can starve the event loop's ability to
    # answer WebSocket keepalive pings on already-open connections, which
    # was showing up as `1011 keepalive ping timeout` under concurrent
    # load on cold deploys. See #23.
    await chat.manager.agent_service.ensure_initialized()
    await chat.manager.agent_service._wait_for_warmup()

    base_url = _get_api_base_url()
    logger.info(
        "api_started",
        rest_api=f"{base_url}/api",
        websocket=base_url.replace("http", "ws") + "/ws/chat",
        docs=f"{base_url}/swagger",
    )

    yield  # Application runs here

    # Shutdown
    logger.info("api_shutting_down")
    try:
        await chat.manager.shutdown()
    except Exception as e:
        logger.error(f"Error during shutdown: {e}")
    shutdown_tracing()
    logger.info("api_shutdown_complete")


tags_metadata = [
    {
        "name": "health",
        "description": (
            "System and index health probes. `/api/health` reports Postgres + OpenSearch + "
            "Google AI reachability; `/api/admin/health` reports current index document count."
        ),
    },
    {
        "name": "suggest",
        "description": (
            "Typeahead autocomplete with spell correction. Edge-ngram prefix matching on "
            "`title_suggest` and `brand_suggest` fields, with Levenshtein + SequenceMatcher "
            "spell correction and a distance-1 fuzzy fallback for single-character typos."
        ),
    },
    {
        "name": "conversations",
        "description": "Conversation history CRUD (LangGraph checkpoints in Postgres).",
    },
    {
        "name": "admin",
        "description": (
            "Operational endpoints for index health and diagnostics (same-origin only). "
            "Reindexing is handled externally: `bash scripts/lucille_ingest.sh`. "
            "No in-container ingest."
        ),
    },
    {
        "name": "chat",
        "description": (
            "Real-time streaming chat. WebSocket at `/ws/chat` is the primary surface; "
            "a synchronous REST fallback lives at `/api/chat`."
        ),
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
        "40-doc batch, default) or optional Gemini LLM (~500ms–1s), 0.0–1.0 scores; on a "
        "low score the gate retries once with a widened retrieval pool (not just a "
        "re-weighted alpha, which alone was measured to not move the reranker's score)\n"
        "- **Typeahead autocomplete**: `/api/suggest` edge-ngram prefix matching with "
        "spell correction and distance-1 fuzzy fallback\n"
        "- **BM25 optimizations**: synonyms, phrase boosting, field boosting, phonetic matching\n"
        "- **Per-query optimization toggles**: 10 flags (hybrid, fuzzy, synonyms, phonetic, "
        "phrase_boost, field_boost, typeahead, reranking, llm, llm_judge) sent on every WebSocket chat "
        "message; the pipeline collapses skipped stages out of the observability panel.\n"
        "- **Pipeline Quality Summary**: end-of-pipeline `PipelineSummaryEvent` carrying "
        "BM25 / Hybrid / Reranked NDCG@10, MRR, Recall@20, Precision@10 against ESCI "
        "ground-truth judgments, plus per-stage latency lift-per-100ms. "
        "Falls back to self-referential confidence proxy (top-1 score, gap, variance, rank churn) when no ground truth exists.\n"
        "- **OpenSearch DSL viewer**: `OpenSearchQueryEvent` carries the full DSL `body` "
        "(with embedding vector scrubbed), `index`, and `params` for the actual request the "
        "retriever sent. `query_type` ∈ {`hybrid`, `bm25_baseline`, `quality_gate_retry`} "
        "tags each event so the observability panel can render an eye-icon viewer per query.\n"
        "- **Real-time streaming**: token-by-token output over WebSocket\n\n"
        "**Authentication:** Same-origin check (localhost dev ports + Cloud Run URL) "
        "on every route."
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


# Add rate limiter to app state
app.state.limiter = limiter

# Register rate limit exceeded handler
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS configuration
# Accept localhost for development plus this service's Cloud Run URL
cors_origins = [
    "http://localhost:5173",  # Vite dev server
    "http://localhost:3000",  # Alternative dev port
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]

# Add explicitly configured origins (e.g., custom domains)
if os.environ.get("CORS_ORIGINS"):
    configured_origins = [
        o.strip() for o in os.environ.get("CORS_ORIGINS", "").split(",") if o.strip()
    ]
    cors_origins.extend(configured_origins)

# Determine this service's URL for Cloud Run
# The frontend will request from the same origin, so we need to allow it
# This is set dynamically via the /api/config endpoint at runtime
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_origin_regex=r"https://.*\.a\.run\.app",  # Accept all Cloud Run URLs
)

# Register REST routes
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(conversations.router, prefix="/api", tags=["conversations"])
app.include_router(suggest.router, prefix="/api", tags=["suggest"])
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
