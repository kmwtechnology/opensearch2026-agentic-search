"""
Integration tests for POST /api/admin/enrich — request/response contract,
ENABLE_ENRICHMENT_TOOL gating, and delegation to enrichment_service.

enrichment_service.enrich_material is mocked; auth via a real session
login. Note: TestClient must use an https:// base_url — SessionMiddleware's
https_only flag (from SESSION_COOKIE_SECURE, default true) is baked in at
app-construction time, and a Secure cookie set over the default
http://testserver base URL is silently dropped by httpx's cookie jar on the
next request. Auth itself is covered by tests/unit/test_admin_routes_auth.py.
"""

import os
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from enrichment_service import EnrichmentResult


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"password": os.environ.get("LOGIN_PASSWORD", "")},
        headers={"Host": "localhost:8000"},
    )
    assert resp.status_code == 200, f"test login failed: {resp.text}"


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_material")
def test_successful_enrichment_returns_200(mock_enrich, client) -> None:
    mock_enrich.return_value = EnrichmentResult(
        success=True, variant="chrome", canonical="metal", docs_updated=30
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich", json={"variant": "chrome"}, headers={"Host": "localhost:8000"}
        )

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "success": True,
        "variant": "chrome",
        "canonical": "metal",
        "docs_updated": 30,
        "reason": None,
    }
    mock_enrich.assert_called_once_with("chrome")


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_material")
def test_classification_failure_returns_200_with_reason(mock_enrich, client) -> None:
    """A failed classification is a normal (non-exceptional) result, not an
    HTTP error — the caller checks `success` in the body."""
    mock_enrich.return_value = EnrichmentResult(
        success=False, variant="unobtainium", reason="could not classify to a known material bucket"
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"variant": "unobtainium"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["reason"] == "could not classify to a known material bucket"


@patch("config.ENABLE_ENRICHMENT_TOOL", False)
def test_disabled_flag_returns_403(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich", json={"variant": "chrome"}, headers={"Host": "localhost:8000"}
        )

    assert r.status_code == 403


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
def test_empty_variant_rejected_by_schema_validation(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich", json={"variant": ""}, headers={"Host": "localhost:8000"}
        )

    assert r.status_code == 422


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
def test_missing_variant_field_rejected(client) -> None:
    with client:
        _login(client)
        r = client.post("/api/admin/enrich", json={}, headers={"Host": "localhost:8000"})

    assert r.status_code == 422
