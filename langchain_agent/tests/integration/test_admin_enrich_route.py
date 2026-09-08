"""
Integration tests for POST /api/admin/enrich — request/response contract,
ENABLE_ENRICHMENT_TOOL gating, and delegation to enrichment_service.

enrichment_service.enrich_attribute is mocked; auth via a real session
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
from api.routes.auth import limiter as auth_limiter
from enrichment_service import EnrichmentResult


@pytest.fixture
def client() -> TestClient:
    # Each test logs in once; the login rate limiter (5/min) is in-memory
    # and shared across the whole pytest process via the module-level `app`
    # singleton, so it must be reset per test rather than left to expire.
    # Note: api/routes/auth.py constructs its own Limiter() rather than
    # reusing api.main's (registered as app.state.limiter) — the login
    # route's @limiter.limit(...) decorator is bound to this separate
    # instance, so it's the one that actually needs resetting.
    auth_limiter.reset()
    return TestClient(app, base_url="https://testserver")


def _login(client: TestClient) -> None:
    resp = client.post(
        "/api/auth/login",
        json={"password": os.environ.get("LOGIN_PASSWORD", "")},
        headers={"Host": "localhost:8000"},
    )
    assert resp.status_code == 200, f"test login failed: {resp.text}"


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_attribute")
def test_successful_enrichment_returns_200(mock_enrich, client) -> None:
    mock_enrich.return_value = EnrichmentResult(
        success=True,
        attribute_type="material",
        variant="chrome",
        canonical="metal",
        reindex_triggered=True,
        reindex_success=True,
        docs_processed=9618,
        duration_seconds=18.3,
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material", "variant": "chrome"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "success": True,
        "attribute_type": "material",
        "variant": "chrome",
        "canonical": "metal",
        "reason": None,
        "reindex_triggered": True,
        "reindex_success": True,
        "docs_processed": 9618,
        "duration_seconds": 18.3,
        "reindex_mode": "local",
        "reindex_run_url": None,
        "reindex_error": None,
    }
    mock_enrich.assert_called_once_with("material", "chrome", explicit_canonical=None)


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_attribute")
def test_classification_failure_returns_200_with_reason(mock_enrich, client) -> None:
    """A failed classification is a normal (non-exceptional) result, not an
    HTTP error — the caller checks `success` in the body."""
    mock_enrich.return_value = EnrichmentResult(
        success=False,
        attribute_type="material",
        variant="unobtainium",
        reason="could not classify to a known material bucket",
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material", "variant": "unobtainium"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["reason"] == "could not classify to a known material bucket"


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_attribute")
def test_color_attribute_type_works_too(mock_enrich, client) -> None:
    mock_enrich.return_value = EnrichmentResult(
        success=True, attribute_type="color", variant="camel", canonical="brown"
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "color", "variant": "camel"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    assert r.json()["canonical"] == "brown"
    mock_enrich.assert_called_once_with("color", "camel", explicit_canonical=None)


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
@patch("enrichment_service.enrich_attribute")
def test_explicit_canonical_is_passed_through(mock_enrich, client) -> None:
    """A term the dictionary can't classify (e.g. 'chrome' for material) needs
    an explicit canonical supplied, the same way the live agent tool does."""
    mock_enrich.return_value = EnrichmentResult(
        success=True, attribute_type="material", variant="chrome", canonical="metal"
    )

    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material", "variant": "chrome", "canonical": "metal"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    assert r.json()["canonical"] == "metal"
    mock_enrich.assert_called_once_with("material", "chrome", explicit_canonical="metal")


@patch("config.ENABLE_ENRICHMENT_TOOL", False)
def test_disabled_flag_returns_403(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material", "variant": "chrome"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 403


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
def test_empty_variant_rejected_by_schema_validation(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material", "variant": ""},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
def test_missing_variant_field_rejected(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "material"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422


@patch("config.ENABLE_ENRICHMENT_TOOL", True)
def test_missing_attribute_type_field_rejected(client) -> None:
    with client:
        _login(client)
        r = client.post(
            "/api/admin/enrich",
            json={"variant": "chrome"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422
