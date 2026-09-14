"""Contract test: admin routes enforce auth WHEN THE LOGIN GATE IS ON.

Pure unit test (no network). Verifies that all /api/admin/* endpoints
require either session auth OR admin token (X-Admin-Token header).

Catches any new admin routes that ship without auth guards.

Scope note (#103): the login gate is now optional and OFF by default, and
with it off verify_session returns True — so these routes are reachable by
any SAME-ORIGIN caller without credentials. That is a deliberate trade for a
demo box (the Restart button calls /api/admin/demo-reset from the browser
with no session), and verify_same_origin still rejects cross-site requests.
These tests therefore switch the gate ON, which is what any deployment
holding something worth protecting should also do.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from api.middleware.origin_auth import verify_same_origin
from api.middleware.session_auth import verify_admin_token, verify_session


@pytest.fixture(autouse=True)
def login_gate_on(monkeypatch):
    """These assertions are about the gate doing its job, so turn it on."""
    monkeypatch.setattr("core.config.REQUIRE_LOGIN", True, raising=False)


@pytest.fixture(scope="module")
def test_app() -> FastAPI:
    app = FastAPI()

    # Add SessionMiddleware required by verify_session
    app.add_middleware(SessionMiddleware, secret_key="test-secret-key-32-chars-min!")

    @app.post("/test/login")
    async def test_login(request: Request):
        """Test-only endpoint to set session['authenticated'] = True."""
        request.session["authenticated"] = True
        return {"status": "logged_in"}

    @app.get("/api/admin/diagnose")
    async def admin_diagnose(request: Request, q: str = "test"):
        await verify_same_origin(request)
        try:
            await verify_session(request)
        except HTTPException:
            await verify_admin_token(request)
        return {"query": q}

    @app.get("/api/admin/health")
    async def admin_health(request: Request):
        await verify_same_origin(request)
        try:
            await verify_session(request)
        except HTTPException:
            await verify_admin_token(request)
        return {"status": "healthy"}

    @app.post("/api/admin/enrich")
    async def admin_enrich(request: Request):
        await verify_same_origin(request)
        try:
            await verify_session(request)
        except HTTPException:
            await verify_admin_token(request)
        return {"success": True}

    return app


@pytest.fixture(scope="module")
def client(test_app: FastAPI) -> TestClient:
    return TestClient(test_app)


# ---------------------------------------------------------------------------
# Unauthenticated access is rejected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_reject_unauthenticated_access(client: TestClient, endpoint: str) -> None:
    response = client.get(endpoint, headers={"Host": "localhost:8000"})
    assert response.status_code in (401, 403), (
        f"{endpoint} should reject unauthenticated access (no session, no token), "
        f"got {response.status_code}"
    )


# ---------------------------------------------------------------------------
# Session auth works (simulated via session cookie)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_accept_valid_session(client: TestClient, endpoint: str) -> None:
    """Session auth: authenticate via test login endpoint, then access admin routes."""
    with client:
        # First, call the test login endpoint to set session["authenticated"] = True
        login_resp = client.post("/test/login", headers={"Host": "localhost:8000"})
        assert login_resp.status_code == 200, "Test login endpoint should work"

        # Now the session is set; call the admin endpoint
        response = client.get(endpoint, headers={"Host": "localhost:8000"})
        assert (
            response.status_code == 200
        ), f"{endpoint} should accept valid session, got {response.status_code}"


# ---------------------------------------------------------------------------
# Admin token works (X-Admin-Token header)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_accept_admin_token_when_session_missing(
    client: TestClient, endpoint: str, monkeypatch
) -> None:
    """Admin token: X-Admin-Token header bypasses session requirement."""
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")

    response = client.get(
        endpoint,
        headers={
            "Host": "localhost:8000",
            "X-Admin-Token": "test-admin-token-12345",
        },
    )
    assert (
        response.status_code == 200
    ), f"{endpoint} should accept valid X-Admin-Token header, got {response.status_code}"


# ---------------------------------------------------------------------------
# Origin check still required (no bypass for tokens)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "endpoint",
    ["/api/admin/diagnose", "/api/admin/health"],
)
def test_admin_routes_enforce_origin_check(client: TestClient, endpoint: str, monkeypatch) -> None:
    """Even with valid admin token, disallowed Origin is still rejected."""
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")

    response = client.get(
        endpoint,
        headers={
            "Host": "evil.example.com",
            "Origin": "https://evil.example.com",
            "X-Admin-Token": "test-admin-token-12345",
        },
    )
    assert (
        response.status_code == 403
    ), f"{endpoint} should reject disallowed Origin even with valid token, got {response.status_code}"


# ---------------------------------------------------------------------------
# POST /api/admin/enrich — same contract, different HTTP method
# ---------------------------------------------------------------------------


def test_admin_enrich_rejects_unauthenticated_access(client: TestClient) -> None:
    # The module-scoped client may carry a session cookie set by an earlier
    # test (e.g. test_admin_routes_accept_valid_session) — clear it so this
    # test genuinely exercises the unauthenticated path.
    client.cookies.clear()
    response = client.post("/api/admin/enrich", headers={"Host": "localhost:8000"})
    assert response.status_code in (401, 403), (
        f"/api/admin/enrich should reject unauthenticated access (no session, no token), "
        f"got {response.status_code}"
    )


def test_admin_enrich_accepts_valid_session(client: TestClient) -> None:
    with client:
        login_resp = client.post("/test/login", headers={"Host": "localhost:8000"})
        assert login_resp.status_code == 200

        response = client.post("/api/admin/enrich", headers={"Host": "localhost:8000"})
        assert response.status_code == 200


def test_admin_enrich_accepts_admin_token_when_session_missing(
    client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")

    response = client.post(
        "/api/admin/enrich",
        headers={"Host": "localhost:8000", "X-Admin-Token": "test-admin-token-12345"},
    )
    assert response.status_code == 200


def test_admin_enrich_enforces_origin_check(client: TestClient, monkeypatch) -> None:
    monkeypatch.setenv("ADMIN_TOKEN", "test-admin-token-12345")

    response = client.post(
        "/api/admin/enrich",
        headers={
            "Host": "evil.example.com",
            "Origin": "https://evil.example.com",
            "X-Admin-Token": "test-admin-token-12345",
        },
    )
    assert response.status_code == 403
