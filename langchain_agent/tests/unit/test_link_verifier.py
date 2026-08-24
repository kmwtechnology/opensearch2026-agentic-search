"""
Unit tests for link_verifier — LinkCache (TTL cache) and LinkVerifier (URL validation).
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import httpx
import pytest

from link_verifier import LinkCache, LinkVerifier


@pytest.mark.unit
class TestLinkCache:
    def test_get_returns_none_on_miss(self):
        cache = LinkCache()
        assert cache.get("https://example.com") is None

    def test_set_then_get_returns_cached_value(self):
        cache = LinkCache()
        cache.set("https://example.com", True)
        assert cache.get("https://example.com") is True

    def test_invalid_url_cached_as_false(self):
        cache = LinkCache()
        cache.set("https://broken.example.com", False)
        assert cache.get("https://broken.example.com") is False

    def test_expired_entry_returns_none(self):
        cache = LinkCache(ttl_minutes=60)
        url = "https://example.com"
        # Manually insert an entry with an old timestamp
        old_ts = datetime.now() - timedelta(minutes=61)
        cache.cache[url] = (True, old_ts)
        assert cache.get(url) is None

    def test_within_ttl_returns_value(self):
        cache = LinkCache(ttl_minutes=60)
        url = "https://example.com"
        recent_ts = datetime.now() - timedelta(minutes=30)
        cache.cache[url] = (True, recent_ts)
        assert cache.get(url) is True

    def test_clear_removes_all_entries(self):
        cache = LinkCache()
        cache.set("https://a.com", True)
        cache.set("https://b.com", False)
        cache.clear()
        assert cache.get("https://a.com") is None
        assert len(cache.cache) == 0

    def test_stats_returns_count_and_ttl(self):
        cache = LinkCache(ttl_minutes=30)
        cache.set("https://a.com", True)
        stats = cache.stats()
        assert stats["cached_urls"] == 1
        assert stats["ttl_minutes"] == 30


@pytest.mark.unit
class TestLinkVerifier:
    def _mock_response(self, status_code: int):
        resp = MagicMock()
        resp.status_code = status_code
        return resp

    def test_verify_url_returns_true_for_200(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = self._mock_response(200)
            mock_client_cls.return_value = mock_client

            is_valid, reason = verifier.verify_url("https://amazon.com/dp/B08")
            assert is_valid is True
            assert "200" in reason

    def test_verify_url_returns_false_for_404(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = self._mock_response(404)
            mock_client_cls.return_value = mock_client

            is_valid, reason = verifier.verify_url("https://amazon.com/dp/GONE")
            assert is_valid is False
            assert "404" in reason

    def test_verify_url_returns_false_on_timeout(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.side_effect = httpx.TimeoutException("timed out")
            mock_client_cls.return_value = mock_client

            is_valid, reason = verifier.verify_url("https://slow.example.com")
            assert is_valid is False
            assert "Timeout" in reason or "timeout" in reason.lower()

    def test_verify_url_returns_false_on_connect_error(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.side_effect = httpx.ConnectError("refused")
            mock_client_cls.return_value = mock_client

            is_valid, reason = verifier.verify_url("https://down.example.com")
            assert is_valid is False

    def test_verify_url_returns_false_for_empty_url(self):
        verifier = LinkVerifier()
        is_valid, reason = verifier.verify_url(None)
        assert is_valid is False
        assert "empty" in reason.lower()

    def test_verify_url_uses_cache_on_second_call(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.return_value = self._mock_response(200)
            mock_client_cls.return_value = mock_client

            url = "https://amazon.com/dp/B08"
            verifier.verify_url(url)
            verifier.verify_url(url)  # Second call should hit cache

            # HTTP call should only happen once
            assert mock_client.head.call_count == 1

    def test_verify_urls_returns_result_for_all(self):
        verifier = LinkVerifier()
        urls = ["https://a.com", "https://b.com"]

        with patch.object(verifier, "verify_url") as mock_verify:
            mock_verify.side_effect = lambda u: (
                (True, "Status 200") if "a" in u else (False, "Status 404")
            )
            results = verifier.verify_urls(urls)

        assert "https://a.com" in results
        assert "https://b.com" in results
        assert results["https://a.com"][0] is True
        assert results["https://b.com"][0] is False

    def test_verify_urls_empty_list_returns_empty_dict(self):
        verifier = LinkVerifier()
        assert verifier.verify_urls([]) == {}

    def test_get_stats_tracks_verified_and_failed(self):
        verifier = LinkVerifier()
        with patch("httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client.__enter__ = MagicMock(return_value=mock_client)
            mock_client.__exit__ = MagicMock(return_value=False)
            mock_client.head.side_effect = [
                self._mock_response(200),
                self._mock_response(404),
            ]
            mock_client_cls.return_value = mock_client

            verifier.verify_url("https://valid.com")
            verifier.verify_url("https://broken.com")

        stats = verifier.get_stats()
        assert stats["verified_count"] == 1
        assert stats["failed_count"] == 1
