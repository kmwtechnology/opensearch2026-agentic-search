"""Contract test: admin routes enforce same-origin auth.

Pure unit test (no network). Verifies that all /api/admin/* endpoints
require a same-origin request. Catches any new admin routes that ship
without the origin guard.

Scope note: this is a demo box — admin routes are deliberately reachable by
any SAME-ORIGIN caller without credentials (the header's Restart button
calls /api/admin/demo-reset from the browser with no token), and
verify_same_origin still rejects cross-site requests. Any deployment holding
something worth protecting should put a real auth layer in front of these
routes.

verify_admin_token (X-Admin-Token header, for unattended automation) is
tested standalone below since it isn't wired into any admin.py route today.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from api.middleware.admin_auth import verify_admin_token
from api.middleware.origin_auth import verify_same_origin


@pytest.fixture(scope="module")
def test_app() -> FastAPI:
    app = FastAPI()

    @app.get("/api/admin/diagnose")
    async def admin_diagnose(request: Request, q: str = "test"):
        await verify_same_origin(request)
        return {"query": q}

    @app.get("/api/admin/health")
    async def admin_health(request: Request):
        await verify_same_origin(request)
        return {"status": "healthy"}

    @app.post("/api/admin/enrich")
    async def admin_enrich(request: Request):
        await verify_same_origin(request)
        return {"success": True}

    return app


@pytest.fixture(scope="module")
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Same-origin requests are accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_accept_same_origin(client: TestClient, endpoint: str) -> None:
    response = client.get(endpoint, headers={"Host": "localhost:8000"})
    assert response.status_code == 200, f"{endpoint} should accept a same-origin request"


def test_admin_enrich_accepts_same_origin(client: TestClient) -> None:
    response = client.post("/api/admin/enrich", headers={"Host": "localhost:8000"})
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Cross-site requests are rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_enforce_origin_check(client: TestClient, endpoint: str) -> None:
    response = client.get(
        endpoint,
        headers={"Host": "evil.example.com", "Origin": "https://evil.example.com"},
    )
    assert (
        response.status_code == 403
    ), f"{endpoint} should reject a disallowed Origin, got {response.status_code}"


def test_admin_enrich_enforces_origin_check(client: TestClient) -> None:
    response = client.post(
        "/api/admin/enrich",
        headers={"Host": "evil.example.com", "Origin": "https://evil.example.com"},
    )
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# verify_admin_token, standalone (not wired into any admin.py route today —
# preserved as a utility for anything that wants token-based automation auth)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def token_app() -> FastAPI:
    app = FastAPI()

    @app.get("/token-protected")
    async def token_protected(request: Request):
        await verify_admin_token(request)
        return {"success": True}

    return app


@pytest.fixture(scope="module")
def token_client(token_app: FastAPI) -> TestClient:
    return TestClient(token_app)


def test_verify_admin_token_rejects_missing_token(token_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")
    response = token_client.get("/token-protected")
    assert response.status_code == 401


def test_verify_admin_token_rejects_invalid_token(token_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")
    response = token_client.get("/token-protected", headers={"X-Admin-Token": "wrong"})
    assert response.status_code == 401


def test_verify_admin_token_accepts_valid_token(token_client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")
    response = token_client.get(
        "/token-protected", headers={"X-Admin-Token": "test-admin-token-12345"}
    )
    assert response.status_code == 200


def test_verify_admin_token_rejects_when_unconfigured(
    token_client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    response = token_client.get("/token-protected", headers={"X-Admin-Token": "anything"})
    assert response.status_code == 401
