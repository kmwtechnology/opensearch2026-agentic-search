"""
X-Admin-Token authentication for unattended automation (e.g. CI) hitting
admin routes directly, without a browser session.

Independent of the (removed) shared-password login gate. Layered with
``origin_auth.verify_same_origin`` wherever it's used.
"""

import hmac
import logging
import os

from fastapi import HTTPException, Request, status

from api.middleware.client_ip import get_client_ip

logger = logging.getLogger(__name__)


async def verify_admin_token(request: Request) -> bool:
    """Verify X-Admin-Token header for admin routes (GitHub Actions, etc.).

    Token is compared via hmac.compare_digest to prevent timing attacks.

    Raises 401 if token is invalid or missing.
    Returns True on success.
    """
    admin_token = os.environ.get("ADMIN_TOKEN", "")
    if not admin_token:
        logger.warning("admin_token_check_skipped", extra={"reason": "ADMIN_TOKEN not configured"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Admin token not configured on server.",
        )

    provided_token = request.headers.get("X-Admin-Token", "")
    if not provided_token:
        logger.info(
            "admin_token_missing",
            extra={
                "path": request.url.path,
                "client": get_client_ip(request),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="X-Admin-Token header required.",
        )

    if not hmac.compare_digest(provided_token, admin_token):
        logger.warning(
            "admin_token_invalid",
            extra={
                "path": request.url.path,
                "client": get_client_ip(request),
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid admin token.",
        )

    return True
