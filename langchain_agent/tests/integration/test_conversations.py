"""
Integration tests for /api/conversations — list, get, and delete endpoints.

PostgreSQL is fully mocked. Origin auth is bypassed by sending a localhost
Origin header that matches the allowed-origins list in origin_auth.py.

Session auth (PR #8 / feat/login-gate) is bypassed at fixture-build time by
monkeypatching ``verify_session`` to a no-op. The session-cookie contract
is exercised independently in ``tests/unit/test_auth_routes.py`` and
``tests/unit/test_session_auth.py``; duplicating it here would mean every
integration test had to perform a login round-trip, which a) costs an
extra request per test, b) interacts badly with the 5/min login rate
limit, and c) couples integration tests to LOGIN_PASSWORD env state.
"""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from api.main import app

ORIGIN = "http://localhost:5173"
HEADERS = {"origin": ORIGIN}


@pytest.fixture(autouse=True)
def _bypass_session_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-op verify_session for every test in this module.

    The session middleware is still wired into the app, but the dependency
    short-circuits to True so route logic runs against the mocked DB.
    """
    monkeypatch.setattr("api.routes.conversations.verify_session", AsyncMock(return_value=True))


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def _mock_conn(rows=None, rowcount=1):
    """Return a mock psycopg connection whose cursor returns `rows` on fetchall/fetchone."""
    rows = rows or []
    mock_cur = MagicMock()
    mock_cur.__enter__ = MagicMock(return_value=mock_cur)
    mock_cur.__exit__ = MagicMock(return_value=False)
    mock_cur.fetchall.return_value = rows
    mock_cur.fetchone.return_value = rows[0] if rows else None
    mock_cur.rowcount = rowcount

    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cur
    mock_conn.autocommit = False
    return mock_conn


# ---------------------------------------------------------------------------
# GET /api/conversations
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestListConversations:
    @patch("api.routes.conversations.psycopg.connect")
    def test_returns_list_of_conversations(self, mock_connect, client):
        now = datetime(2026, 4, 29, 10, 0, 0)
        rows = [
            ("thread_abc", "Headphone Search", now, now),
            ("thread_def", "Laptop Compare", now, None),
        ]
        mock_connect.return_value = _mock_conn(rows)

        r = client.get("/api/conversations", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert len(body) == 2
        assert body[0]["thread_id"] == "thread_abc"
        assert body[0]["title"] == "Headphone Search"

    @patch("api.routes.conversations.psycopg.connect")
    def test_empty_db_returns_empty_list(self, mock_connect, client):
        mock_connect.return_value = _mock_conn([])
        r = client.get("/api/conversations", headers=HEADERS)
        assert r.status_code == 200
        assert r.json() == []

    @patch("api.routes.conversations.psycopg.connect")
    def test_limit_parameter_passed_to_query(self, mock_connect, client):
        mock_connect.return_value = _mock_conn([])
        r = client.get("/api/conversations?limit=5", headers=HEADERS)
        assert r.status_code == 200

    def test_missing_origin_blocked(self, client):
        r = client.get("/api/conversations")
        assert r.status_code == 403

    @patch("api.routes.conversations.psycopg.connect")
    def test_db_error_returns_500(self, mock_connect, client):
        mock_connect.side_effect = Exception("DB unavailable")
        r = client.get("/api/conversations", headers=HEADERS)
        assert r.status_code == 500


# ---------------------------------------------------------------------------
# GET /api/conversations/{thread_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestGetConversation:
    @patch("api.routes.conversations.psycopg.connect")
    def test_returns_conversation_detail(self, mock_connect, client):
        now = datetime(2026, 4, 29, 10, 0, 0)
        mock_conn = _mock_conn()
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value

        # fetchone returns metadata row, then None for blob
        mock_cur.fetchone.side_effect = [
            ("Headphone Search", now),  # metadata
            None,  # no blob
        ]
        mock_connect.return_value = mock_conn

        r = client.get("/api/conversations/thread_abc", headers=HEADERS)
        assert r.status_code == 200
        body = r.json()
        assert body["thread_id"] == "thread_abc"
        assert body["title"] == "Headphone Search"
        assert isinstance(body["messages"], list)

    @patch("api.routes.conversations.psycopg.connect")
    def test_unknown_thread_returns_404(self, mock_connect, client):
        mock_conn = _mock_conn()
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.fetchone.return_value = None  # No metadata row
        mock_connect.return_value = mock_conn

        r = client.get("/api/conversations/thread_missing", headers=HEADERS)
        assert r.status_code == 404

    def test_invalid_thread_id_format_returns_400(self, client):
        # Thread IDs must be alphanumeric/underscore/hyphen; spaces are invalid
        r = client.get("/api/conversations/invalid id here", headers=HEADERS)
        assert r.status_code in (400, 422)

    def test_missing_origin_blocked(self, client):
        r = client.get("/api/conversations/thread_abc")
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/conversations/{thread_id}
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestDeleteConversation:
    @patch("api.routes.conversations.psycopg.connect")
    def test_delete_existing_returns_204(self, mock_connect, client):
        mock_conn = _mock_conn()
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.rowcount = 1  # One row deleted from metadata
        mock_connect.return_value = mock_conn

        r = client.delete("/api/conversations/thread_abc", headers=HEADERS)
        assert r.status_code == 204

    @patch("api.routes.conversations.psycopg.connect")
    def test_delete_unknown_thread_returns_404(self, mock_connect, client):
        mock_conn = _mock_conn()
        mock_cur = mock_conn.cursor.return_value.__enter__.return_value
        mock_cur.rowcount = 0  # Nothing deleted
        mock_connect.return_value = mock_conn

        r = client.delete("/api/conversations/thread_missing", headers=HEADERS)
        assert r.status_code == 404

    def test_invalid_thread_id_format_returns_400(self, client):
        # Thread IDs must be alphanumeric/underscore/hyphen; ! is invalid
        r = client.delete("/api/conversations/invalid!thread", headers=HEADERS)
        assert r.status_code in (400, 422)

    def test_missing_origin_blocked(self, client):
        r = client.delete("/api/conversations/thread_abc")
        assert r.status_code == 403
