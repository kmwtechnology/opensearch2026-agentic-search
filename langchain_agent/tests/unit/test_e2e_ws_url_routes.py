"""Pre-flight guard: every WebSocket URL referenced in tests/e2e/ must resolve
to a real route on the FastAPI app.

This catches the failure mode from PR-deploy 25118230913, where e2e smoke tests
hit `/ws/chat/{thread_id}` (path-style) while the actual route is
`/ws/chat?thread_id=...` (query-style). Cloud Run/Starlette returns HTTP 403
for an unmatched WS path, which we previously only discovered against live
Cloud Run. Now it fails locally in `make ci`.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent.parent / "e2e"
WS_URL_PATTERN = re.compile(r"""(/ws/[A-Za-z0-9_/{}\-]*)""")


def _registered_ws_paths() -> set[str]:
    from api.main import app

    paths: set[str] = set()

    def walk(routes) -> None:
        for route in routes:
            if "WebSocketRoute" in route.__class__.__name__:
                paths.add(route.path)
            inner = getattr(route, "routes", None)
            if inner:
                walk(inner)

    walk(app.routes)
    return paths


@pytest.mark.unit
def test_e2e_websocket_urls_match_registered_routes() -> None:
    registered = _registered_ws_paths()
    assert registered, "FastAPI app exposes no WebSocket routes — sanity check failed"

    offenders: list[tuple[str, str]] = []
    for py_file in E2E_DIR.rglob("*.py"):
        text = py_file.read_text()
        for match in WS_URL_PATTERN.finditer(text):
            url_path = match.group(1)
            # Strip trailing /{var} segments — those would indicate path params.
            # Compare the literal prefix against registered routes; flag any
            # url whose literal segment isn't a registered route.
            literal = url_path.rstrip("/")
            if literal not in registered:
                offenders.append((str(py_file.relative_to(E2E_DIR.parent.parent)), literal))

    assert not offenders, (
        "e2e tests reference WebSocket paths that aren't registered on the FastAPI app. "
        f"Registered: {sorted(registered)}. Offenders: {offenders}"
    )
