"""
Unit tests for api/routes/health.py.

Mocks psycopg, create_opensearch_client, and config values so no live
services are required.
"""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

import vector_store
from api.main import app
from api.routes.chat import manager as chat_manager


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture(autouse=True)
def _reset_shared_client():
    """get_shared_opensearch_client() is a process-wide lazy singleton (#25)
    -- reset it between tests so each test's own patch of the underlying
    factory actually takes effect, rather than every test after the first
    silently reusing whichever mock got cached first."""
    vector_store.reset_shared_opensearch_client()
    yield
    vector_store.reset_shared_opensearch_client()


# ---------------------------------------------------------------------------
# Helpers — patch targets used across multiple tests
# ---------------------------------------------------------------------------

_PSYCOPG = "api.routes.health.psycopg"
_OS_CLIENT = "vector_store.get_shared_opensearch_client"
_API_KEY = "api.routes.health.GOOGLE_API_KEY"


def _pg_ok():
    """Context-manager mock that succeeds SELECT 1."""
    conn = MagicMock()
    cur = MagicMock()
    cur.execute.return_value = None
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    return conn


def _os_ok(count=100):
    """OpenSearch client mock returning a healthy count response."""
    client = MagicMock()
    client.count.return_value = {"count": count}
    return client


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_health_all_ok(mock_pg, mock_os, client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["postgres"] is True
    assert body["google_ai"] is True
    assert body["vector_store"] is True
    assert body["document_count"] == 100


@patch(_API_KEY, "")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_health_degraded_when_no_api_key(mock_pg, mock_os, client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["google_ai"] is False


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", side_effect=Exception("connection refused"))
def test_health_degraded_when_postgres_fails(mock_pg, mock_os, client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "degraded"
    assert body["postgres"] is False
    assert "postgres_error" in body


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, side_effect=Exception("opensearch down"))
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_health_vector_store_error_not_degraded_overall(mock_pg, mock_os, client):
    # vector_store failure doesn't affect overall "ok" (only postgres + google_ai gate it)
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["vector_store"] is False
    assert "vector_store_error" in body
    assert body["status"] == "ok"  # postgres+google_ai still healthy


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok(count=0))
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_health_vector_store_false_when_zero_docs(mock_pg, mock_os, client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["vector_store"] is False
    assert body["document_count"] == 0


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_health_returns_version(mock_pg, mock_os, client):
    r = client.get("/api/health")
    assert "version" in r.json()


# ---------------------------------------------------------------------------
# GET /health/ready
# ---------------------------------------------------------------------------


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_ready_returns_true_when_healthy_and_warmed_up(mock_pg, mock_os, client):
    with patch.object(chat_manager.agent_service, "_warmup_complete", True):
        r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True}


@patch(_API_KEY, "")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_ready_returns_503_with_reason_when_degraded(mock_pg, mock_os, client):
    with patch.object(chat_manager.agent_service, "_warmup_complete", True):
        r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert "reason" in body
    assert body["reason"]["status"] == "degraded"


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_ready_returns_503_when_healthy_but_warmup_incomplete(mock_pg, mock_os, client):
    """Regression test for #23: a cold instance whose reranker is still
    loading must NOT report ready, even if postgres/opensearch/google_ai are
    all healthy -- this is what gates Cloud Run's --startup-probe so it
    doesn't route concurrent chat traffic to a not-yet-warm instance."""
    with patch.object(chat_manager.agent_service, "_warmup_complete", False):
        r = client.get("/api/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["ready"] is False
    assert body["reason"]["warmup_complete"] is False


# ---------------------------------------------------------------------------
# GET /config
# ---------------------------------------------------------------------------


def test_config_returns_empty_api_url_in_dev(client):
    with patch.dict("os.environ", {"API_URL": ""}, clear=False):
        r = client.get("/api/config")
    assert r.status_code == 200
    assert "apiUrl" in r.json()


def test_config_returns_https_origin_as_api_url(client):
    r = client.get(
        "/api/config",
        headers={"origin": "https://my-service.a.run.app"},
    )
    assert r.status_code == 200
    assert r.json()["apiUrl"] == "https://my-service.a.run.app"


def test_config_uses_env_var_for_http_origin(client):
    with patch.dict("os.environ", {"API_URL": "http://localhost:8000"}):
        r = client.get("/api/config", headers={"origin": "http://localhost:5173"})
    assert r.status_code == 200
    assert r.json()["apiUrl"] == "http://localhost:8000"


# ---------------------------------------------------------------------------
# Event loop non-blocking (regression coverage for #25)
# ---------------------------------------------------------------------------


@patch(_API_KEY, "fake-key")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect")
@pytest.mark.asyncio
async def test_slow_postgres_does_not_block_concurrent_config_request(mock_connect, mock_os):
    """/api/health is Cloud Run's --startup-probe target (see #23), polled on
    a schedule. A blocking psycopg.connect() called directly on an async def
    route would stall the loop -- and every in-flight WebSocket -- for the
    duration of a Postgres hiccup. run_in_threadpool moves it to a worker
    thread; this proves a concurrent request doesn't wait on it."""

    def _slow_connect(*args, **kwargs):
        time.sleep(0.4)
        return _pg_ok()

    mock_connect.side_effect = _slow_connect

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
        t0 = time.monotonic()
        slow_task = asyncio.create_task(ac.get("/api/health"))
        await asyncio.sleep(0.05)  # let the slow request actually start
        fast_resp = await ac.get("/api/config")
        fast_elapsed = time.monotonic() - t0
        slow_resp = await slow_task

    assert slow_resp.status_code == 200
    assert fast_resp.status_code == 200
    assert fast_elapsed < 0.3, f"fast request took {fast_elapsed:.3f}s -- event loop was blocked"
