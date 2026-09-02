"""
Real client IP resolution behind Cloud Run's proxy (issue #33).

slowapi's default ``get_remote_address`` reads ``request.client.host`` -- the
direct TCP peer. Behind Cloud Run that is *always* the internal load-balancer
address (``169.254.169.126`` in prod logs), so every caller shared one
rate-limit bucket and every auth log line recorded the proxy, not the user.

Cloud Run's frontend sets ``X-Forwarded-For`` with the originating client IP
as the first entry. Traffic only reaches this app through that frontend, so
trusting the first entry is safe in the deployed topology. Locally (no proxy)
the header is normally absent and we fall back to the socket peer, which is
what ``get_remote_address`` returned before.
"""

from slowapi.util import get_remote_address
from starlette.requests import HTTPConnection


def get_client_ip(request: HTTPConnection) -> str:
    """Return the originating client IP for an HTTP request *or* a WebSocket.

    Usable directly as a slowapi ``key_func`` and for log context. Accepts
    ``HTTPConnection`` (the shared base of ``Request`` and ``WebSocket``) so
    the same function keys rate limits and tags auth logs on both transports.
    """
    headers = getattr(request, "headers", None)
    forwarded = headers.get("x-forwarded-for") if headers is not None else None
    # isinstance guard: unit tests hand in MagicMock requests whose
    # ``headers.get`` returns a (truthy) MagicMock, not a string.
    if isinstance(forwarded, str):
        first = forwarded.split(",")[0].strip()
        if first:
            return first
    return get_remote_address(request)
