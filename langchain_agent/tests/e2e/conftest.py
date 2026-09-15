"""Shared helpers for e2e tests against a live deployment.

Routes are same-origin-only (no login gate). This module exposes:

* ``auth_ws_headers()``  — dict to pass as ``additional_headers`` on
  ``websockets.asyncio.client.connect``.
* ``auth_rest_headers()`` — dict to pass as ``headers`` on httpx requests
  hitting protected REST routes.

Both just carry the Origin header; the names are kept (rather than renamed
to e.g. ``origin_headers``) so the many call sites across this test suite
didn't need touching.

Env vars consumed:
* ``CLOUD_RUN_URL`` — base URL of the deployment under test (defaults to
  http://localhost:8000 for local iteration).
"""

from __future__ import annotations

import os
from typing import Optional

DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
ORIGIN_HEADER = DEPLOYMENT_URL


def auth_ws_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Headers for ``websockets.asyncio.client.connect``: Origin only."""
    headers = {"Origin": ORIGIN_HEADER}
    if extra:
        headers.update(extra)
    return headers


def auth_rest_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Headers for httpx calls to protected REST routes: Origin only."""
    headers = {"Origin": ORIGIN_HEADER}
    if extra:
        headers.update(extra)
    return headers
