"""
Unit tests for api/middleware/origin_auth.py.

All tests are pure unit tests — no network calls, no FastAPI app.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from api.middleware.origin_auth import (
    get_allowed_origins,
    is_allowed_origin,
    verify_same_origin,
    verify_websocket_origin,
)

# ---------------------------------------------------------------------------
# get_allowed_origins
# ---------------------------------------------------------------------------


def test_get_allowed_origins_returns_localhost_variants():
    origins = get_allowed_origins()
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins


def test_get_allowed_origins_returns_list():
    origins = get_allowed_origins()
    assert isinstance(origins, list)
    assert len(origins) > 0


# ---------------------------------------------------------------------------
# is_allowed_origin — origin header
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:3000",
        "http://localhost:8080",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
)
def test_is_allowed_origin_accepts_dev_origins(origin):
    assert is_allowed_origin(origin) is True


@pytest.mark.parametrize(
    "origin",
    [
        "https://my-service-abc123.a.run.app",
        "https://agentic-hybrid-search-375500751528.us-central1.run.app",
        "https://anything.a.run.app",
    ],
)
def test_is_allowed_origin_accepts_cloud_run_domains(origin):
    assert is_allowed_origin(origin) is True


@pytest.mark.parametrize(
    "origin",
    [
        "https://evil.example.com",
        "http://evil.com",
        "https://not-run-app.com",
        "https://fake.run.app.evil.com",  # subdomain attack
    ],
)
def test_is_allowed_origin_rejects_unknown_origins(origin):
    assert is_allowed_origin(origin) is False


def test_is_allowed_origin_none_origin_no_referer():
    assert is_allowed_origin(None) is False


def test_is_allowed_origin_empty_string_no_referer():
    # empty string is falsy — falls through to referer check
    assert is_allowed_origin("") is False


# ---------------------------------------------------------------------------
# is_allowed_origin — referer fallback
# ---------------------------------------------------------------------------


def test_is_allowed_origin_uses_referer_when_origin_absent():
    assert is_allowed_origin(None, referer="http://localhost:5173/some/path") is True


def test_is_allowed_origin_referer_cloud_run():
    assert is_allowed_origin(None, referer="https://my-service.a.run.app/dashboard") is True


def test_is_allowed_origin_referer_unknown_host_rejected():
    assert is_allowed_origin(None, referer="https://evil.com/path") is False


def test_is_allowed_origin_origin_takes_priority_over_referer():
    # Good origin + bad referer → allowed
    assert is_allowed_origin("http://localhost:5173", referer="https://evil.com/") is True


def test_is_allowed_origin_bad_origin_good_referer():
    # When origin is present but not allowed, the code falls through to the referer check.
    # A good referer after a bad origin still grants access (by design — referer is the fallback).
    assert is_allowed_origin("https://evil.com", referer="http://localhost:5173/") is True


# ---------------------------------------------------------------------------
# verify_same_origin — async
# ---------------------------------------------------------------------------


def _make_request(origin=None, referer=None, host=None):
    request = MagicMock()
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    if referer is not None:
        headers["referer"] = referer
    if host is not None:
        headers["host"] = host
    request.headers.get = lambda key, default=None: headers.get(key, default)
    request.method = "GET"
    return request


@pytest.mark.asyncio
async def test_verify_same_origin_allows_localhost():
    request = _make_request(origin="http://localhost:5173")
    result = await verify_same_origin(request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_same_origin_allows_cloud_run():
    request = _make_request(origin="https://my-service.a.run.app")
    result = await verify_same_origin(request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_same_origin_allows_via_host_fallback():
    # No origin/referer but host matches localhost:5173
    request = _make_request(host="localhost:5173")
    result = await verify_same_origin(request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_same_origin_allows_cloud_run_host():
    request = _make_request(host="my-service.a.run.app")
    result = await verify_same_origin(request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_same_origin_raises_403_for_unknown():
    request = _make_request(origin="https://evil.example.com")
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_raises_403_no_headers():
    request = _make_request()
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


# ---------------------------------------------------------------------------
# Regression: Host fallback must NOT override an explicit disallowed Origin.
#
# On Cloud Run, `Host` is the destination domain (e.g.
# "agentic-hybrid-search-375500751528.us-central1.run.app") and matches
# *.run.app on every request regardless of who sent it. If verify_same_origin
# treated Host as a same-origin signal whenever Origin was disallowed, the
# entire origin allow-list would be defeated for the production deployment.
#
# This was the 2026-04-29 smoke failure root cause:
#   GET /api/conversations  Origin: https://evil.example.com
#                           Host:   <service>.run.app
#   → returned 200 instead of 403.
#
# The contract: Host is consulted ONLY when both Origin and Referer are
# absent (the legitimate same-origin GET case where the browser omits Origin).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_same_origin_disallowed_origin_with_run_app_host_rejected():
    """The smoke-test regression: disallowed Origin + Cloud Run Host MUST 403."""
    request = _make_request(
        origin="https://evil.example.com",
        host="agentic-hybrid-search-375500751528.us-central1.run.app",
    )
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_disallowed_origin_with_localhost_host_rejected():
    request = _make_request(origin="https://evil.example.com", host="localhost:5173")
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_disallowed_referer_with_run_app_host_rejected():
    """Disallowed Referer (no Origin) + Cloud Run Host: Referer is authoritative."""
    request = _make_request(
        referer="https://evil.example.com/path",
        host="my-service.us-central1.run.app",
    )
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_no_origin_no_referer_run_app_host_allowed():
    """Same-origin GET (no Origin, no Referer) with Cloud Run Host falls through to host fallback."""
    request = _make_request(host="my-service.us-central1.run.app")
    result = await verify_same_origin(request)
    assert result is True


# ---------------------------------------------------------------------------
# verify_websocket_origin — async
# ---------------------------------------------------------------------------


def _make_websocket(origin=None, referer=None):
    ws = MagicMock()
    ws.close = AsyncMock()
    headers = {}
    if origin is not None:
        headers["origin"] = origin
    if referer is not None:
        headers["referer"] = referer
    ws.headers.get = lambda key, default=None: headers.get(key, default)
    return ws


@pytest.mark.asyncio
async def test_verify_websocket_origin_allows_localhost():
    ws = _make_websocket(origin="http://localhost:5173")
    result = await verify_websocket_origin(ws)
    assert result is True
    ws.close.assert_not_called()


@pytest.mark.asyncio
async def test_verify_websocket_origin_closes_unknown():
    ws = _make_websocket(origin="https://evil.example.com")
    result = await verify_websocket_origin(ws)
    assert result is False
    ws.close.assert_called_once()
    call_kwargs = ws.close.call_args[1]
    assert call_kwargs["code"] == 4003
    assert isinstance(call_kwargs["reason"], str)


@pytest.mark.asyncio
async def test_verify_websocket_origin_closes_no_origin():
    ws = _make_websocket()
    result = await verify_websocket_origin(ws)
    assert result is False
    ws.close.assert_called_once()
