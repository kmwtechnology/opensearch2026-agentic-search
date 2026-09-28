"""
Client IP resolution for the local-only app (originally issue #33).

This app runs with no reverse proxy in front of it: the browser connects
directly to the container's mapped port. That means ``request.client.host``
(the direct TCP peer) *is* the real client, so this just wraps slowapi's
default ``get_remote_address``.

Deliberately does NOT trust ``X-Forwarded-For`` — with no proxy setting that
header, trusting a client-supplied value would let any caller spoof its own
address for rate-limiting and auth logs. If this app is ever run behind a
real reverse proxy again, that trust should be reintroduced narrowly (e.g.
only when a proxy env flag is set), not unconditionally.
"""

from slowapi.util import get_remote_address
from starlette.requests import HTTPConnection


def get_client_ip(request: HTTPConnection) -> str:
    """Return the originating client IP for an HTTP request *or* a WebSocket.

    Usable directly as a slowapi ``key_func`` and for log context. Accepts
    ``HTTPConnection`` (the shared base of ``Request`` and ``WebSocket``) so
    the same function keys rate limits and tags auth logs on both transports.
    """
    return get_remote_address(request)
