"""Contract test: origin auth via FastAPI TestClient.

Pure unit test (no network, no live deployment). Wires `verify_same_origin`
into a minimal FastAPI app and replays the exact header combinations that
the production deployment receives, plus the smoke-test client's
disallowed-Origin combination.

Catches the 2026-04-29 smoke failure mode where the Host fallback in
`verify_same_origin` always matched on Cloud Run (Host = destination =
always *.run.app) and silently overrode any disallowed Origin.
"""

from __future__ import annotations

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from api.middleware.origin_auth import verify_same_origin


@pytest.fixture(scope="module")
def app() -> FastAPI:
    fastapi_app = FastAPI()

    @fastapi_app.get("/protected")
    async def protected(_: bool = Depends(verify_same_origin)) -> dict[str, bool]:
        return {"ok": True}

    return fastapi_app


@pytest.fixture(scope="module")
def client(app: FastAPI) -> TestClient:
    return TestClient(app)


# ---------------------------------------------------------------------------
# The regression scenarios
# ---------------------------------------------------------------------------


def test_disallowed_origin_with_cloud_run_host_returns_403(client: TestClient) -> None:
    """The exact smoke-test scenario: disallowed Origin + Cloud Run Host must 403.

    Before the 2026-04-29 fix, this returned 200 because the Host fallback
    accepted any *.run.app value regardless of an explicit disallowed Origin.
    """
    response = client.get(
        "/protected",
        headers={
            "Origin": "https://evil.example.com",
            "Host": "agentic-hybrid-search-375500751528.us-central1.run.app",
        },
    )
    assert response.status_code == 403, (
        f"Disallowed Origin must 403 even when Host matches *.run.app — got "
        f"{response.status_code}. Host is the destination, not the source; "
        "treating it as a same-origin signal defeats the entire allow-list."
    )


def test_disallowed_origin_with_localhost_host_returns_403(client: TestClient) -> None:
    response = client.get(
        "/protected",
        headers={"Origin": "https://evil.example.com", "Host": "localhost:5173"},
    )
    assert response.status_code == 403


def test_disallowed_referer_with_cloud_run_host_returns_403(client: TestClient) -> None:
    response = client.get(
        "/protected",
        headers={
            "Referer": "https://evil.example.com/path",
            "Host": "service.us-central1.run.app",
        },
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# The legitimate cases (still allowed after the fix)
# ---------------------------------------------------------------------------


def test_allowed_cloud_run_origin_returns_200(client: TestClient) -> None:
    response = client.get(
        "/protected",
        headers={
            "Origin": "https://agentic-hybrid-search-375500751528.us-central1.run.app",
            "Host": "agentic-hybrid-search-375500751528.us-central1.run.app",
        },
    )
    assert response.status_code == 200


def test_allowed_localhost_origin_returns_200(client: TestClient) -> None:
    response = client.get(
        "/protected",
        headers={"Origin": "http://localhost:5173", "Host": "localhost:5173"},
    )
    assert response.status_code == 200


def test_no_origin_no_referer_falls_back_to_host_cloud_run(client: TestClient) -> None:
    """Same-origin GET (browser omits Origin) with Cloud Run Host: 200."""
    response = client.get(
        "/protected",
        headers={"Host": "service-12345.us-central1.run.app"},
    )
    assert response.status_code == 200


def test_no_origin_no_referer_unknown_host_returns_403(client: TestClient) -> None:
    response = client.get(
        "/protected",
        headers={"Host": "evil.example.com"},
    )
    assert response.status_code == 403


def test_disallowed_origin_overrides_allowed_referer_is_not_a_thing(
    client: TestClient,
) -> None:
    """is_allowed_origin checks Origin first; if disallowed it falls through to
    Referer. So a good Referer rescues a bad Origin — this is documented
    behavior (see test_is_allowed_origin_bad_origin_good_referer)."""
    response = client.get(
        "/protected",
        headers={
            "Origin": "https://evil.example.com",
            "Referer": "http://localhost:5173/dashboard",
            "Host": "service.us-central1.run.app",
        },
    )
    assert response.status_code == 200
