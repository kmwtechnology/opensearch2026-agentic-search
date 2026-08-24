"""
Origin-based authentication for same-origin-only API access.

This middleware ensures that only requests from the same origin
(the UI served from Cloud Run) can access the API.

Provides:
- Origin header validation for REST endpoints
- Same-origin enforcement for WebSocket endpoints
- Automatic same-origin detection on Cloud Run
"""

import logging
import re
from typing import Optional

from fastapi import HTTPException, Request, WebSocket, status

logger = logging.getLogger(__name__)


def get_allowed_origins() -> list[str]:
    """
    Get list of allowed origins.

    On Cloud Run, this automatically includes the service URL and all Cloud Run domains.
    In development, allows localhost.

    Returns:
        List of allowed origins
    """
    return [
        "http://localhost:5173",  # Vite dev
        "http://localhost:5174",  # Vite dev (fallback port)
        "http://localhost:3000",  # Alt dev
        "http://localhost:8000",  # Backend dev (local e2e tests)
        "http://localhost:8080",  # Dev server
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:8000",
        "http://127.0.0.1:8080",
    ]


def is_allowed_origin(origin: Optional[str], referer: Optional[str] = None) -> bool:
    """
    Check if origin is allowed.

    On Cloud Run, accepts any *.a.run.app domain (same service).
    In development, accepts localhost.

    For GET requests without an Origin header, checks the Referer header instead
    (same-origin GET requests don't include Origin by default).

    Args:
        origin: Origin header value
        referer: Referer header value (fallback for GET requests without Origin)

    Returns:
        True if origin is allowed
    """
    # Try Origin header first (sent by cross-origin requests and POST/DELETE/PUT)
    if origin:
        allowed_origins = get_allowed_origins()

        # Exact match for development origins
        if origin in allowed_origins:
            return True

        # Allow any Cloud Run domain (*.a.run.app)
        if re.match(r"https://.*\.run\.app$", origin):
            return True

    # Fallback to Referer header for same-origin GET requests
    # (same-origin GET requests don't include Origin by design)
    if referer:
        # Extract origin from referer (e.g., "http://localhost:5173/path" -> "http://localhost:5173")
        referer_origin = "/".join(referer.split("/")[:3])  # Keep only scheme://host:port
        allowed_origins = get_allowed_origins()

        # Exact match for development origins
        if referer_origin in allowed_origins:
            return True

        # Allow any Cloud Run domain (*.a.run.app)
        if re.match(r"https://.*\.run\.app$", referer_origin):
            return True

    return False


async def verify_same_origin(request: Request) -> bool:
    """
    Verify that the request is from the same origin.

    This is the primary security mechanism: only the UI served from the same
    Cloud Run service can access the API. External clients cannot.

    For same-origin requests (which don't include Origin header by default),
    uses the Referer header as a fallback, then Host header as final fallback.

    Args:
        request: FastAPI request object

    Returns:
        True if request is from allowed origin

    Raises:
        HTTPException: If origin is not allowed (403 Forbidden)
    """
    origin = request.headers.get("origin")
    referer = request.headers.get("referer")
    host = request.headers.get("host")
    method = request.method

    logger.debug(
        f"Origin auth check: method={method}, origin={origin}, referer={referer}, host={host}"
    )

    # If Origin or Referer is present, it is the source of truth.
    # An explicit disallowed Origin must be rejected — the Host header is the
    # destination, not the source, and on Cloud Run it always matches *.run.app
    # regardless of who sent the request, so falling back to Host here would
    # defeat origin enforcement entirely.
    if origin or referer:
        if is_allowed_origin(origin, referer):
            logger.debug("Request allowed via origin/referer check")
            return True
        logger.warning(
            f"Request blocked (disallowed origin/referer): "
            f"origin={origin}, referer={referer}, host={host}, method={method}"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Origin not allowed. This API is only accessible from the UI.",
        )

    # No Origin and no Referer — typical for same-origin GETs which omit
    # Origin by browser design. Fall back to Host (destination) matching.
    if host:
        allowed_origins = get_allowed_origins()

        # Check if Host matches any allowed origin (localhost:5173, 127.0.0.1:5173, etc.)
        for allowed in allowed_origins:
            # Extract host:port from allowed origin (e.g., "localhost:5173")
            allowed_host = "/".join(allowed.split("/")[2:])  # Get everything after "http://"
            if host == allowed_host:
                logger.debug(f"Request allowed via host match: {host}")
                return True

        # Check if Host matches Cloud Run domain pattern (*.run.app)
        if re.match(r".+\.run\.app$", host):
            logger.debug(f"Request allowed via Cloud Run pattern: {host}")
            return True

    logger.warning(
        f"Request blocked: origin={origin}, referer={referer}, host={host}, method={method}"
    )
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Origin not allowed. This API is only accessible from the UI.",
    )


async def verify_websocket_origin(websocket: WebSocket) -> bool:
    """
    Verify WebSocket connection is from the same origin.

    WebSocket connections always include Origin header (unlike same-origin GET requests),
    but we also check Referer as a fallback for robustness.

    Args:
        websocket: FastAPI WebSocket object

    Returns:
        True if connection is from allowed origin, False if connection was closed
    """
    origin = websocket.headers.get("origin")
    referer = websocket.headers.get("referer")

    if not is_allowed_origin(origin, referer):
        await websocket.close(
            code=4003, reason="Origin not allowed. This API is only accessible from the UI."
        )
        return False

    return True
