"""
Unit tests for api/middleware/client_ip.get_client_ip (issue #33).

Regression coverage for the Cloud Run proxy problem: slowapi's default
get_remote_address keyed every caller on the load balancer's own address,
collapsing all users into a single rate-limit bucket.
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
    def test_uses_first_x_forwarded_for_entry_behind_proxy(self):
        # Cloud Run prod shape: real client first, proxy hop(s) after.
        req = _request(
            headers={"X-Forwarded-For": "203.0.113.9, 169.254.169.126"},
            client=("169.254.169.126", 40114),
        )
        assert get_client_ip(req) == "203.0.113.9"

    def test_strips_whitespace_around_forwarded_entry(self):
        req = _request(headers={"X-Forwarded-For": "  203.0.113.9  ,10.0.0.1"})
        assert get_client_ip(req) == "203.0.113.9"

    def test_falls_back_to_peer_address_without_header(self):
        # Local dev / direct connections: no proxy, no header.
        req = _request(client=("10.0.0.5", 4321))
        assert get_client_ip(req) == "10.0.0.5"

    def test_falls_back_to_peer_when_header_is_blank(self):
        req = _request(headers={"X-Forwarded-For": "   "}, client=("10.0.0.5", 4321))
        assert get_client_ip(req) == "10.0.0.5"

    def test_falls_back_to_loopback_when_no_client_at_all(self):
        # Mirrors slowapi's own get_remote_address fallback.
        req = _request(client=None)
        assert get_client_ip(req) == "127.0.0.1"

    def test_works_for_websocket_connections(self):
        ws = _websocket(
            headers={"X-Forwarded-For": "198.51.100.7"},
            client=("169.254.169.126", 1),
        )
        assert get_client_ip(ws) == "198.51.100.7"

    def test_two_proxied_callers_get_distinct_keys(self):
        """The actual #33 failure mode: two different users behind the same
        proxy must NOT share a rate-limit key."""
        proxy = ("169.254.169.126", 40114)
        a = _request(headers={"X-Forwarded-For": "203.0.113.1"}, client=proxy)
        b = _request(headers={"X-Forwarded-For": "203.0.113.2"}, client=proxy)
        assert get_client_ip(a) != get_client_ip(b)

    def test_tolerates_magicmock_requests_used_by_other_unit_tests(self):
        # test_session_auth.py builds MagicMock requests; headers.get returns a
        # MagicMock (truthy, not a str) -- must fall through to client.host.
        req = MagicMock()
        req.client.host = "1.2.3.4"
        assert get_client_ip(req) == "1.2.3.4"
