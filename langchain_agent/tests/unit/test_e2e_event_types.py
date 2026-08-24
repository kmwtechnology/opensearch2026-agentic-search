"""Pre-flight guard: every event-type literal compared against in tests/e2e/
must be a real `type: Literal[...]` value declared in api/schemas/events.py.

Catches the failure mode from the 2026-04-29 smoke run, where e2e tests
asserted `event.get("event_type") == "AgentCompleteEvent"` (CamelCase
class-name style) while the wire protocol uses `event["type"] ==
"agent_complete"` (snake_case discriminator). HTTP 200 / no error, just
silent skip-of-every-event → empty responses → cascading failures.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

E2E_DIR = Path(__file__).resolve().parent.parent / "e2e"

# Match `event.get("type") == "X"` and `event["type"] == "X"`.
EVENT_TYPE_COMPARE = re.compile(
    r"""(?:event\.get\(\s*["']type["']\s*\)|event\[\s*["']type["']\s*\])"""
    r"""\s*==\s*["']([A-Za-z_][A-Za-z0-9_]*)["']"""
)
# The wire field is `type`, not `event_type`. Catch the wrong field name.
WRONG_FIELD = re.compile(
    r"""event\.get\(\s*["']event_type["']\s*\)|event\[\s*["']event_type["']\s*\]"""
)


def _registered_event_types() -> set[str]:
    from api.schemas import events as events_module

    literals: set[str] = set()
    pattern = re.compile(r'type:\s*Literal\[\s*["\']([a-z_]+)["\']\s*\]\s*=\s*["\']\1["\']')
    src = Path(events_module.__file__).read_text()
    for match in pattern.finditer(src):
        literals.add(match.group(1))
    return literals


@pytest.mark.unit
def test_e2e_event_type_literals_match_schema() -> None:
    registered = _registered_event_types()
    assert registered, "events.py exposes no `type: Literal[...]` declarations"

    offenders: list[tuple[str, str]] = []
    wrong_field: list[str] = []
    for py_file in E2E_DIR.rglob("*.py"):
        text = py_file.read_text()
        rel = str(py_file.relative_to(E2E_DIR.parent.parent))
        for match in EVENT_TYPE_COMPARE.finditer(text):
            literal = match.group(1)
            if literal not in registered:
                offenders.append((rel, literal))
        if WRONG_FIELD.search(text):
            wrong_field.append(rel)

    assert not wrong_field, (
        "e2e tests access `event['event_type']` — the wire protocol uses "
        f"`event['type']`. Files: {wrong_field}"
    )
    assert not offenders, (
        "e2e tests compare event['type'] against literals that aren't declared "
        f"in api/schemas/events.py. Registered: {sorted(registered)}. "
        f"Offenders: {offenders}"
    )
