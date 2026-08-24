"""
Link Verification Module - Validates citation URLs and tracks their status.

This module provides fast, cached URL validation to ensure all citations
are working before sending documents to the LLM. Features:
- Concurrent URL checking for performance
- In-memory cache with TTL
- Graceful timeout handling
- Detailed logging of verification results
"""

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

import httpx

logger = logging.getLogger(__name__)


class LinkCache:
    """
    In-memory cache for URL verification results with TTL.

    Stores verification status for URLs with automatic expiration.
    Thread-safe implementation for concurrent access.
    """

    def __init__(self, ttl_minutes: int = 60):
        self.ttl_minutes = ttl_minutes
        self.cache: Dict[str, Tuple[bool, datetime]] = {}
        self._lock = threading.Lock()

    def get(self, url: str) -> Optional[bool]:
        """
        Get cached result for URL (if not expired).

        Args:
            url: URL to check

        Returns:
            True (valid), False (invalid), or None (not cached or expired)
        """
        with self._lock:
            if url not in self.cache:
                return None

            is_valid, timestamp = self.cache[url]

            # Check if cache entry is expired
            if datetime.now() - timestamp > timedelta(minutes=self.ttl_minutes):
                del self.cache[url]
                return None

            return is_valid

    def set(self, url: str, is_valid: bool) -> None:
        """
        Cache a verification result.

        Args:
            url: URL that was verified
            is_valid: Whether the URL is valid (returned 200-299)
        """
        with self._lock:
            self.cache[url] = (is_valid, datetime.now())

    def clear(self) -> None:
        """Clear all cached entries."""
        with self._lock:
            self.cache.clear()

    def stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        with self._lock:
            return {
                "cached_urls": len(self.cache),
                "ttl_minutes": self.ttl_minutes,
            }


class LinkVerifier:
    """
    Verifies URLs are accessible and returns valid status.

    Features:
    - Parallel verification of multiple URLs
    - Smart caching to avoid repeated checks
    - Timeout handling (prevents hanging on slow servers)
    - Comprehensive error logging
    - Returns verification status + reasoning
    """

    def __init__(self, timeout_ms: int = 2000, cache_ttl_minutes: int = 60):
        """
        Initialize link verifier.

        Args:
            timeout_ms: Timeout per URL check in milliseconds (default: 2000)
            cache_ttl_minutes: Cache TTL in minutes (default: 60)
        """
        self.timeout_seconds = timeout_ms / 1000.0
        self.cache = LinkCache(ttl_minutes=cache_ttl_minutes)
        self.verified_count = 0
        self.failed_count = 0
        self._counter_lock = threading.Lock()  # Thread-safe counter updates

    def verify_url(self, url: Optional[str]) -> Tuple[bool, str]:
        """
        Verify a single URL is accessible.

        Args:
            url: URL to verify

        Returns:
            Tuple of (is_valid, reason_string)
        """
        # Handle missing/empty URL
        if not url:
            return False, "URL is empty"

        # Check cache first
        cached_result = self.cache.get(url)
        if cached_result is not None:
            status = "valid" if cached_result else "invalid"
            return cached_result, f"Cached ({status})"

        # Perform verification
        try:
            with httpx.Client(timeout=self.timeout_seconds, follow_redirects=True) as client:
                response = client.head(url)

                # 200-299 = success
                is_valid = 200 <= response.status_code < 300

                if is_valid:
                    with self._counter_lock:
                        self.verified_count += 1
                    self.cache.set(url, True)
                    return True, f"Status {response.status_code}"
                else:
                    with self._counter_lock:
                        self.failed_count += 1
                    self.cache.set(url, False)
                    return False, f"Status {response.status_code}"

        except httpx.TimeoutException:
            with self._counter_lock:
                self.failed_count += 1
            self.cache.set(url, False)
            return False, f"Timeout (>{self.timeout_seconds}s)"

        except httpx.ConnectError:
            with self._counter_lock:
                self.failed_count += 1
            self.cache.set(url, False)
            return False, "Connection failed"

        except httpx.RequestError as e:
            with self._counter_lock:
                self.failed_count += 1
            self.cache.set(url, False)
            return False, f"Request error: {str(e)[:50]}"

        except Exception as e:
            with self._counter_lock:
                self.failed_count += 1
            self.cache.set(url, False)
            logger.warning(f"Unexpected error verifying {url}: {e}")
            return False, f"Error: {type(e).__name__}"

    def verify_urls(self, urls: list[str], max_workers: int = 5) -> Dict[str, Tuple[bool, str]]:
        """
        Verify multiple URLs concurrently.

        Args:
            urls: List of URLs to verify
            max_workers: Number of concurrent threads (default: 5)

        Returns:
            Dict mapping URL -> (is_valid, reason)
        """
        if not urls:
            return {}

        results = {}

        # Use thread pool for concurrent verification
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_url = {executor.submit(self.verify_url, url): url for url in urls}

            for future in as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    is_valid, reason = future.result()
                    results[url] = (is_valid, reason)
                except Exception as e:
                    logger.error(f"Error verifying {url}: {e}")
                    results[url] = (False, f"Verification failed: {str(e)[:50]}")

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get verification statistics."""
        with self._counter_lock:
            return {
                "verified_count": self.verified_count,
                "failed_count": self.failed_count,
                "cache": self.cache.stats(),
            }
