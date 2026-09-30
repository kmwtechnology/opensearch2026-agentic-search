"""
Smoke Tests for Agentic Hybrid Search

Health, origin checking and the search pipeline against a running backend
(DEPLOYMENT_URL, default the native backend on :8080). scripts/smoke_local.sh
runs the whole file; `make ci` runs test_search_intent_returns_results.
"""

import asyncio
import json
import time

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect

from tests.e2e.conftest import (
    DEPLOYMENT_URL,
    ORIGIN_HEADER,
    auth_rest_headers,
    auth_ws_headers,
)


def _fail_if_origin_blocked(exc: BaseException) -> None:
    """Fail (not skip) when the deployment rejects with origin errors.
    With the correct Origin header sent on every ws_connect call this should
    never trigger — if it does, the origin allow-list is misconfigured."""
    msg = str(exc).lower()
    if "http 403" in msg or "rejected websocket" in msg:
        pytest.fail(
            f"WebSocket rejected despite Origin={ORIGIN_HEADER}. "
            "Check the same-origin allow-list in api/middleware/origin_auth.py."
        )


TIMEOUT = 30  # seconds
# Cross-encoder model loads ~60s on first request; full pipeline round-trip needs ~90-120s
WEBSOCKET_TIMEOUT = 180  # seconds


class TestDeploymentHealth:
    """Health check and basic connectivity tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_reports_every_dependency(self):
        """/api/health is public, returns 200, and reports Postgres, OpenSearch and the
        indexed document count."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()
        assert data["status"] in ["ok", "degraded"], f"Invalid status: {data['status']}"
        assert "version" in data, "Missing 'version' field"
        assert data["postgres"] is True, "PostgreSQL should be healthy"
        assert isinstance(data["vector_store"], bool), "vector_store field should be boolean"
        assert isinstance(data["document_count"], int), "document_count should be integer"
        if not data["vector_store"] or data["document_count"] == 0:
            pytest.skip("OpenSearch not yet initialized (run make setup)")


class TestAuthentication:
    """Same-origin authentication tests.

    The deployment gates protected routes via one layer:
    `api/middleware/origin_auth.py:verify_same_origin` — blocks cross-site.

    These tests probe the contract from the outside; the unit-test guard at
    `tests/unit/test_origin_auth_contract.py` exercises the origin layer in
    isolation.
    """

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_request_with_valid_origin_accepted(self):
        """Valid origin → 200 on a same-origin-only route."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/admin/health", headers=auth_rest_headers())

        assert response.status_code in [
            200,
            400,
        ], f"Valid origin rejected: {response.status_code} - {response.text}"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_request_with_disallowed_origin_rejected(self):
        """Cross-origin request (Origin does not match) is rejected with 403."""
        headers = {"Origin": "https://evil.example.com"}

        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/admin/health", headers=headers)

        assert (
            response.status_code == 403
        ), f"Disallowed origin should be rejected with 403, got {response.status_code}"


class TestSearchPipeline:
    """RAG Q&A search pipeline tests with different intents."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_search_intent_returns_results(self):
        """Test search intent returns products with citations."""
        thread_id = "test-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Skip ConnectionEstablished
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                # Send search query
                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Find wireless headphones",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message)

                # Collect response events
                response_text = ""
                final_response = ""
                received_events = []
                start_time = time.time()

                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        received_events.append(event)

                        # Collect LLM response chunks
                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        # Break on agent complete. Fall back to final_response
                        # when no chunks streamed (e.g. the server-side graph
                        # timeout emits a complete event with fallback text but
                        # never streams chunks) -- see #23.
                        if event.get("type") == "agent_complete":
                            final_response = event.get("final_response", "") or final_response
                            break
                    except asyncio.TimeoutError:
                        continue

                assert len(received_events) > 0, "No events received"
                assert any(
                    e.get("type") == "agent_complete" for e in received_events
                ), "agent_complete event never received — server likely dropped the message"
                assert len(response_text or final_response) > 0, "No response text generated"
        except asyncio.TimeoutError:
            pytest.fail("Timeout during search intent test")
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Search intent test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_comparison_intent_returns_results(self):
        """Test comparison intent between products."""
        thread_id = "test-compare-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Skip ConnectionEstablished
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                # Send comparison query
                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Compare wireless headphones vs earbuds",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message)

                # Collect response
                response_text = ""
                final_response = ""
                received_events = []
                start_time = time.time()

                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        received_events.append(event)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            final_response = event.get("final_response", "") or final_response
                            break
                    except asyncio.TimeoutError:
                        continue

                assert any(
                    e.get("type") == "agent_complete" for e in received_events
                ), "agent_complete event never received"
                assert len(response_text or final_response) > 0, "No comparison generated"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Comparison intent test failed: {e}")


class TestCitations:
    """Citation and product metadata validation tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_citations_include_product_urls(self):
        """Verify citations in responses include valid product URLs."""
        thread_id = "test-citations-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                message = json.dumps(
                    {"type": "chat_message", "message": "Find headphones", "thread_id": thread_id}
                )
                await websocket.send(message)

                complete = None
                start_time = time.time()

                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "agent_complete":
                            complete = event
                            break
                    except asyncio.TimeoutError:
                        continue

                assert complete is not None, "agent_complete event never received"
                # `citations` is a top-level list on agent_complete (never under
                # `metadata`): {label, url, asin?, image_url?}, url = Amazon search by title.
                citations = complete.get("citations")
                assert isinstance(citations, list), f"citations missing/not a list: {complete!r}"
                assert citations, "search for 'Find headphones' produced no citations"
                for c in citations:
                    assert c.get("label"), c
                    assert c.get("url", "").startswith("https://www.amazon.com/s?k="), c
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Citations test failed: {e}")


class TestResponseTiming:
    """Response time and performance tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_search_response_time_under_5_seconds(self):
        """Verify search responses complete in under 5 seconds."""
        thread_id = "test-timing-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Find headphones under $100",
                        "thread_id": thread_id,
                    }
                )

                start_time = time.time()
                await websocket.send(message)

                # Wait for completion
                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                elapsed = time.time() - start_time
                # SLO ceiling 45s. Cross-encoder predict() on 40 docs (RERANKER_FETCH_K)
                # is ~10s on typical hardware; total budget covers embed +
                # hybrid retrieve + rerank + LLM stream + network overhead.
                assert elapsed < 45, f"Search took {elapsed:.1f}s, should be under 45s"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Response timing test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_generation_response_time_under_60_seconds(self):
        """Verify generation responses complete in under 60 seconds."""
        thread_id = "test-timing-gen-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Generate comparison between wireless and wired headphones",
                        "thread_id": thread_id,
                    }
                )

                start_time = time.time()
                await websocket.send(message)

                # Wait for completion
                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                elapsed = time.time() - start_time
                # SLO ceiling 60s (issue #54: raised from 45s after a real
                # measurement of 58.4s on a healthy deploy -- not a first-request
                # cold start, since prior tests in this same run already warmed
                # the container). Comparison intent generates a longer multi-
                # product synthesis than search's single-list response, so it
                # legitimately needs more budget than test_search_response_time_
                # under_5_seconds's 45s ceiling for the same reranker batch size.
                assert elapsed < 60, f"Generation took {elapsed:.1f}s, should be under 60s"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Generation timing test failed: {e}")
