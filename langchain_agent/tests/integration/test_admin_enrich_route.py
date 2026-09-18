"""
Integration tests for POST /api/admin/enrich — request/response contract,
ENABLE_ENRICHMENT_TOOL gating, and delegation to enrichment_service.

enrichment_service.enrich_attribute is mocked. Auth is same-origin only
(a matching Host/Origin header) — covered by
tests/unit/test_admin_routes_auth.py.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from api.main import app
from quality.enrichment_service import EnrichmentResult


@pytest.fixture
def client() -> TestClient:
    return TestClient(app, base_url="https://testserver")


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
@patch("quality.enrichment_service.enrich_attribute")
def test_successful_enrichment_returns_200(mock_enrich, client) -> None:
    mock_enrich.return_value = EnrichmentResult(
        success=True,
        attribute_type="waterproof",
        variant="weatherproof",
        canonical="waterproof",
        reindex_triggered=True,
        reindex_success=True,
        docs_processed=9618,
        duration_seconds=18.3,
    )

    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "waterproof", "variant": "weatherproof"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body == {
        "success": True,
        "attribute_type": "waterproof",
        "variant": "weatherproof",
        "canonical": "waterproof",
        "reason": None,
        "reindex_triggered": True,
        "reindex_success": True,
        "docs_processed": 9618,
        "duration_seconds": 18.3,
        "reindex_mode": "local",
        "reindex_run_url": None,
        "reindex_error": None,
    }
    mock_enrich.assert_called_once_with("waterproof", "weatherproof", explicit_canonical=None)


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
@patch("quality.enrichment_service.enrich_attribute")
def test_classification_failure_returns_200_with_reason(mock_enrich, client) -> None:
    """A failed classification is a normal (non-exceptional) result, not an
    HTTP error — the caller checks `success` in the body."""
    mock_enrich.return_value = EnrichmentResult(
        success=False,
        attribute_type="waterproof",
        variant="unobtainium",
        reason="could not classify to a known waterproof bucket",
    )

    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "waterproof", "variant": "unobtainium"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["success"] is False
    assert body["reason"] == "could not classify to a known waterproof bucket"


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
@patch("quality.enrichment_service.enrich_attribute")
def test_color_attribute_type_works_too(mock_enrich, client) -> None:
    mock_enrich.return_value = EnrichmentResult(
        success=True, attribute_type="color", variant="camel", canonical="brown"
    )

    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "color", "variant": "camel"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    assert r.json()["canonical"] == "brown"
    mock_enrich.assert_called_once_with("color", "camel", explicit_canonical=None)


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
@patch("quality.enrichment_service.enrich_attribute")
def test_explicit_canonical_is_passed_through(mock_enrich, client) -> None:
    """A term the dictionary can't classify (e.g. 'weatherproof' for waterproof) needs
    an explicit canonical supplied, the same way the live agent tool does."""
    mock_enrich.return_value = EnrichmentResult(
        success=True, attribute_type="waterproof", variant="weatherproof", canonical="waterproof"
    )

    with client:
        r = client.post(
            "/api/admin/enrich",
            json={
                "attribute_type": "waterproof",
                "variant": "weatherproof",
                "canonical": "waterproof",
            },
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 200
    assert r.json()["canonical"] == "waterproof"
    mock_enrich.assert_called_once_with(
        "waterproof", "weatherproof", explicit_canonical="waterproof"
    )


@patch("core.config.ENABLE_ENRICHMENT_TOOL", False)
def test_disabled_flag_returns_403(client) -> None:
    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "waterproof", "variant": "weatherproof"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 403


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
def test_empty_variant_rejected_by_schema_validation(client) -> None:
    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "waterproof", "variant": ""},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
def test_missing_variant_field_rejected(client) -> None:
    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"attribute_type": "waterproof"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422


@patch("core.config.ENABLE_ENRICHMENT_TOOL", True)
def test_missing_attribute_type_field_rejected(client) -> None:
    with client:
        r = client.post(
            "/api/admin/enrich",
            json={"variant": "weatherproof"},
            headers={"Host": "localhost:8000"},
        )

    assert r.status_code == 422
