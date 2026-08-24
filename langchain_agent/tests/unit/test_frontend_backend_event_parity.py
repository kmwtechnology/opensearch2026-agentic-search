"""Pre-flight guard: every backend event-type Literal must be declared in
the frontend TypeScript event union.

Catches drift like the 2026-04-29 review finding: backend rename of
`ConnectionError` -> `ConnectionErrorEvent` left the union including
the Python builtin, and would have only surfaced at runtime when a
ConnectionErrorEvent was emitted.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
EVENTS_PY = REPO_ROOT / "api" / "schemas" / "events.py"
EVENTS_TS = REPO_ROOT / "web" / "src" / "types" / "events.ts"

PY_LITERAL = re.compile(r"""type:\s*Literal\[\s*["']([a-z_]+)["']\s*\]""")
TS_LITERAL = re.compile(r"""type:\s*['"]([a-z_]+)['"]""")
PY_NODE_LITERAL = re.compile(r"""\bnode:\s*Literal\[\s*["']([a-z_]+)["']\s*\]""")
TS_NODE_LITERAL = re.compile(r"""\bnode:\s*['"]([a-z_]+)['"]""")


@pytest.mark.unit
def test_backend_event_types_exist_in_frontend() -> None:
    py_types = set(PY_LITERAL.findall(EVENTS_PY.read_text()))
    ts_types = set(TS_LITERAL.findall(EVENTS_TS.read_text()))

    assert py_types, "events.py exposes no `type: Literal[...]` declarations"
    assert ts_types, "events.ts exposes no `type: '...'` declarations"

    missing_in_ts = py_types - ts_types
    assert not missing_in_ts, (
        "Backend event types declared in api/schemas/events.py but missing "
        f"from web/src/types/events.ts: {sorted(missing_in_ts)}. Frontend "
        "will silently drop these events."
    )


@pytest.mark.unit
def test_no_python_builtin_in_event_union() -> None:
    """Catch unions that reference Python builtins instead of the renamed
    *Event class — e.g. `| ConnectionError` (builtin) vs
    `| ConnectionErrorEvent` (our class).
    """
    src = EVENTS_PY.read_text()
    union_match = re.search(r"AgentEvent\s*=\s*\(([^)]+)\)", src, re.DOTALL)
    assert union_match, "AgentEvent union not found in events.py"

    union_body = union_match.group(1)
    members = [m.strip().lstrip("|").strip() for m in union_body.split("\n") if m.strip()]
    builtins = {"ConnectionError", "Exception", "BaseException", "ValueError", "TypeError"}
    offenders = [m for m in members if m in builtins]
    assert not offenders, (
        "AgentEvent union references Python builtins instead of *Event classes: "
        f"{offenders}. Pydantic would silently accept any object of these types."
    )


@pytest.mark.unit
def test_event_node_names_match_between_backend_and_frontend() -> None:
    """Per-event-type, the backend `node: Literal[...]` must equal the
    frontend `node: '...'` value. Mismatches mean events route to the wrong
    UI panel — see HybridSearchResultEvent.node ('tools' vs 'retriever')
    found in the 2026-04-29 review.
    """
    py_src = EVENTS_PY.read_text()
    ts_src = EVENTS_TS.read_text()

    py_class_re = re.compile(r"class\s+(\w+)\s*\(BaseEvent\)\s*:.*?(?=\nclass\s+\w+|\Z)", re.DOTALL)
    ts_iface_re = re.compile(
        r"export\s+interface\s+(\w+)\s+extends\s+BaseEvent\s*\{(.*?)\n\}", re.DOTALL
    )

    py_nodes: dict[str, str] = {}
    for m in py_class_re.finditer(py_src):
        cls = m.group(1)
        body = m.group(0)
        n = PY_NODE_LITERAL.search(body)
        if n:
            py_nodes[cls] = n.group(1)

    ts_nodes: dict[str, str] = {}
    for m in ts_iface_re.finditer(ts_src):
        cls = m.group(1)
        body = m.group(2)
        n = TS_NODE_LITERAL.search(body)
        if n:
            ts_nodes[cls] = n.group(1)

    mismatches = [
        (cls, py_nodes[cls], ts_nodes[cls])
        for cls in py_nodes
        if cls in ts_nodes and py_nodes[cls] != ts_nodes[cls]
    ]
    assert not mismatches, (
        "Per-event `node:` literal mismatches between backend and frontend: "
        f"{mismatches}. Frontend will route these events to the wrong panel."
    )
