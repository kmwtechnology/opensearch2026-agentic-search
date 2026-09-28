"""
Unit tests for api/middleware/client_ip.get_client_ip (originally issue #33).

This app runs with no reverse proxy in front of it, so get_client_ip trusts
only the direct socket peer (request.client.host) and deliberately ignores
X-Forwarded-For — trusting a client-supplied header with no proxy setting it
would let any caller spoof its own address for rate-limiting and auth logs.
"""

from unittest.mock import MagicMock

import pytest
from starlette.requests import Request
from starlette.websockets import WebSocket

from api.middleware.client_ip import get_client_ip


def _scope(headers: dict | None = None, client=("10.0.0.5", 4321), scope_type: str = "http"):
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    return {
        "type": scope_type,
        "headers": raw_headers,
        "client": client,
        "method": "GET",
        "path": "/x",
        "query_string": b"",
    }


def _request(**kw) -> Request:
    return Request(_scope(**kw))


def _websocket(**kw) -> WebSocket:
    scope = _scope(scope_type="websocket", **kw)
    return WebSocket(scope, receive=MagicMock(), send=MagicMock())


@pytest.mark.unit
class TestGetClientIp:
    def test_ignores_x_forwarded_for_uses_direct_peer(self):
        # No reverse proxy in front of this app -- a client-supplied
        # X-Forwarded-For must NOT override the real socket peer.
        req = _request(
            headers={"X-Forwarded-For": "203.0.113.9, 169.254.169.126"},
            client=("10.0.0.5", 4321),
        )
        assert get_client_ip(req) == "10.0.0.5"

    def test_falls_back_to_peer_address_without_header(self):
        req = _request(client=("10.0.0.5", 4321))
        assert get_client_ip(req) == "10.0.0.5"

    def test_falls_back_to_loopback_when_no_client_at_all(self):
        # Mirrors slowapi's own get_remote_address fallback.
        req = _request(client=None)
        assert get_client_ip(req) == "127.0.0.1"

    def test_works_for_websocket_connections(self):
        ws = _websocket(
            headers={"X-Forwarded-For": "198.51.100.7"},
            client=("10.0.0.9", 1),
        )
        assert get_client_ip(ws) == "10.0.0.9"

    def test_two_direct_callers_get_distinct_keys(self):
        a = _request(client=("10.0.0.1", 40114))
        b = _request(client=("10.0.0.2", 40114))
        assert get_client_ip(a) != get_client_ip(b)

    def test_tolerates_magicmock_requests_used_by_other_unit_tests(self):
        # Other unit tests build MagicMock requests for get_client_ip callers.
        req = MagicMock()
        req.client.host = "1.2.3.4"
        assert get_client_ip(req) == "1.2.3.4"
