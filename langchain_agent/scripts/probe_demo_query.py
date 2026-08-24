#!/usr/bin/env python3
"""Probe one chat query against the local backend and dump every event.

Standalone diagnostic — does NOT use pytest. Drive directly:

    PYTHONPATH=. .venv/bin/python scripts/probe_demo_query.py "gift ideas for hair dresser"
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import uuid
from typing import Any

import httpx
import websockets.asyncio.client as ws_client

URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
PASSWORD = os.environ.get("LOGIN_PASSWORD")


async def login() -> str:
    if not PASSWORD:
        raise SystemExit("LOGIN_PASSWORD env var unset")
    async with httpx.AsyncClient(timeout=30) as c:
        r = await c.post(
            f"{URL}/api/auth/login",
            json={"password": PASSWORD},
            headers={"Origin": URL},
        )
        r.raise_for_status()
        cookie = r.headers["set-cookie"].split(";", 1)[0]
        return cookie


async def probe(message: str, second_message: str | None = None) -> None:
    cookie = await login()
    headers = {"Origin": URL, "Cookie": cookie}
    ws_url = URL.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat"
    thread = f"probe-{uuid.uuid4().hex[:8]}"
    print(f"[connect] {ws_url} thread={thread}")
    async with ws_client.connect(ws_url, additional_headers=headers) as ws:
        print("[recv welcome]")
        # Drain until connection_established
        deadline = asyncio.get_event_loop().time() + 10
        while True:
            r = await asyncio.wait_for(
                ws.recv(), timeout=deadline - asyncio.get_event_loop().time()
            )
            evt = json.loads(r)
            print(
                f"  EVENT: {evt.get('type')} {json.dumps({k: v for k, v in evt.items() if k != 'type'})[:200]}"
            )
            if evt.get("type") == "connection_established":
                break

        for idx, msg in enumerate(filter(None, [message, second_message]), 1):
            print(f"\n[turn {idx}] sending: {msg!r}")
            await ws.send(json.dumps({"type": "chat_message", "message": msg, "thread_id": thread}))
            t0 = asyncio.get_event_loop().time()
            saw_complete = False
            while asyncio.get_event_loop().time() - t0 < 120:
                try:
                    r = await asyncio.wait_for(
                        ws.recv(), timeout=120 - (asyncio.get_event_loop().time() - t0)
                    )
                except asyncio.TimeoutError:
                    print("  [timeout]")
                    break
                evt = json.loads(r)
                t = evt.get("type")
                # Truncate long fields
                summary = {
                    k: (str(v)[:120] if isinstance(v, (str, list, dict)) else v)
                    for k, v in evt.items()
                    if k != "type"
                }
                print(
                    f"  EVENT [{(asyncio.get_event_loop().time()-t0):.1f}s]: {t} {json.dumps(summary)[:300]}"
                )
                if t == "agent_error":
                    print(f"  >>> AGENT_ERROR detail: {json.dumps(evt, indent=2)[:1500]}")
                if t == "agent_complete":
                    saw_complete = True
                    break
            print(f"[turn {idx} done, complete={saw_complete}]")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <message> [second_message]")
        sys.exit(1)
    asyncio.run(probe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None))
