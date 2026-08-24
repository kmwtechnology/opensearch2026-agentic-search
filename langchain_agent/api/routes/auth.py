"""
Authentication routes for the shared-password login gate.

Three endpoints, all under ``/api/auth``:
* ``POST /login`` — validates a typed password against ``LOGIN_PASSWORD`` and
  marks the session authenticated. Rate-limited per IP to slow brute force.
* ``POST /logout`` — clears the session.
* ``GET /status`` — reports whether the current session is authenticated, so
  the SPA can decide whether to render the login screen or the chat UI.

Origin auth (``origin_auth.verify_same_origin``) is layered on every route to
match the rest of the API; ``status`` and ``logout`` are intentionally
callable without an existing session so a fresh page load can probe them.
"""

import hmac
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, status
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address

# Add parent directory to path for config import
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from api.middleware.origin_auth import verify_same_origin
from config import LOGIN_PASSWORD, RATE_LIMIT_LOGIN
from logging_config import get_logger

logger = get_logger(__name__)

# A separate Limiter instance keeps login throttling self-contained; slowapi
# allows multiple Limiters on one app as long as the global one in main.py
# owns the exception handler.
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


class LoginRequest(BaseModel):
    password: str = Field(
        min_length=1,
        max_length=512,
        description="Shared password matching the LOGIN_PASSWORD env var.",
    )


class LoginResponse(BaseModel):
    authenticated: bool


class StatusResponse(BaseModel):
    authenticated: bool


@router.post("/auth/login", response_model=LoginResponse)
@limiter.limit(RATE_LIMIT_LOGIN)
async def login(request: Request, body: LoginRequest):
    """Validate the shared password and mark the session authenticated.

    Returns 401 on mismatch (with the same delay characteristics as the
    success path — ``compare_digest`` is constant-time relative to length).
    Returns 503 if the server is misconfigured (no ``LOGIN_PASSWORD`` set).
    """
    await verify_same_origin(request)

    if not LOGIN_PASSWORD:
        logger.error("login_misconfigured", extra={"reason": "LOGIN_PASSWORD unset"})
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Login is not configured on this server.",
        )

    if not hmac.compare_digest(body.password, LOGIN_PASSWORD):
        logger.info(
            "login_failed",
            extra={"client": request.client.host if request.client else None},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid password.",
        )

    request.session["authenticated"] = True
    logger.info(
        "login_succeeded",
        extra={"client": request.client.host if request.client else None},
    )
    return LoginResponse(authenticated=True)


@router.post("/auth/logout", response_model=LoginResponse)
async def logout(request: Request):
    """Clear the session. Always succeeds (idempotent)."""
    await verify_same_origin(request)
    request.session.clear()
    return LoginResponse(authenticated=False)


@router.get("/auth/status", response_model=StatusResponse)
async def auth_status(request: Request):
    """Report whether the current session is authenticated.

    Public (origin-only). The SPA hits this on first paint to decide between
    rendering the login screen and the chat UI.
    """
    await verify_same_origin(request)
    session = getattr(request, "session", None)
    authenticated = bool(session.get("authenticated")) if session is not None else False
    return StatusResponse(authenticated=authenticated)
