"""Shared helpers for e2e tests against a live backend.

Every route is same-origin-only, so both helpers return just the Origin header:
``auth_ws_headers()`` for ``websockets.asyncio.client.connect`` and
``auth_rest_headers()`` for httpx.

``DEPLOYMENT_URL`` defaults to http://localhost:8080, the native `make dev` backend
(:8000 is the demo container's image, frozen at the last `make dev`).
"""

from __future__ import annotations

import os

DEPLOYMENT_URL = os.environ.get("DEPLOYMENT_URL", "http://localhost:8080")
ORIGIN_HEADER = DEPLOYMENT_URL


def auth_ws_headers() -> dict[str, str]:
    return {"Origin": ORIGIN_HEADER}


auth_rest_headers = auth_ws_headers
