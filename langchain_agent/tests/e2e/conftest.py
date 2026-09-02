"""Shared helpers for e2e tests against a live deployment.

The shared-password login gate (added 2026-04-29 on `feat/login-gate`) means
every protected REST call and every WebSocket handshake must carry a session
cookie obtained from ``POST /api/auth/login``. This module performs that
login once per pytest session and exposes:

* ``auth_ws_headers()``  — dict to pass as ``additional_headers`` on
  ``websockets.asyncio.client.connect``.
* ``auth_rest_headers()`` — dict to pass as ``headers`` on httpx requests
  hitting protected REST routes.

Env vars consumed:
* ``CLOUD_RUN_URL`` — base URL of the deployment under test (defaults to
  http://localhost:8000 for local iteration).
* ``LOGIN_PASSWORD`` — the shared password to send to /api/auth/login.
  Required when the gate is active; without it the helpers raise.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Optional

import httpx

DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
ORIGIN_HEADER = DEPLOYMENT_URL
# Login password for the gate — set in the GH Actions secret + .env locally.
LOGIN_PASSWORD = os.environ.get("LOGIN_PASSWORD")
LOGIN_TIMEOUT_S = 30

# Module-level cache populated on first successful login. Pytest runs tests
# in a single process per worker so this survives across the test session.
_AUTH_COOKIE: Optional[str] = None


def _login_and_get_cookie() -> str:
    """POST to /api/auth/login and return the ``name=value`` cookie segment.

    Raises a clear AssertionError if the deployment didn't set a cookie or
    if LOGIN_PASSWORD is unset.
    """
    if not LOGIN_PASSWORD:
        raise AssertionError(
            "LOGIN_PASSWORD env var is unset. The deployment's shared-password "
            "login gate cannot be unlocked without it. Set LOGIN_PASSWORD in "
            "the test environment."
        )

    with httpx.Client(timeout=LOGIN_TIMEOUT_S) as client:
        response = client.post(
            f"{DEPLOYMENT_URL}/api/auth/login",
            json={"password": LOGIN_PASSWORD},
            headers={"Origin": ORIGIN_HEADER},
        )

    assert response.status_code == 200, (
        f"Login failed: status={response.status_code}, body={response.text!r}. "
        f"Check LOGIN_PASSWORD against the deployment's configured password."
    )

    raw_cookie = response.headers.get("set-cookie")
    assert raw_cookie, (
        f"Login succeeded ({response.status_code}) but no Set-Cookie header was "
        "returned. SessionMiddleware may not be wired or the deployment's "
        "https_only flag may not match the test client's scheme."
    )
    # Set-Cookie may carry attributes like Path/HttpOnly/Secure/SameSite —
    # only the first segment ("name=value") is needed on subsequent requests.
    return raw_cookie.split(";", 1)[0]


def get_auth_cookie() -> str:
    """Return the cached session cookie, logging in lazily on first call."""
    global _AUTH_COOKIE
    if _AUTH_COOKIE is None:
        _AUTH_COOKIE = _login_and_get_cookie()
    return _AUTH_COOKIE


def auth_ws_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Headers for ``websockets.asyncio.client.connect``: Origin + Cookie."""
    headers = {"Origin": ORIGIN_HEADER, "Cookie": get_auth_cookie()}
    if extra:
        headers.update(extra)
    return headers


def auth_rest_headers(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Headers for httpx calls to protected REST routes: Origin + Cookie."""
    headers = {"Origin": ORIGIN_HEADER, "Cookie": get_auth_cookie()}
    if extra:
        headers.update(extra)
    return headers


async def collect_chat_response(
    websocket, timeout_s: float = 60, recv_timeout_s: float = 15
) -> str:
    """Drain a chat WebSocket until ``agent_complete`` (or the timeout) and
    return the response text.

    Prefers the streamed ``llm_response_chunk`` content, but falls back to
    ``agent_complete``'s ``final_response`` field when no chunks arrived —
    e.g. the server-side 150s graph timeout in ``ObservableAgentService``
    emits a complete event with fallback text but never streams chunks, so a
    caller that only accumulates chunks reads a real (if slow) response as
    "nothing came back". See #23.
    """
    response_text = ""
    final_response = ""
    start_time = time.time()

    while time.time() - start_time < timeout_s:
        try:
            event_msg = await asyncio.wait_for(websocket.recv(), timeout=recv_timeout_s)
            event = json.loads(event_msg)
            event_type = event.get("type")

            if event_type == "llm_response_chunk":
                response_text += event.get("content", "")
            elif event_type == "agent_complete":
                final_response = event.get("final_response", "") or ""
                break
        except asyncio.TimeoutError:
            continue

    return response_text or final_response


async def collect_chat_result(websocket, timeout_s: float = 60, recv_timeout_s: float = 15) -> dict:
    """Like ``collect_chat_response`` but keep the structured outcome too.

    Returns ``{"text": str, "completed": bool, "citations": list}`` where
    ``completed`` is whether an ``agent_complete`` event actually arrived (vs.
    the drain loop timing out) and ``citations`` is that event's citation
    list. Used by consistency checks that need something more deterministic
    than the prose length of a non-deterministic LLM response (#43).
    """
    response_text = ""
    final_response = ""
    completed = False
    citations: list = []
    start_time = time.time()

    while time.time() - start_time < timeout_s:
        try:
            event_msg = await asyncio.wait_for(websocket.recv(), timeout=recv_timeout_s)
            event = json.loads(event_msg)
            event_type = event.get("type")

            if event_type == "llm_response_chunk":
                response_text += event.get("content", "")
            elif event_type == "agent_complete":
                final_response = event.get("final_response", "") or ""
                citations = event.get("citations") or []
                completed = True
                break
        except asyncio.TimeoutError:
            continue

    return {
        "text": response_text or final_response,
        "completed": completed,
        "citations": citations,
    }
