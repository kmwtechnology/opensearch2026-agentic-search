"""Contract tests for ``/api/auth/*`` routes.

Wires a real FastAPI app with SessionMiddleware + the auth router and drives
it via TestClient (no network, no Cloud Run). Validates:
* `POST /login` round-trips the session cookie
* wrong password returns 401 without setting the cookie
* `GET /status` reflects the current session
* `POST /logout` clears the session
* a missing `LOGIN_PASSWORD` returns 503 (server misconfigured)
* origin enforcement still applies (disallowed Origin → 403)
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from api.routes import auth as auth_routes


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    """Build a fresh app per test so cookie state doesn't leak."""
    monkeypatch.setattr(auth_routes, "LOGIN_PASSWORD", "demo-password")
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="x" * 64,
        session_cookie="ahs_session",
        https_only=False,  # TestClient uses http://
        same_site="lax",
        max_age=86400,
    )
    app.include_router(auth_routes.router, prefix="/api")
    return app


@pytest.fixture
def client(app: FastAPI) -> TestClient:
    # TestClient requires a non-empty base URL; an allowed Origin is sent on
    # every request so the origin check passes.
    return TestClient(app, base_url="http://localhost:5173")


ALLOWED = {"Origin": "http://localhost:5173"}


@pytest.mark.unit
class TestLogin:
    def test_correct_password_sets_cookie(self, client: TestClient) -> None:
        resp = client.post("/api/auth/login", json={"password": "demo-password"}, headers=ALLOWED)
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": True}
        # Cookie was set on the client jar; use it on a follow-up status call
        status = client.get("/api/auth/status", headers=ALLOWED)
        assert status.status_code == 200
        assert status.json() == {"authenticated": True}

    def test_wrong_password_returns_401(self, client: TestClient) -> None:
        resp = client.post("/api/auth/login", json={"password": "nope"}, headers=ALLOWED)
        assert resp.status_code == 401
        # Status should still report unauthenticated
        status = client.get("/api/auth/status", headers=ALLOWED)
        assert status.json() == {"authenticated": False}

    def test_missing_password_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/auth/login", json={}, headers=ALLOWED)
        # Pydantic validation error before the route runs
        assert resp.status_code == 422

    def test_empty_password_returns_422(self, client: TestClient) -> None:
        resp = client.post("/api/auth/login", json={"password": ""}, headers=ALLOWED)
        assert resp.status_code == 422

    def test_disallowed_origin_returns_403(self, client: TestClient) -> None:
        resp = client.post(
            "/api/auth/login",
            json={"password": "demo-password"},
            headers={"Origin": "https://evil.example.com"},
        )
        assert resp.status_code == 403

    def test_unconfigured_password_returns_503(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(auth_routes, "LOGIN_PASSWORD", None)
        resp = client.post("/api/auth/login", json={"password": "anything"}, headers=ALLOWED)
        assert resp.status_code == 503


@pytest.mark.unit
class TestLogout:
    def test_logout_clears_session(self, client: TestClient) -> None:
        client.post("/api/auth/login", json={"password": "demo-password"}, headers=ALLOWED)
        assert client.get("/api/auth/status", headers=ALLOWED).json() == {"authenticated": True}
        resp = client.post("/api/auth/logout", headers=ALLOWED)
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": False}
        assert client.get("/api/auth/status", headers=ALLOWED).json() == {"authenticated": False}

    def test_logout_when_not_logged_in_is_idempotent(self, client: TestClient) -> None:
        resp = client.post("/api/auth/logout", headers=ALLOWED)
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": False}


@pytest.mark.unit
class TestStatus:
    def test_unauthenticated_initial_status(self, client: TestClient) -> None:
        resp = client.get("/api/auth/status", headers=ALLOWED)
        assert resp.status_code == 200
        assert resp.json() == {"authenticated": False}

    def test_disallowed_origin_returns_403(self, client: TestClient) -> None:
        resp = client.get("/api/auth/status", headers={"Origin": "https://evil.example.com"})
        assert resp.status_code == 403


@pytest.mark.unit
class TestPasswordCompareTimingShape:
    """The login route must use ``hmac.compare_digest`` for the password check.

    Static source check — runtime mocking of compare_digest would be cleaner
    but slowapi's per-IP login rate limit (5/min) is shared across tests in
    this module and would 429 the spy probe.
    """

    def test_login_source_uses_compare_digest(self) -> None:
        import inspect

        source = inspect.getsource(auth_routes.login)
        assert "hmac.compare_digest" in source, (
            "POST /api/auth/login must use hmac.compare_digest for the password "
            "check, not ==. Constant-time comparison defeats remote timing oracles."
        )
