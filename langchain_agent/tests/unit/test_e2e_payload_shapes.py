"""Pre-flight guard: every JSON payload sent by tests/e2e/ over WebSocket
must conform to the actual server-side message contract.

Catches the failure mode from the 2026-04-29 smoke run, where every test
sent {"query": x, "session_id": y} but the server only handles
{"type": "chat_message", "message": x, "thread_id": y}. The server
silently dropped each message, no events fired, all six smoke tests
cascaded to failure 30 minutes after deploy.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent.parent / "e2e"

# The wire contract for inbound WebSocket messages, as enforced by
# api/routes/chat.py:367 — `data.get("type") == "chat_message"` with
# fields `message` (string) and `thread_id` (string). Stop messages use
# `type=stop_execution` with `thread_id`.
INBOUND_MESSAGE_TYPES = {
    "chat_message": {"required": {"type", "message"}, "optional": {"thread_id", "optimizations"}},
    "stop_execution": {"required": {"type"}, "optional": {"thread_id"}},
}


def _extract_json_dumps_dicts(source: str) -> list[ast.Dict]:
    """Find all `json.dumps({...})` calls and return the dict-literal AST
    nodes. We only look at literal dicts — dynamic shapes are out of scope
    (and rare in tests)."""
    tree = ast.parse(source)
    dicts: list[ast.Dict] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "json"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            dicts.append(node.args[0])
    return dicts


def _string_keys(d: ast.Dict) -> set[str]:
    keys: set[str] = set()
    for k in d.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.add(k.value)
    return keys


def _string_value(d: ast.Dict, key: str) -> str | None:
    for k, v in zip(d.keys, d.values):
        if (
            isinstance(k, ast.Constant)
            and k.value == key
            and isinstance(v, ast.Constant)
            and isinstance(v.value, str)
        ):
            return v.value
    return None


@pytest.mark.unit
def test_e2e_websocket_payloads_conform_to_chat_message_contract() -> None:
    """Every json.dumps({...}) call in tests/e2e/ that includes a `type`
    key must use a known inbound message type and supply its required
    fields. A payload missing `type` is also flagged — the server will
    silently drop it."""
    offenders: list[tuple[str, int, str]] = []

    for py_file in E2E_DIR.rglob("*.py"):
        text = py_file.read_text()
        rel = str(py_file.relative_to(E2E_DIR.parent.parent))
        for d in _extract_json_dumps_dicts(text):
            keys = _string_keys(d)
            # Heuristic: only flag dicts that look like WebSocket payloads
            # (sent via websocket.send near a ws_connect block). The cheapest
            # heuristic: look for the legacy `query`/`session_id` keys, OR
            # presence of `type` against known message types.
            looks_like_ws_payload = (
                ("query" in keys and "session_id" in keys) or "type" in keys or "message" in keys
            )

            if not looks_like_ws_payload:
                continue

            type_value = _string_value(d, "type")
            if type_value is None:
                offenders.append(
                    (rel, d.lineno, f"WS payload missing 'type' field; keys={sorted(keys)}")
                )
                continue
            if type_value not in INBOUND_MESSAGE_TYPES:
                offenders.append(
                    (
                        rel,
                        d.lineno,
                        f"unknown message type {type_value!r}; "
                        f"valid: {sorted(INBOUND_MESSAGE_TYPES)}",
                    )
                )
                continue
            spec = INBOUND_MESSAGE_TYPES[type_value]
            missing = spec["required"] - keys
            if missing:
                offenders.append(
                    (
                        rel,
                        d.lineno,
                        f"{type_value!r} payload missing required fields {sorted(missing)}; "
                        f"got keys={sorted(keys)}",
                    )
                )
            unknown = keys - spec["required"] - spec["optional"]
            if unknown:
                offenders.append(
                    (
                        rel,
                        d.lineno,
                        f"{type_value!r} payload has unknown fields {sorted(unknown)} "
                        "that the server will ignore — likely stale test (e.g. 'session_id' "
                        "instead of 'thread_id', 'query' instead of 'message')",
                    )
                )

    assert not offenders, (
        "e2e WebSocket payloads do not conform to the server's chat_message "
        f"contract:\n  " + "\n  ".join(f"{f}:{ln} {msg}" for f, ln, msg in offenders)
    )


@pytest.mark.unit
def test_inbound_message_types_match_server_handler() -> None:
    """The handler in api/routes/chat.py is the source of truth. If a new
    message `type` is added there, this test's INBOUND_MESSAGE_TYPES must
    track it — otherwise we lose contract enforcement.
    """
    chat_py = E2E_DIR.parent.parent / "api" / "routes" / "chat.py"
    src = chat_py.read_text()
    handled = set(re.findall(r'data\.get\(\s*["\']type["\']\s*\)\s*==\s*["\'](\w+)["\']', src))
    assert handled, "chat.py handler exposes no `data.get('type') == ...` checks"

    untracked = handled - INBOUND_MESSAGE_TYPES.keys()
    assert not untracked, (
        f"chat.py handles message types {sorted(untracked)} that aren't declared in "
        "INBOUND_MESSAGE_TYPES above. Add them so the conformance check stays accurate."
    )
