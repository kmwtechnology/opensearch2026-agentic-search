"""Unit tests for ``api/middleware/session_auth.py``.

Pure unit tests — no live HTTP, no SessionMiddleware. We hand the verifiers
a stub object with a ``session`` attribute that mimics the dict-like Starlette
exposes once SessionMiddleware is registered.

The login gate is OPTIONAL and off by default (REQUIRE_LOGIN, #103), so the
verifiers short-circuit to True unless it is switched on. Tests that exercise
gate BEHAVIOUR therefore turn it on explicitly via the ``login_gate_on``
autouse fixture; the tests at the bottom pin the off behaviour instead.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from api.middleware.session_auth import (
    WS_CLOSE_UNAUTHORIZED,
    _is_session_authenticated,
    verify_session,
    verify_websocket_session,
)


@pytest.fixture(autouse=True)
def login_gate_on(monkeypatch):
    """Most of this module tests what the gate does when it is enabled."""
    monkeypatch.setattr("core.config.REQUIRE_LOGIN", True, raising=False)


def _http_request(session=None, path: str = "/x", method: str = "GET"):
    req = MagicMock()
    req.session = session
    req.url.path = path
    req.method = method
    req.client.host = "1.2.3.4"
    return req


def _ws(session=None):
    ws = MagicMock()
    ws.session = session
    ws.client.host = "1.2.3.4"
    ws.close = AsyncMock()
    return ws


@pytest.mark.unit
class TestIsSessionAuthenticated:
    def test_returns_false_for_none(self) -> None:
        assert _is_session_authenticated(None) is False

    def test_returns_false_for_empty_dict(self) -> None:
        assert _is_session_authenticated({}) is False

    def test_returns_false_when_authenticated_missing(self) -> None:
        assert _is_session_authenticated({"other": "value"}) is False

    def test_returns_false_when_authenticated_falsy(self) -> None:
        assert _is_session_authenticated({"authenticated": False}) is False
        assert _is_session_authenticated({"authenticated": 0}) is False
        assert _is_session_authenticated({"authenticated": ""}) is False

    def test_returns_true_when_authenticated(self) -> None:
        assert _is_session_authenticated({"authenticated": True}) is True
        # We accept any truthy value — defensive against odd serialization
        assert _is_session_authenticated({"authenticated": 1}) is True

    def test_returns_false_for_non_mapping(self) -> None:
        assert _is_session_authenticated("not-a-mapping") is False
        assert _is_session_authenticated(12345) is False


@pytest.mark.unit
class TestVerifySession:
    @pytest.mark.asyncio
    async def test_authenticated_returns_true(self) -> None:
        req = _http_request(session={"authenticated": True})
        assert await verify_session(req) is True

    @pytest.mark.asyncio
    async def test_no_session_raises_401(self) -> None:
        req = _http_request(session=None)
        with pytest.raises(HTTPException) as exc_info:
            await verify_session(req)
        assert exc_info.value.status_code == 401
        assert exc_info.value.headers.get("WWW-Authenticate") == "Session"

    @pytest.mark.asyncio
    async def test_empty_session_raises_401(self) -> None:
        req = _http_request(session={})
        with pytest.raises(HTTPException) as exc_info:
            await verify_session(req)
        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_unauthenticated_session_raises_401(self) -> None:
        # A session exists (e.g. logout was called) but the flag was cleared
        req = _http_request(session={"authenticated": False})
        with pytest.raises(HTTPException) as exc_info:
            await verify_session(req)
        assert exc_info.value.status_code == 401


@pytest.mark.unit
class TestVerifyWebsocketSession:
    @pytest.mark.asyncio
    async def test_authenticated_returns_true_no_close(self) -> None:
        ws = _ws(session={"authenticated": True})
        assert await verify_websocket_session(ws) is True
        ws.close.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_session_closes_with_4401(self) -> None:
        ws = _ws(session=None)
        assert await verify_websocket_session(ws) is False
        ws.close.assert_awaited_once()
        kwargs = ws.close.await_args.kwargs
        assert kwargs["code"] == WS_CLOSE_UNAUTHORIZED == 4401

    @pytest.mark.asyncio
    async def test_unauthenticated_session_closes_with_4401(self) -> None:
        ws = _ws(session={"authenticated": False})
        assert await verify_websocket_session(ws) is False
        ws.close.assert_awaited_once()
        assert ws.close.await_args.kwargs["code"] == 4401


@pytest.mark.unit
class TestLoginGateDisabled:
    """With REQUIRE_LOGIN off there is no session to check and nothing to reject.

    This is the default: the shared-password screen put a password prompt
    between a presenter and their own demo. verify_same_origin still applies,
    so routes are open to same-origin callers rather than to the whole web.
    """

    @pytest.fixture(autouse=True)
    def _gate_off(self, monkeypatch):
        monkeypatch.setattr("core.config.REQUIRE_LOGIN", False, raising=False)

    @pytest.mark.asyncio
    async def test_http_request_without_a_session_is_allowed(self):
        assert await verify_session(_http_request(session=None)) is True

    @pytest.mark.asyncio
    async def test_websocket_without_a_session_is_accepted(self):
        ws = _ws(session=None)
        assert await verify_websocket_session(ws) is True
        ws.close.assert_not_called()
