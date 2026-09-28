"""Demo-query smoke: three legacy conversation scenarios plus the four scripted demos.

Why this exists separately from ``test_deployment_smoke.py``:

The error that prompted this file was

    RequestError(400, 'x_content_parse_exception',
        '[multi_match] unknown token [START_ARRAY] after [query]')

surfaced while running a demo scenario locally. The fix flattens
HumanMessage list-of-content-blocks at five extraction sites in
``main.py``. The unit-level regression covers the extraction loops; this
e2e probe drives a real WebSocket end-to-end and asserts three legacy
scenarios (they predate the scripted demos in web/src/demos/registry.ts,
which TestScriptedDemos below drives verbatim) complete cleanly:

  1. α-Shift Wins — single turn, expects ``quality_gate`` event with a
     retry, then ``agent_complete``.
  2. Refinement Keeps Context — two turns, expects ``intent_classification``
     with ``intent='refinement'`` on turn 2.
  3. Query Rewrite Wins — two turns, expects ``query_expansion`` event
     and ``intent_classification`` with ``intent='follow_up'`` on turn 2.

Each scenario asserts no ``agent_error`` event was emitted at any point.
That is the explicit guard against the original crash class.

Drive locally:

    DEPLOYMENT_URL=http://localhost:8080 \
      PYTHONPATH=. .venv/bin/pytest tests/e2e/test_demo_queries_smoke.py \
      -v -s --tb=short -m "e2e and slow" --timeout=300 --asyncio-mode=auto
"""

from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Tuple

import httpx
import pytest
import websockets.asyncio.client as ws_client

from .conftest import DEPLOYMENT_URL, auth_rest_headers, auth_ws_headers

# Single-message budget locally (cross-encoder warm, FETCH_K=40, local Ollama
# generation) is observed at ~12-35s per turn.
PER_TURN_TIMEOUT_S = 90.0
TWO_TURN_TIMEOUT_S = 180.0
# The two self-correcting/growing demos add a scoped re-tag on top of the
# usual intent->retrieve->rerank->generate pipeline, plus a second LLM call
# to approve the enrichment tool call.
ENRICHMENT_TURN_TIMEOUT_S = 150.0


def _ws_url(thread_id: str) -> str:
    # thread_id must match what _drive_turn sends in the chat_message payload:
    # ConnectionManager.emit_event routes by the connection's registered
    # thread_id (set from this query param, or a random one if omitted), so a
    # mismatch here means every event after connection_established is
    # silently dropped -- no error, the socket just goes quiet until timeout.
    base = DEPLOYMENT_URL.replace("http://", "ws://").replace("https://", "wss://")
    return f"{base}/ws/chat?thread_id={thread_id}"


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
    timeout_s: float = PER_TURN_TIMEOUT_S,
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
    deadline = asyncio.get_event_loop().time() + timeout_s
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


async def _drain_trailing(websocket: Any, grace_s: float = 5.0) -> List[Dict[str, Any]]:
    """Collect any further events for a short grace period after
    agent_complete. Some events (e.g. pipeline_summary) are emitted after
    agent_complete, which _drive_turn stops listening for as soon as it sees."""
    events: List[Dict[str, Any]] = []
    deadline = asyncio.get_event_loop().time() + grace_s
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
    return events


def _summarize(events: List[Dict[str, Any]]) -> str:
    """One-line per event for diagnostic output on failure."""
    lines = []
    for e in events:
        t = e.get("type", "?")
        if t == "intent_classification":
            lines.append(
                f"  intent_classification intent={e.get('intent')} confidence={e.get('confidence')}"
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
        elif t == "enrichment_triggered":
            lines.append(
                f"  enrichment_triggered status={e.get('status')} "
                f"attribute_type={e.get('attribute_type')} variant={e.get('variant')!r} "
                f"canonical={e.get('canonical')!r} corrected_from={e.get('corrected_from')!r}"
            )
        elif t == "pipeline_summary":
            lines.append(f"  pipeline_summary has_ground_truth={e.get('has_ground_truth')}")
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


async def _reset_demo_taxonomy() -> None:
    """Re-arm both self-consuming demos (taxonomy-ingestion, schema-evolution)
    via the same POST /api/admin/demo-reset the UI's Restart button calls.

    Both demos destroy their own preconditions on success (see
    quality/demo_reset.py) -- this must run before each one so its first
    turn reliably reproduces the gap it exists to fix, and again after, so a
    test run doesn't leave the taxonomy mutated for whatever runs next
    (including a re-export of the precomputed index dump, which asserts
    zero waterproof mappings).
    """
    async with httpx.AsyncClient(base_url=DEPLOYMENT_URL, timeout=30.0) as client:
        response = await client.post("/api/admin/demo-reset", headers=auth_rest_headers())
        response.raise_for_status()


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.asyncio
class TestDemoQueriesSmoke:
    """Probe the three legacy conversation scenarios end-to-end.

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
            _ws_url(thread_id),
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
            _ws_url(thread_id),
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
        intents = [e for e in t2_events if e.get("type") == "intent_classification"]
        assert intents, f"[demo2-turn2] no intent_classification event.\n{_summarize(t2_events)}"
        intent_value = intents[0].get("intent")
        assert intent_value == "refinement", (
            f"[demo2-turn2] expected intent='refinement', got {intent_value!r}.\n"
            f"Events:\n{_summarize(t2_events)}"
        )

    async def test_demo3_query_rewrite_wins(self) -> None:
        thread_id = f"demo3-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(thread_id),
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
        intents = [e for e in t2_events if e.get("type") == "intent_classification"]
        assert intents, f"[demo3-turn2] no intent_classification event.\n{_summarize(t2_events)}"
        intent_value = intents[0].get("intent")
        assert intent_value == "follow_up", (
            f"[demo3-turn2] expected intent='follow_up', got {intent_value!r}. "
            f"This is a soft assertion — if intent drifts to 'refinement' the "
            f"demo's narrative changes (filter group appears alongside expansion). "
            f"Adjust the demo, not the test, if intent stabilizes elsewhere.\n"
            f"Events:\n{_summarize(t2_events)}"
        )


@pytest.mark.e2e
@pytest.mark.slow
@pytest.mark.asyncio
class TestScriptedDemos:
    """Drive the four ACTUAL scripted demos from web/src/demos/registry.ts,
    verbatim, end to end. This is separate from TestDemoQueriesSmoke above,
    which exercises the same underlying mechanisms (alpha shift, refinement,
    query rewrite) with standalone queries that predate the current scripted
    demos and are NOT the literal on-stage script.

    Query strings here must stay byte-for-byte identical to registry.ts --
    several are load-bearing in ways documented there (see each demo's
    comment block). If registry.ts changes a query, update it here too.

    Two of the four demos are self-consuming (color correction, waterproof
    growth): each destroys its own precondition on success, so a second run
    without resetting finds nothing to demonstrate. Both reset before AND
    after via /api/admin/demo-reset, so this class is safe to re-run and
    leaves the taxonomy clean for anything that runs after it (notably: the
    precomputed-dump export, which asserts zero waterproof mappings).
    """

    async def test_demo_adaptive_query_enhancements(self) -> None:
        """registry.ts id='adaptive-query'. One conversation, three turns
        that narrow. No retry turn is expected -- see registry.ts's own
        note on why no query in this arc both fires the quality gate and
        recovers inside the same conversation."""
        thread_id = f"adaptive-query-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(thread_id),
            additional_headers=auth_ws_headers(),
        ) as websocket:
            await _drain_until_welcome(websocket)

            t1_events, t1_done = await _drive_turn(
                websocket, "Show me blue running shoes", thread_id
            )
            _assert_no_error(t1_events, "adaptive-query-turn1")
            assert (
                t1_done
            ), f"[adaptive-query-turn1] agent_complete never emitted.\n{_summarize(t1_events)}"

            t2_events, t2_done = await _drive_turn(websocket, "only size 10", thread_id)
            _assert_no_error(t2_events, "adaptive-query-turn2")
            assert (
                t2_done
            ), f"[adaptive-query-turn2] agent_complete never emitted.\n{_summarize(t2_events)}"

            t3_events, t3_done = await _drive_turn(
                websocket, "what about trail running?", thread_id
            )
            _assert_no_error(t3_events, "adaptive-query-turn3")
            assert (
                t3_done
            ), f"[adaptive-query-turn3] agent_complete never emitted.\n{_summarize(t3_events)}"

        # The "wow moment" on turn 3 is the rewriter carrying both earlier
        # constraints forward into a semantic query.
        expansions = [e for e in t3_events if e.get("type") == "query_expansion"]
        assert expansions, (
            f"[adaptive-query-turn3] no query_expansion event observed -- the "
            f"vague follow-up should get rewritten with prior context.\n"
            f"Events:\n{_summarize(t3_events)}"
        )

    async def test_demo_ground_truth_proof(self) -> None:
        """registry.ts id='ground-truth-proof'. Single turn, single new
        conversation. The payoff is has_ground_truth flipping True -- this
        query is one of the few in the corpus with real ESCI judgments."""
        thread_id = f"ground-truth-proof-{uuid.uuid4().hex[:8]}"
        async with ws_client.connect(
            _ws_url(thread_id),
            additional_headers=auth_ws_headers(),
        ) as websocket:
            await _drain_until_welcome(websocket)
            events, completed = await _drive_turn(
                websocket, "headphones with microphone", thread_id
            )
            # pipeline_summary is emitted AFTER agent_complete (see
            # observable_agent.py's process_message) -- _drive_turn stops
            # collecting the instant it sees agent_complete, so keep
            # listening briefly to catch the trailing event too.
            events += await _drain_trailing(websocket)
        _assert_no_error(events, "ground-truth-proof")
        assert (
            completed
        ), f"[ground-truth-proof] agent_complete never emitted.\n{_summarize(events)}"

        summaries = [e for e in events if e.get("type") == "pipeline_summary"]
        assert summaries, f"[ground-truth-proof] no pipeline_summary event.\n{_summarize(events)}"
        assert summaries[0].get("has_ground_truth") is True, (
            f"[ground-truth-proof] expected has_ground_truth=True for this query -- "
            f"if this now fails, the corpus/judgments no longer have real ESCI "
            f"ground truth for 'headphones with microphone'; pick a new query in "
            f"registry.ts (see its long comment on how the current one was chosen) "
            f"rather than loosening this test.\n"
            f"Events:\n{_summarize(events)}"
        )

    async def test_demo_taxonomy_ingestion(self) -> None:
        """registry.ts id='taxonomy-ingestion'. Self-consuming: re-arms
        before and after. Turn 2 disputes a real shipped mis-tag (tan ->
        yellow) and triggers a live scoped re-tag (pipeline/scoped_retag.py);
        turn 3 is a NEW conversation (same-thread would rewrite the query
        down a lexical path instead of re-querying the corrected field)."""
        await _reset_demo_taxonomy()
        try:
            thread_id_1 = f"taxonomy-ingestion-{uuid.uuid4().hex[:8]}"
            async with ws_client.connect(
                _ws_url(thread_id_1),
                additional_headers=auth_ws_headers(),
            ) as websocket:
                await _drain_until_welcome(websocket)

                t1_events, t1_done = await _drive_turn(websocket, "show me tan boots", thread_id_1)
                _assert_no_error(t1_events, "taxonomy-ingestion-turn1")
                assert t1_done, (
                    f"[taxonomy-ingestion-turn1] agent_complete never emitted.\n"
                    f"{_summarize(t1_events)}"
                )

                t2_events, t2_done = await _drive_turn(
                    websocket,
                    "that's not tan, that's tagged yellow which is wrong",
                    thread_id_1,
                    timeout_s=ENRICHMENT_TURN_TIMEOUT_S,
                )
                _assert_no_error(t2_events, "taxonomy-ingestion-turn2")
                assert t2_done, (
                    f"[taxonomy-ingestion-turn2] agent_complete never emitted.\n"
                    f"{_summarize(t2_events)}"
                )

            enrichments = [e for e in t2_events if e.get("type") == "enrichment_triggered"]
            assert enrichments, (
                f"[taxonomy-ingestion-turn2] no enrichment_triggered event -- the "
                f"correction-dispute phrasing should trigger a live re-tag every "
                f"time (this is the one demo turn that isn't a soft LLM-choice "
                f"assertion; see registry.ts's note that this exact phrase 'trips "
                f"the correction detector').\nEvents:\n{_summarize(t2_events)}"
            )
            terminal = [e for e in enrichments if e.get("status") != "started"]
            assert terminal and terminal[-1].get("status") == "complete", (
                f"[taxonomy-ingestion-turn2] enrichment did not reach status=complete.\n"
                f"Events:\n{_summarize(t2_events)}"
            )

            thread_id_2 = f"taxonomy-ingestion-{uuid.uuid4().hex[:8]}"
            async with ws_client.connect(
                _ws_url(thread_id_2),
                additional_headers=auth_ws_headers(),
            ) as websocket:
                await _drain_until_welcome(websocket)
                t3_events, t3_done = await _drive_turn(websocket, "show me tan boots", thread_id_2)
            _assert_no_error(t3_events, "taxonomy-ingestion-turn3")
            assert t3_done, (
                f"[taxonomy-ingestion-turn3] agent_complete never emitted.\n"
                f"{_summarize(t3_events)}"
            )
        finally:
            await _reset_demo_taxonomy()

    async def test_demo_schema_evolution(self) -> None:
        """registry.ts id='schema-evolution'. Self-consuming: re-arms before
        and after. Turn 1's enrichment trigger is a genuine LLM choice
        (registry.ts documents that the model may decline on a given run),
        so that part is asserted softly -- only completion-with-no-error is
        a hard requirement for turn 1. Turn 2 (new conversation) is only
        meaningfully checked if turn 1 actually grew the taxonomy."""
        await _reset_demo_taxonomy()
        try:
            thread_id_1 = f"schema-evolution-{uuid.uuid4().hex[:8]}"
            async with ws_client.connect(
                _ws_url(thread_id_1),
                additional_headers=auth_ws_headers(),
            ) as websocket:
                await _drain_until_welcome(websocket)
                t1_events, t1_done = await _drive_turn(
                    websocket,
                    "Show me waterproof boots",
                    thread_id_1,
                    timeout_s=ENRICHMENT_TURN_TIMEOUT_S,
                )
            _assert_no_error(t1_events, "schema-evolution-turn1")
            assert t1_done, (
                f"[schema-evolution-turn1] agent_complete never emitted.\n"
                f"{_summarize(t1_events)}"
            )

            enrichments = [e for e in t1_events if e.get("type") == "enrichment_triggered"]
            grew_taxonomy = any(e.get("status") == "complete" for e in enrichments)
            if not grew_taxonomy:
                pytest.skip(
                    "[schema-evolution] model declined to call trigger_enrichment on "
                    "this run (a documented possibility in registry.ts) -- turn 1 "
                    "completed cleanly with no error, which is the hard requirement; "
                    "re-run to exercise the growth path itself."
                )

            thread_id_2 = f"schema-evolution-{uuid.uuid4().hex[:8]}"
            async with ws_client.connect(
                _ws_url(thread_id_2),
                additional_headers=auth_ws_headers(),
            ) as websocket:
                await _drain_until_welcome(websocket)
                t2_events, t2_done = await _drive_turn(
                    websocket, "Show me waterproof boots", thread_id_2
                )
            _assert_no_error(t2_events, "schema-evolution-turn2")
            assert t2_done, (
                f"[schema-evolution-turn2] agent_complete never emitted.\n"
                f"{_summarize(t2_events)}"
            )
        finally:
            await _reset_demo_taxonomy()
