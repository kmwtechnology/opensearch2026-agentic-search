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
        "https://evil.example.com",
        "http://evil.com",
        "https://not-run-app.com",
        "https://fake.run.app.evil.com",  # subdomain attack
        # There is no deployed target for this app — no domain, including a
        # former Cloud Run one, is exempt from the explicit allow-list.
        "https://my-service-abc123.a.run.app",
        "https://agentic-hybrid-search-123456789012.us-central1.run.app",
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
async def test_verify_same_origin_allows_via_host_fallback():
    # No origin/referer but host matches localhost:5173
    request = _make_request(host="localhost:5173")
    result = await verify_same_origin(request)
    assert result is True


@pytest.mark.asyncio
async def test_verify_same_origin_rejects_unknown_host_fallback():
    # No origin/referer and host doesn't match the explicit allow-list —
    # there's no deployed domain this app should ever trust by Host alone.
    request = _make_request(host="my-service.a.run.app")
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


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
# `Host` is the request's destination, not its source — a client can send
# any Origin header alongside a Host that matches this server. If
# verify_same_origin treated Host as a same-origin signal whenever Origin was
# disallowed, the entire origin allow-list would be defeated.
#
# This was the 2026-04-29 smoke failure root cause (against the app's former
# Cloud Run deployment, whose Host always matched *.run.app regardless of who
# sent the request):
#   GET /api/conversations  Origin: https://evil.example.com
#                           Host:   <service>.run.app
#   → returned 200 instead of 403.
#
# The contract: Host is consulted ONLY when both Origin and Referer are
# absent (the legitimate same-origin GET case where the browser omits Origin).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_same_origin_disallowed_origin_with_matching_host_rejected():
    """Disallowed Origin + a Host that would otherwise pass fallback MUST 403."""
    request = _make_request(
        origin="https://evil.example.com",
        host="localhost:5173",
    )
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_disallowed_referer_with_matching_host_rejected():
    """Disallowed Referer (no Origin) + a matching Host: Referer is authoritative."""
    request = _make_request(
        referer="https://evil.example.com/path",
        host="localhost:5173",
    )
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_verify_same_origin_no_origin_no_referer_unknown_host_rejected():
    """Same-origin GET (no Origin, no Referer) with an unknown Host is rejected."""
    request = _make_request(host="my-service.us-central1.run.app")
    with pytest.raises(HTTPException) as exc_info:
        await verify_same_origin(request)
    assert exc_info.value.status_code == 403


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
