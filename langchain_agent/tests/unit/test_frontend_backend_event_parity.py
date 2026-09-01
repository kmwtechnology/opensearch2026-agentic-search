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

# [a-z0-9_]+, not [a-z_]+: an event type name containing a digit (e.g. a
# future "phase2_something") silently dropped out of the match entirely
# under the old character class, making the assertion below pass vacuously
# for that type instead of comparing it.
PY_LITERAL = re.compile(r"""type:\s*Literal\[\s*["']([a-z0-9_]+)["']\s*\]""")
TS_LITERAL = re.compile(r"""type:\s*['"]([a-z0-9_]+)['"]""")
PY_NODE_LITERAL = re.compile(r"""\bnode:\s*Literal\[\s*["']([a-z0-9_]+)["']\s*\]""")
TS_NODE_LITERAL = re.compile(r"""\bnode:\s*['"]([a-z0-9_]+)['"]""")


@pytest.mark.unit
def test_backend_event_types_exist_in_frontend() -> None:
    """Symmetric: a type declared on only one side is drift either way.

    The original version of this test only checked py_types - ts_types
    (backend type with no frontend counterpart). A frontend-only type is
    just as real a bug -- e.g. a TS event the backend never actually emits,
    or a rename applied to one side and not the other -- so it's checked
    both directions.
    """
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

    missing_in_py = ts_types - py_types
    assert not missing_in_py, (
        "Frontend event types declared in web/src/types/events.ts but missing "
        f"from api/schemas/events.py: {sorted(missing_in_py)}. Either dead "
        "frontend code or the backend stopped emitting these."
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

    # A class with a `node:` literal on only one side was previously skipped
    # entirely by the comparison below (`if cls in ts_nodes`) -- silently, no
    # assertion ever ran for it. That's drift too: a renamed class, or one
    # side adding/removing `node:` without the other, both go undetected.
    py_only = set(py_nodes) - set(ts_nodes)
    ts_only = set(ts_nodes) - set(py_nodes)
    assert not py_only, (
        "Backend event classes declare a `node:` literal with no matching "
        f"frontend interface: {sorted(py_only)}."
    )
    assert not ts_only, (
        "Frontend event interfaces declare a `node:` literal with no matching "
        f"backend class: {sorted(ts_only)}."
    )

    mismatches = [
        (cls, py_nodes[cls], ts_nodes[cls])
        for cls in py_nodes
        if cls in ts_nodes and py_nodes[cls] != ts_nodes[cls]
    ]
    assert not mismatches, (
        "Per-event `node:` literal mismatches between backend and frontend: "
        f"{mismatches}. Frontend will route these events to the wrong panel."
    )


@pytest.mark.unit
def test_shared_model_fields_match_between_backend_and_frontend() -> None:
    """Field-level parity for every Python/TypeScript class pair that shares
    a name -- not just event types, but nested models referenced by events
    (e.g. `RerankedDocument`, embedded in `RerankerResultEvent`).

    The three tests above only ever compared `type:`/`node:` *literal
    values* -- they never looked at a class's other fields at all. That's
    exactly how the #27 drift shipped: the frontend `RerankedDocument`
    interface grew `vector_score`/`text_score`/`rrf_score`/`page_content`
    fields the backend Pydantic model never had, silently breaking the
    score chips in the UI (they read fields that were always undefined).
    """
    py_src = EVENTS_PY.read_text()
    ts_src = EVENTS_TS.read_text()

    py_class_re = re.compile(
        r"^class\s+(\w+)\s*\([^)]*\)\s*:(.*?)(?=^class\s+\w+|\Z)", re.DOTALL | re.MULTILINE
    )
    # [ \t]* here, never \s*: \s matches newlines, so a bare \s* between the
    # colon and the next non-space character would happily skip over a blank
    # line (or the rest of a docstring line) onto the FIRST WORD OF THE NEXT
    # LINE and count it as this field's type -- and if that next line is
    # itself indented 4 spaces (e.g. a docstring's "Fields:" block), its
    # first word gets misread as an unrelated field of the class entirely.
    py_field_re = re.compile(r"^    (\w+)[ \t]*:[ \t]*\S", re.MULTILINE)

    ts_iface_re = re.compile(
        r"export\s+interface\s+(\w+)\s*(?:extends\s+\w+\s*)?\{(.*?)\n\}", re.DOTALL
    )
    ts_field_re = re.compile(r"^\s{2}(\w+)\??\s*:", re.MULTILINE)

    py_classes: dict[str, set[str]] = {
        m.group(1): set(py_field_re.findall(m.group(2))) for m in py_class_re.finditer(py_src)
    }
    ts_classes: dict[str, set[str]] = {
        m.group(1): set(ts_field_re.findall(m.group(2))) for m in ts_iface_re.finditer(ts_src)
    }

    # Only classes present (by name) on both sides -- a class that's
    # intentionally one-sided (a frontend-only UI helper type, say) is out
    # of scope here; that's a naming/existence question the tests above
    # already cover for the event types that matter.
    shared = set(py_classes) & set(ts_classes)
    assert shared, "No Python/TypeScript class names matched at all -- regex likely broken"

    # KNOWN, tracked drift -- not silenced, scoped. #27 already covers
    # RerankedDocument's 4 TS-only score/content fields as its own finding
    # ("wire the fields on the backend or delete the dead UI" -- a product
    # decision this test isn't the place to make). Everything else is fully
    # enforced; remove this entry when #27 lands.
    KNOWN_DRIFT = {
        "RerankedDocument": {
            "ts_only": ["page_content", "rrf_score", "text_score", "vector_score"],
            "py_only": [],
        },
    }

    drift = {}
    for cls in sorted(shared):
        extra_in_ts = ts_classes[cls] - py_classes[cls]
        extra_in_py = py_classes[cls] - ts_classes[cls]
        if cls in KNOWN_DRIFT:
            extra_in_ts -= set(KNOWN_DRIFT[cls]["ts_only"])
            extra_in_py -= set(KNOWN_DRIFT[cls]["py_only"])
        if extra_in_ts or extra_in_py:
            drift[cls] = {"ts_only": sorted(extra_in_ts), "py_only": sorted(extra_in_py)}

    assert not drift, (
        "Field-level drift between same-named Python/TypeScript classes in "
        f"events.py / events.ts: {drift}. A ts_only field reads as `undefined` "
        "in the UI forever; a py_only field is either dead or the frontend "
        "never displays it."
    )
