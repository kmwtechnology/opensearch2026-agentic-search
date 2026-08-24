"""
Unit tests for retry_utils — retry decorators and helper functions.
"""

from unittest.mock import MagicMock, patch

import httpx
import psycopg
import pytest

from exceptions import DatabaseError, LLMError
from retry_utils import (
    is_transient_error,
    retry_database,
    retry_llm,
    retry_network,
    with_retry_context,
)


@pytest.mark.unit
class TestRetryDatabase:
    def test_succeeds_on_second_attempt(self):
        call_count = 0

        @retry_database(max_attempts=3, wait_min=0, wait_max=0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise psycopg.OperationalError("connection lost")
            return "ok"

        result = flaky()
        assert result == "ok"
        assert call_count == 2

    def test_raises_after_max_attempts_exhausted(self):
        @retry_database(max_attempts=2, wait_min=0, wait_max=0)
        def always_fails():
            raise psycopg.OperationalError("down")

        with pytest.raises(psycopg.OperationalError):
            always_fails()

    def test_retries_on_interface_error(self):
        call_count = 0

        @retry_database(max_attempts=3, wait_min=0, wait_max=0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise psycopg.InterfaceError("closed")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 2

    def test_does_not_retry_on_value_error(self):
        call_count = 0

        @retry_database(max_attempts=3, wait_min=0, wait_max=0)
        def bad_args():
            nonlocal call_count
            call_count += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError):
            bad_args()
        assert call_count == 1  # No retry for non-transient error


@pytest.mark.unit
class TestRetryLlm:
    def test_retries_on_timeout_exception(self):
        call_count = 0

        @retry_llm(max_attempts=3, wait_min=0, wait_max=0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.TimeoutException("timeout")
            return "response"

        assert flaky() == "response"
        assert call_count == 2

    def test_retries_on_connect_error(self):
        call_count = 0

        @retry_llm(max_attempts=3, wait_min=0, wait_max=0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("refused")
            return "response"

        assert flaky() == "response"

    def test_raises_after_max_attempts(self):
        @retry_llm(max_attempts=2, wait_min=0, wait_max=0)
        def always_fails():
            raise httpx.TimeoutException("timeout")

        with pytest.raises(httpx.TimeoutException):
            always_fails()


@pytest.mark.unit
class TestRetryNetwork:
    def test_retries_on_connect_error(self):
        call_count = 0

        @retry_network(max_attempts=3, wait_min=0, wait_max=0)
        def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise httpx.ConnectError("refused")
            return "ok"

        assert flaky() == "ok"
        assert call_count == 2

    def test_raises_after_max_attempts(self):
        @retry_network(max_attempts=2, wait_min=0, wait_max=0)
        def always_fails():
            raise OSError("DNS failure")

        with pytest.raises(OSError):
            always_fails()


@pytest.mark.unit
class TestIsTransientError:
    def test_timeout_exception_is_transient(self):
        assert is_transient_error(httpx.TimeoutException("t")) is True

    def test_connect_error_is_transient(self):
        assert is_transient_error(httpx.ConnectError("c")) is True

    def test_operational_error_is_transient(self):
        assert is_transient_error(psycopg.OperationalError()) is True

    def test_connection_error_is_transient(self):
        assert is_transient_error(ConnectionError()) is True

    def test_os_error_is_transient(self):
        assert is_transient_error(OSError()) is True

    def test_value_error_is_not_transient(self):
        assert is_transient_error(ValueError("bad")) is False

    def test_runtime_error_is_not_transient(self):
        assert is_transient_error(RuntimeError("crash")) is False


@pytest.mark.unit
class TestWithRetryContext:
    def test_converts_exception_to_custom_error_class(self):
        with pytest.raises(DatabaseError):
            with with_retry_context("db query", DatabaseError):
                raise RuntimeError("disk full")

    def test_re_raises_already_matching_error_class(self):
        with pytest.raises(DatabaseError):
            with with_retry_context("db query", DatabaseError):
                raise DatabaseError("already a db error")

    def test_wraps_non_matching_exception_into_error_class(self):
        # with_retry_context wraps ALL non-matching exceptions into error_class
        with pytest.raises(DatabaseError):
            with with_retry_context("db query", DatabaseError):
                raise ValueError("validation")

    def test_no_exception_passes_through(self):
        with with_retry_context("db query", DatabaseError):
            result = 1 + 1
        assert result == 2
