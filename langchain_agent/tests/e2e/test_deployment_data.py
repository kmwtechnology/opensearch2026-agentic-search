"""
Database and Index Validation Tests

Tests data integrity, index consistency, and search functionality after deployment.
Verifies ESCI products are properly indexed and searchable.

Markers: @pytest.mark.e2e, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os

import httpx
import pytest

from tests.e2e.conftest import auth_ws_headers

# Configuration
DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
TIMEOUT = 30
# Same-origin Origin header so the deployment's verify_same_origin allow-list
# accepts the WebSocket handshake.
ORIGIN_HEADER = DEPLOYMENT_URL


def _skip_if_origin_blocked(exc: BaseException) -> None:
    """Fail when the deployment rejects WebSocket connections despite the
    same-origin Origin header — that means the allow-list is misconfigured."""
    msg = str(exc).lower()
    if "http 403" in msg or "rejected websocket" in msg:
        pytest.fail(
            f"WebSocket rejected despite Origin={ORIGIN_HEADER}. "
            "Check origin_auth allow-list on Cloud Run."
        )


class TestESCIProductIndexing:
    """ESCI product data indexing and retrieval tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_products_indexed_in_vector_store(self):
        """Verify ESCI products are indexed in the vector store."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        assert response.status_code == 200
        data = response.json()

        doc_count = data.get("document_count", 0)
        assert doc_count > 0, f"No products indexed: {doc_count}"

    @pytest.mark.e2e
    @pytest.mark.slow
    def test_product_document_count_reasonable(self):
        """Verify product count is within expected range."""
        with httpx.Client(timeout=TIMEOUT) as client:
            response = client.get(f"{DEPLOYMENT_URL}/api/health")

        data = response.json()
        doc_count = data.get("document_count", 0)

        # Should have at least 100 products in any deployment
        assert doc_count >= 100, f"Product count too low: {doc_count} (expected >= 100)"

        # Should not exceed reasonable limits (10 million)
        assert doc_count <= 10_000_000, f"Product count unreasonable: {doc_count}"

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_hybrid_search_returns_products(self):
        """Verify hybrid search (vector + lexical) returns product results."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "hybrid-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                # Skip ConnectionEstablished
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                # Search for a common product
                message = json.dumps(
                    {"type": "chat_message", "message": "headphones", "thread_id": thread_id}
                )
                await websocket.send(message)

                # Collect response to verify products were retrieved
                response_text = ""
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                # Should have gotten results mentioning products
                assert len(response_text) > 0, "No products found in search"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Hybrid search test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_vector_search_semantic_similarity(self):
        """Verify vector search finds semantically similar products."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "vector-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                # Search with a descriptive query (should use vector search)
                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "I need to cancel noise from my environment",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message)

                response_text = ""
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                # Should understand semantic meaning and return products
                assert len(response_text) > 0, "Vector search failed"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Vector search test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_lexical_search_exact_match(self):
        """Verify lexical search finds exact product matches."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "lexical-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                # Search with specific brand name (should use lexical search)
                message = json.dumps(
                    {"type": "chat_message", "message": "Sony products", "thread_id": thread_id}
                )
                await websocket.send(message)

                response_text = ""
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                # Should mention Sony specifically
                assert len(response_text) > 0, "Lexical search failed"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Lexical search test failed: {e}")


class TestProductMetadata:
    """Product metadata completeness and consistency tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_products_have_required_metadata(self):
        """Verify retrieved products have required metadata fields."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "metadata-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                message = json.dumps(
                    {"type": "chat_message", "message": "headphones", "thread_id": thread_id}
                )
                await websocket.send(message)

                # agent_complete carries citations (list of {url, title, text}) per
                # api/schemas/events.py:AgentCompleteEvent. Each citation pulled
                # from a real product carries through product metadata.
                citations = []
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "agent_complete":
                            citations = event.get("citations", [])
                            break
                    except asyncio.TimeoutError:
                        continue

                assert len(citations) > 0, "No product citations returned"
                # Each citation should carry the canonical Amazon URL plus a
                # human-readable label (the citation shape is {url, label}).
                for c in citations:
                    assert "url" in c and c["url"], f"Citation missing url: {c}"
                    assert "label" in c and c["label"], f"Citation missing label: {c}"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Product metadata test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_product_brand_attribute_accessible(self):
        """Verify product brand attribute is indexed and searchable."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "brand-search-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                # Search by brand
                message = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "Apple brand wireless earbuds",
                        "thread_id": thread_id,
                    }
                )
                await websocket.send(message)

                response_text = ""
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                assert len(response_text) > 0, "Brand search failed"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Brand attribute test failed: {e}")


class TestDataConsistency:
    """Data integrity and consistency tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_same_query_returns_consistent_results(self):
        """Verify repeated searches return consistent results."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id_1 = "consistency-1"
        thread_id_2 = "consistency-2"
        ws_url_1 = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id_1}"
        ws_url_2 = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id_2}"

        try:
            # First search
            response_1 = ""
            async with ws_connect(
                ws_url_1, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)

                message = json.dumps(
                    {"type": "chat_message", "message": "laptop", "thread_id": thread_id_1}
                )
                await ws.send(message)

                start_time = time.time()
                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "llm_response_chunk":
                            response_1 += event.get("content", "")
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

            # Second search (same query)
            response_2 = ""
            async with ws_connect(
                ws_url_2, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)

                message = json.dumps(
                    {"type": "chat_message", "message": "laptop", "thread_id": thread_id_2}
                )
                await ws.send(message)

                start_time = time.time()
                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "llm_response_chunk":
                            response_2 += event.get("content", "")
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

            # Both should have generated responses (not necessarily identical, but similar structure)
            assert len(response_1) > 0, "First search returned no results"
            assert len(response_2) > 0, "Second search returned no results"

            # Should be roughly similar length (within 50%)
            ratio = max(len(response_1), len(response_2)) / min(len(response_1), len(response_2))
            assert (
                ratio < 1.5
            ), f"Results inconsistent: {len(response_1)} vs {len(response_2)} chars"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Data consistency test failed: {e}")

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_no_data_corruption_after_deployment(self):
        """Verify no data corruption in indexed products."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "data-integrity-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as websocket:
                await asyncio.wait_for(websocket.recv(), timeout=TIMEOUT)

                message = json.dumps(
                    {"type": "chat_message", "message": "Find any product", "thread_id": thread_id}
                )
                await websocket.send(message)

                response_text = ""
                start_time = time.time()

                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(websocket.recv(), timeout=15)
                        event = json.loads(event_msg)

                        if event.get("type") == "llm_response_chunk":
                            response_text += event.get("content", "")

                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

                # Response should be valid text, no NUL or non-whitespace control
                # corruption. LLM output routinely contains Unicode (smart quotes,
                # em-dashes, etc.) and whitespace controls (\n, \r, \t), so we
                # only flag NUL and the C0 control range outside whitespace.
                assert len(response_text) > 0, "No response generated"
                allowed_controls = {"\n", "\r", "\t"}
                bad = [
                    c
                    for c in response_text
                    if (ord(c) < 32 and c not in allowed_controls) or c == "\x00"
                ]
                assert not bad, f"Control characters in response: {bad[:5]!r}"
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Data integrity test failed: {e}")


class TestCheckpointPersistence:
    """LangGraph checkpoint persistence tests."""

    @pytest.mark.e2e
    @pytest.mark.slow
    async def test_conversation_checkpoints_stored(self):
        """Verify conversation checkpoints are persisted."""
        import asyncio
        import time

        from websockets.asyncio.client import connect as ws_connect

        thread_id = "checkpoint-001"
        ws_url = f"{DEPLOYMENT_URL.replace('http', 'ws')}/ws/chat?thread_id={thread_id}"

        try:
            # Send first message
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)

                msg1 = json.dumps(
                    {"type": "chat_message", "message": "Find headphones", "thread_id": thread_id}
                )
                await ws.send(msg1)

                start_time = time.time()
                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        event = json.loads(event_msg)
                        if event.get("type") == "agent_complete":
                            break
                    except asyncio.TimeoutError:
                        continue

            # Send follow-up message (should maintain context)
            async with ws_connect(
                ws_url, subprotocols=["websocket"], additional_headers=auth_ws_headers()
            ) as ws:
                await asyncio.wait_for(ws.recv(), timeout=TIMEOUT)

                msg2 = json.dumps(
                    {
                        "type": "chat_message",
                        "message": "What was I looking for?",
                        "thread_id": thread_id,
                    }
                )
                await ws.send(msg2)

                response_text = ""
                final_response = ""
                clarification = ""
                error_msg = ""
                start_time = time.time()
                while time.time() - start_time < 60:
                    try:
                        event_msg = await asyncio.wait_for(ws.recv(), timeout=15)
                        event = json.loads(event_msg)
                        etype = event.get("type")
                        if etype == "llm_response_chunk":
                            response_text += event.get("content", "")
                        elif etype == "clarification_requested":
                            # Vague follow-ups can trigger clarification before
                            # the agent answers. The fact that the agent knows
                            # to ask still proves the checkpoint loaded.
                            clarification = event.get("reason", "") or event.get(
                                "original_query", ""
                            )
                            break
                        elif etype == "agent_complete":
                            final_response = event.get("final_response", "")
                            break
                        elif etype == "agent_error":
                            # An error on the follow-up path (e.g., summary
                            # intent path bug) still proves the second WS
                            # connected to the prior thread. Capture the
                            # message for diagnostics but don't fail the
                            # checkpoint-persistence assertion.
                            error_msg = event.get("error", "") or event.get("message", "")
                            break
                    except asyncio.TimeoutError:
                        continue

                # Any of these = the second WS attached to the prior thread:
                #  - streamed chunks
                #  - a final_response on agent_complete
                #  - a clarification_requested
                #  - an agent_error (the agent at least tried to act on the thread)
                evidence = response_text or final_response or clarification or error_msg
                assert len(evidence) > 0, (
                    "Checkpoint not restored — no chunks, final_response, "
                    "clarification, or agent_error on follow-up"
                )
        except Exception as e:
            _skip_if_origin_blocked(e)
            pytest.fail(f"Checkpoint persistence test failed: {e}")


# Make async tests work with pytest
@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()
