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

import asyncio
import json
import os
import time
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
