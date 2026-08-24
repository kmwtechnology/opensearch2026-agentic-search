"""
Unit tests for api/routes/health.py.

Mocks psycopg, create_opensearch_client, and config values so no live
services are required.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers — patch targets used across multiple tests
# ---------------------------------------------------------------------------

_PSYCOPG = "api.routes.health.psycopg"
_OS_CLIENT = "vector_store.create_opensearch_client"
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
def test_ready_returns_true_when_healthy(mock_pg, mock_os, client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    assert r.json() == {"ready": True}


@patch(_API_KEY, "")
@patch(_OS_CLIENT, return_value=_os_ok())
@patch(_PSYCOPG + ".connect", return_value=_pg_ok())
def test_ready_returns_false_with_reason_when_degraded(mock_pg, mock_os, client):
    r = client.get("/api/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["ready"] is False
    assert "reason" in body
    assert body["reason"]["status"] == "degraded"


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
