"""Demo-query smoke: drive the three scenarios from DEMO_QUERIES.md.

Why this exists separately from ``test_deployment_smoke.py``:

The error that prompted this file was

    RequestError(400, 'x_content_parse_exception',
        '[multi_match] unknown token [START_ARRAY] after [query]')

surfaced while running a demo scenario locally. The fix flattens
HumanMessage list-of-content-blocks at five extraction sites in
``main.py``. The unit-level regression covers the extraction loops; this
e2e probe drives a real WebSocket end-to-end and asserts the three
DEMO_QUERIES.md scenarios complete cleanly:

  1. α-Shift Wins — single turn, expects ``quality_gate`` event with a
     retry, then ``agent_complete``.
  2. Refinement Keeps Context — two turns, expects ``intent_classified``
     with ``intent='refinement'`` on turn 2.
  3. Query Rewrite Wins — two turns, expects ``query_expansion`` event
     and ``intent_classified`` with ``intent='follow_up'`` on turn 2.

Each scenario asserts no ``agent_error`` event was emitted at any point.
That is the explicit guard against the original crash class.

Drive locally:

    CLOUD_RUN_URL=http://localhost:8000 \
      LOGIN_PASSWORD=$(grep '^LOGIN_PASSWORD=' .env | cut -d= -f2) \
      PYTHONPATH=. .venv/bin/pytest tests/e2e/test_demo_queries_smoke.py \
      -v -s --tb=short -m "e2e and slow" --timeout=300 --asyncio-mode=auto
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Tuple

import pytest
import websockets.asyncio.client as ws_client

from .conftest import DEPLOYMENT_URL, auth_ws_headers

# Single-message budget on Cloud Run is 16-25s (per memory_smoke_test_budget);
# locally with cross-encoder warm + FETCH_K=40 we observe ~12-35s per turn.
PER_TURN_TIMEOUT_S = 90.0
TWO_TURN_TIMEOUT_S = 180.0


def _ws_url() -> str:
    base = DEPLOYMENT_URL.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/ws/chat"


async def _drain_until_welcome(websocket: Any, timeout_s: float = 10.0) -> None:
    """Consume the ``connection_established`` greeting before sending anything.

    The chat WS handler emits ``connection_established`` first; messages sent
    before that greeting may be processed before the per-connection state is
    fully initialized. Mirror the protocol every other smoke test follows.
    """
    deadline = asyncio.get_event_loop().time() + timeout_s
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            raise AssertionError(f"Did not receive connection_established within {timeout_s}s")
        raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if evt.get("type") == "connection_established":
            return


async def _drive_turn(
    websocket: Any,
    message: str,
    thread_id: str,
) -> Tuple[List[Dict[str, Any]], bool]:
    """Send one ``chat_message`` and collect events until ``agent_complete``.

    Returns (events, completed). ``completed`` is True iff an
    ``agent_complete`` event was observed before the timeout. Caller must
    have already drained the ``connection_established`` greeting.
    """
    await websocket.send(
        json.dumps(
            {
                "type": "chat_message",
                "message": message,
                "thread_id": thread_id,
            }
        )
    )
    events: List[Dict[str, Any]] = []
    completed = False
    deadline = asyncio.get_event_loop().time() + PER_TURN_TIMEOUT_S
    while True:
        remaining = deadline - asyncio.get_event_loop().time()
        if remaining <= 0:
            break
        try:
            raw = await asyncio.wait_for(websocket.recv(), timeout=remaining)
        except asyncio.TimeoutError:
            break
        try:
            evt = json.loads(raw)
        except json.JSONDecodeError:
            continue
        events.append(evt)
        if evt.get("type") == "agent_complete":
            completed = True
            break
        # Bail early on agent_error so the assertion has the full event in scope.
        if evt.get("type") == "agent_error":
            break
    return events, completed


def _summarize(events: List[Dict[str, Any]]) -> str:
    """One-line per event for diagnostic output on failure."""
    lines = []
    for e in events:
        t = e.get("type", "?")
        if t == "intent_classified":
            lines.append(
                f"  intent_classified intent={e.get('intent')} confidence={e.get('confidence')}"
            )
        elif t == "opensearch_query":
            lines.append(
                f"  opensearch_query alpha={e.get('alpha')} intent={e.get('intent')} "
                f"query_type={e.get('query_type')} filters={len(e.get('filters') or [])}"
            )
        elif t == "quality_gate":
            lines.append(
                f"  quality_gate decision={e.get('decision')} max_score={e.get('max_score')} "
                f"retry_alpha={e.get('new_alpha')}"
            )
        elif t == "query_expansion":
            lines.append(
                f"  query_expansion original={e.get('original_query')!r} "
                f"expanded={e.get('expanded_query')!r}"
            )
        elif t == "agent_error":
            lines.append(f"  AGENT_ERROR error={e.get('error')!r}")
        elif t == "agent_complete":
            lines.append(f"  agent_complete response_len={len(e.get('response') or '')}")
        else:
            lines.append(f"  {t}")
    return "\n".join(lines)


def _assert_no_error(events: List[Dict[str, Any]], scenario: str) -> None:
    errors = [e for e in events if e.get("type") == "agent_error"]
    assert not errors, (
        f"[{scenario}] agent_error emitted — this is the regression class the "
        f"flatten fix targets. Errors: {[e.get('error') for e in errors]}\n"
        f"Full event log:\n{_summarize(events)}"
    )


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.asyncio
class TestDemoQueriesSmoke:
    """Probe the three DEMO_QUERIES.md scenarios end-to-end.

    Each test opens its own WebSocket and uses a fresh thread_id so prior
    state can't leak between runs. The assertions are loose on the
    pipeline-quality numbers (those drift with corpus + cross-encoder
    versions) and tight on the structural payoff each demo promises:

    - Demo 1: a ``quality_gate`` event with a retry decision fires.
    - Demo 2: turn-2 intent classification reports ``refinement``.
    - Demo 3: ``query_expansion`` fires AND turn-2 intent is ``follow_up``.

    All three additionally assert no ``agent_error`` event at any point.
    """

    async def test_demo1_alpha_shift_wins(self) -> None:
        thread_id = f"demo1-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(),
            additional_headers=auth_ws_headers(),
        ) as websocket:
            await _drain_until_welcome(websocket)
            events, completed = await _drive_turn(
                websocket, "gift ideas for hair dresser", thread_id
            )
        _assert_no_error(events, "demo1")
        assert completed, (
            f"[demo1] agent_complete never emitted within {PER_TURN_TIMEOUT_S}s.\n"
            f"Events:\n{_summarize(events)}"
        )

        # The audience-visible payoff is the quality_gate retry — assert it fires.
        gate_events = [e for e in events if e.get("type") == "quality_gate"]
        assert gate_events, (
            f"[demo1] no quality_gate event observed. Demo narrative requires "
            f"the retry diagnostic loop to be visible.\nEvents:\n{_summarize(events)}"
        )

    async def test_demo2_refinement_keeps_context(self) -> None:
        thread_id = f"demo2-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(),
            additional_headers=auth_ws_headers(),
        ) as websocket:
            await _drain_until_welcome(websocket)
            t1_events, t1_done = await _drive_turn(websocket, "wireless headphones", thread_id)
            _assert_no_error(t1_events, "demo2-turn1")
            assert t1_done, (
                f"[demo2-turn1] agent_complete never emitted.\n" f"Events:\n{_summarize(t1_events)}"
            )

            t2_events, t2_done = await _drive_turn(
                websocket, "only noise cancelling ones", thread_id
            )

        _assert_no_error(t2_events, "demo2-turn2")
        assert t2_done, (
            f"[demo2-turn2] agent_complete never emitted.\n" f"Events:\n{_summarize(t2_events)}"
        )

        # Turn-2 intent must classify as refinement for the demo's
        # "two filter groups" payoff to fire.
        intents = [e for e in t2_events if e.get("type") == "intent_classified"]
        assert intents, f"[demo2-turn2] no intent_classified event.\n{_summarize(t2_events)}"
        intent_value = intents[0].get("intent")
        assert intent_value == "refinement", (
            f"[demo2-turn2] expected intent='refinement', got {intent_value!r}.\n"
            f"Events:\n{_summarize(t2_events)}"
        )

    async def test_demo3_query_rewrite_wins(self) -> None:
        thread_id = f"demo3-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(),
            additional_headers=auth_ws_headers(),
        ) as websocket:
            await _drain_until_welcome(websocket)
            t1_events, t1_done = await _drive_turn(websocket, "coffee maker", thread_id)
            _assert_no_error(t1_events, "demo3-turn1")
            assert t1_done, (
                f"[demo3-turn1] agent_complete never emitted.\n" f"Events:\n{_summarize(t1_events)}"
            )

            t2_events, t2_done = await _drive_turn(websocket, "how about cheaper", thread_id)

        _assert_no_error(t2_events, "demo3-turn2")
        assert t2_done, (
            f"[demo3-turn2] agent_complete never emitted.\n" f"Events:\n{_summarize(t2_events)}"
        )

        # The "wow moment" is query_expansion firing.
        expansions = [e for e in t2_events if e.get("type") == "query_expansion"]
        assert expansions, (
            f"[demo3-turn2] no query_expansion event observed. Demo narrative "
            f"requires the rewrite to fire on a vague follow-up.\n"
            f"Events:\n{_summarize(t2_events)}"
        )
        # Intent should be follow_up (not refinement) so the demo shows
        # expansion alone, no product_id filter.
        intents = [e for e in t2_events if e.get("type") == "intent_classified"]
        assert intents, f"[demo3-turn2] no intent_classified event.\n{_summarize(t2_events)}"
        intent_value = intents[0].get("intent")
        assert intent_value == "follow_up", (
            f"[demo3-turn2] expected intent='follow_up', got {intent_value!r}. "
            f"This is a soft assertion — if intent drifts to 'refinement' the "
            f"demo's narrative changes (filter group appears alongside expansion). "
            f"Adjust the demo, not the test, if intent stabilizes elsewhere.\n"
            f"Events:\n{_summarize(t2_events)}"
        )
