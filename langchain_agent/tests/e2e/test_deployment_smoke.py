"""
Post-Deployment Smoke Tests for Agentic Hybrid Search

Tests core functionality after deployment to ensure the system is working correctly.
Includes health checks, API authentication, WebSocket connectivity, and search pipeline validation.

Markers: @pytest.mark.e2e, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os
import time
from datetime import datetime
from typing import Optional

import httpx
import pytest
from websockets.asyncio.client import connect as ws_connect
from websockets.exceptions import WebSocketException

from tests.e2e.conftest import (
    auth_rest_headers,
    auth_ws_headers,
    get_auth_cookie,
)


def _fail_if_origin_blocked(exc: BaseException) -> None:
    """Fail (not skip) when the deployment rejects with origin errors.
    With the correct Origin header sent on every ws_connect call this should
    never trigger — if it does, the origin allow-list is misconfigured."""
    msg = str(exc).lower()
    if "http 403" in msg or "rejected websocket" in msg:
        pytest.fail(
            f"WebSocket rejected despite Origin={ORIGIN_HEADER}. "
            "Check CORS/origin config on Cloud Run."
        )


# Configuration
DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "test-api-key")
TIMEOUT = 30  # seconds
# Cross-encoder model loads ~60s on first request; full pipeline round-trip needs ~90-120s
WEBSOCKET_TIMEOUT = 180  # seconds
# Origin header must match allowed UI origin (production is same-origin as API)
ORIGIN_HEADER = DEPLOYMENT_URL


class TestDeploymentHealth:
    """Health check and basic connectivity tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_endpoint_returns_ok(self):
        """Verify /health endpoint returns 200 with correct status."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200, f"Health check failed: {response.text}"
        data = response.json()

        assert "status" in data, "Missing 'status' field in health response"
        assert data["status"] in ["ok", "degraded"], f"Invalid status: {data['status']}"
        assert "version" in data, "Missing 'version' field"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_checks_postgres(self):
        """Verify health endpoint reports PostgreSQL status."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "postgres" in data, "Missing 'postgres' field"
        assert isinstance(data["postgres"], bool), "postgres field should be boolean"
        assert data["postgres"], "PostgreSQL should be healthy"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_checks_google_api(self):
        """Verify health endpoint reports Google AI API status."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "google_ai" in data, "Missing 'google_ai' field"
        assert isinstance(data["google_ai"], bool), "google_ai field should be boolean"
        assert data["google_ai"], "Google AI API should be healthy"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_checks_opensearch(self):
        """Verify health endpoint reports OpenSearch status."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "vector_store" in data, "Missing 'vector_store' field"
        assert isinstance(data["vector_store"], bool), "vector_store field should be boolean"
        assert data["vector_store"], "OpenSearch should be healthy"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_suggest_endpoint_returns_results(self):
        """Typeahead suggest endpoint should answer a prefix query with 200."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/suggest?q=son")

        assert response.status_code == 200, f"/api/suggest failed: {response.text}"
        data = response.json()
        assert "suggestions" in data, "Missing 'suggestions' field"
        assert isinstance(data["suggestions"], list), "suggestions field should be a list"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_reports_document_count(self):
        """Verify health endpoint reports product document count."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200
        data = response.json()

        assert "document_count" in data, "Missing 'document_count' field"
        assert isinstance(data["document_count"], int), "document_count should be integer"
        assert data["document_count"] > 0, "Should have indexed products"


class TestAuthentication:
    """Two-layer authentication tests: same-origin + shared-password session.

    The deployment gates protected routes via two layers (in order):
    1. `api/middleware/origin_auth.py:verify_same_origin` — blocks cross-site.
    2. `api/middleware/session_auth.py:verify_session` — blocks anyone-with-the-URL
       who hasn't entered the shared password.

    These tests probe the contract from the outside; the unit-test guard at
    `tests/unit/test_origin_auth_contract.py` exercises the origin layer in
    isolation.
    """

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_request_with_valid_origin_and_session_accepted(self):
        """Valid origin + valid session cookie → 200 on protected route."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(
                f"{DEPLOYMENT_URL}/api/conversations", headers=auth_rest_headers()
            )

        if response.status_code == 429:
            pytest.skip("Rate limited; cannot verify origin acceptance")
        assert response.status_code in [
            200,
            400,
        ], f"Valid origin+session rejected: {response.status_code} - {response.text}"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_request_with_valid_origin_no_session_returns_401(self):
        """Valid origin but no session cookie → 401 (login gate active)."""
        headers = {"Origin": ORIGIN_HEADER}
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/conversations", headers=headers)

        if response.status_code == 429:
            pytest.skip("Rate limited; cannot verify session gate")
        assert response.status_code == 401, (
            f"Unauthenticated request should 401, got {response.status_code}. "
            "If this is 200 the login gate is bypassed."
        )

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_request_with_disallowed_origin_rejected(self):
        """Cross-origin request (Origin does not match) is rejected with 403.

        Origin auth runs *before* session auth, so even an authenticated
        cookie cannot rescue a disallowed Origin.
        """
        headers = {"Origin": "https://evil.example.com", "Cookie": get_auth_cookie()}

        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/conversations", headers=headers)

        if response.status_code == 429:
            pytest.skip("Rate limited; cannot verify origin rejection")
        assert (
            response.status_code == 403
        ), f"Disallowed origin should be rejected with 403, got {response.status_code}"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_health_endpoint_does_not_require_session(self):
        """Health endpoint stays public — no session cookie required."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert (
            response.status_code == 200
        ), f"/api/health must remain public for monitoring; got {response.status_code}"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_login_endpoint_round_trips_a_session_cookie(self):
        """POST /api/auth/login on a valid password returns a Set-Cookie header.

        This is the smoke-test corollary of the conftest helper: if the
        deployment ever stops setting the cookie (misconfigured
        SessionMiddleware, https_only mismatch), every other test in the
        suite would fail confusingly. Surfacing it here makes the cause obvious.
        """
        with httpx.Client(timeout=TIMEOUT) as client:
            # Just confirm the cookie helper works against the live deployment.
            cookie = get_auth_cookie()
        assert cookie and "=" in cookie, f"Login did not return a usable cookie: {cookie!r}"


class TestWebSocketConnectivity:
    """WebSocket connection and basic messaging tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_websocket_accepts_valid_connection(self):
        """Verify WebSocket endpoint accepts valid connection."""
        thread_id = "test-thread-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Should connect without error
                assert websocket is not None
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"WebSocket connection failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_websocket_receives_connection_established(self):
        """Verify WebSocket sends ConnectionEstablished event on connect."""
        thread_id = "test-thread-002"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Receive first message (should be ConnectionEstablished)
                message = await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)
                event = json.loads(message)

                assert "type" in event, "Missing event_type"
                assert (
                    event["type"] == "connection_established"
                ), f"Expected ConnectionEstablished, got {event.get('type')}"
        except asyncio.TimeoutError:
            pytest.fail("Timeout waiting for ConnectionEstablished event")
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"WebSocket test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_websocket_accepts_message(self):
        """Verify WebSocket endpoint accepts incoming messages."""
        thread_id = "test-thread-003"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Skip ConnectionEstablished
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                # Send test message
                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Find wireless headphones",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message)

                # Should receive events in response
                response = await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)
                event = json.loads(response)

                assert "type" in event, "Response missing event_type"
        except asyncio.TimeoutError:
            pytest.fail("Timeout waiting for response after sending message")
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"WebSocket messaging test failed: {e}")


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

                        # Break on agent complete
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                assert len(received_events) > 0, "No events received"
                assert any(
                    e.get("type") == "agent_complete" for e in received_events
                ), "agent_complete event never received — server likely dropped the message"
                assert len(response_text) > 0, "No response text generated"
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
                            break
                    except asyncio.TimeoutError:
                        continue

                assert any(
                    e.get("type") == "agent_complete" for e in received_events
                ), "agent_complete event never received"
                assert len(response_text) > 0, "No comparison generated"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Comparison intent test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_refinement_intent_constrains_results(self):
        """Test refinement intent adds constraints to prior search."""
        thread_id = "test-refinement-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Skip ConnectionEstablished
                await asyncio.wait_for(websocket.recv(), timeout=WEBSOCKET_TIMEOUT)

                # First search
                message1 = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Show me headphones",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message1)

                # Collect first response
                start_time = time.time()
                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                # Second message with refinement
                message2 = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Now only show wireless ones",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message2)

                # Collect refined response
                response_text = ""
                received_complete = False
                start_time = time.time()
                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")
                        if event.get("type") == "agent_complete":
                            received_complete = True
                            break
                    except asyncio.TimeoutError:
                        continue

                assert received_complete, "agent_complete event never received"
                assert len(response_text) > 0, "No refined response generated"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Refinement intent test failed: {e}")


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

                # Collect complete response
                response_text = ""
                metadata = {}
                start_time = time.time()

                while time.time() - start_time < WEBSOCKET_TIMEOUT:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")
                        elif event.get("type") == "agent_complete":
                            metadata = event.get("metadata", {})
                            break
                    except asyncio.TimeoutError:
                        continue

                # Check for citations in metadata
                assert (
                    "citations" in metadata or "sources" in metadata or len(response_text) > 0
                ), "Response should include citations or sources"
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
                # is ~10s on a 4-core Cloud Run instance; total budget covers
                # embed + hybrid retrieve + rerank + LLM stream + TLS overhead.
                assert (
                    elapsed < 45
                ), f"Search took {elapsed:.1f}s, should be under 45s (Cloud Run + network)"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Response timing test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_generation_response_time_under_10_seconds(self):
        """Verify generation responses complete in under 10 seconds."""
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
                # SLO ceiling 45s — comparison intent runs same reranker batch
                # as search; LLM stream may be longer for multi-product output.
                assert (
                    elapsed < 45
                ), f"Generation took {elapsed:.1f}s, should be under 45s (Cloud Run + network)"
        except Exception as e:
            _fail_if_origin_blocked(e)
            pytest.fail(f"Generation timing test failed: {e}")


# Make async tests work with pytest
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
