"""
Retry utilities for handling transient failures.

Provides configurable retry decorators and wrappers for:
- Database operations
- LLM API calls
- Network requests (link verification)

Uses tenacity for robust retry logic with exponential backoff.
"""

import logging
from functools import wraps
from typing import Any, Callable, Tuple, Type

from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from exceptions import (
    DatabaseError,
    LinkVerificationError,
    LLMError,
    RetrievalError,
)

logger = logging.getLogger(__name__)


# ============================================================================
# RETRY CONFIGURATIONS
# ============================================================================

# Database retry: 3 attempts, 1-4 second backoff
DB_RETRY_ATTEMPTS = 3
DB_RETRY_WAIT_MIN = 1
DB_RETRY_WAIT_MAX = 4

# LLM retry: 2 attempts, 2-8 second backoff (LLM calls are slow)
LLM_RETRY_ATTEMPTS = 2
LLM_RETRY_WAIT_MIN = 2
LLM_RETRY_WAIT_MAX = 8

# Network retry: 3 attempts, 0.5-2 second backoff
NETWORK_RETRY_ATTEMPTS = 3
NETWORK_RETRY_WAIT_MIN = 0.5
NETWORK_RETRY_WAIT_MAX = 2


# ============================================================================
# RETRY DECORATORS
# ============================================================================


def retry_database(
    max_attempts: int = DB_RETRY_ATTEMPTS,
    wait_min: float = DB_RETRY_WAIT_MIN,
    wait_max: float = DB_RETRY_WAIT_MAX,
):
    """
    Retry decorator for database operations.

    Catches common transient database errors:
    - psycopg connection errors
    - Operational errors
    - Timeout errors

    Args:
        max_attempts: Maximum retry attempts (default: 3)
        wait_min: Minimum wait time in seconds (default: 1)
        wait_max: Maximum wait time in seconds (default: 4)

    Usage:
        @retry_database()
        def get_documents(conn, query):
            ...
    """
    import psycopg

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        retry=retry_if_exception_type(
            (
                psycopg.OperationalError,
                psycopg.InterfaceError,
                ConnectionError,
                TimeoutError,
            )
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_llm(
    max_attempts: int = LLM_RETRY_ATTEMPTS,
    wait_min: float = LLM_RETRY_WAIT_MIN,
    wait_max: float = LLM_RETRY_WAIT_MAX,
):
    """
    Retry decorator for LLM API calls.

    Catches common transient LLM errors:
    - Connection timeouts
    - Rate limiting
    - Temporary service unavailability

    Args:
        max_attempts: Maximum retry attempts (default: 2)
        wait_min: Minimum wait time in seconds (default: 2)
        wait_max: Maximum wait time in seconds (default: 8)

    Usage:
        @retry_llm()
        def generate_response(llm, messages):
            ...
    """
    import httpx

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.ConnectError,
                ConnectionError,
                TimeoutError,
            )
        ),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )


def retry_network(
    max_attempts: int = NETWORK_RETRY_ATTEMPTS,
    wait_min: float = NETWORK_RETRY_WAIT_MIN,
    wait_max: float = NETWORK_RETRY_WAIT_MAX,
):
    """
    Retry decorator for network requests (link verification, etc).

    Catches common transient network errors:
    - Connection errors
    - Timeouts
    - DNS failures

    Args:
        max_attempts: Maximum retry attempts (default: 3)
        wait_min: Minimum wait time in seconds (default: 0.5)
        wait_max: Maximum wait time in seconds (default: 2)

    Usage:
        @retry_network()
        def fetch_url(url):
            ...
    """
    import httpx

    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=0.5, min=wait_min, max=wait_max),
        retry=retry_if_exception_type(
            (
                httpx.TimeoutException,
                httpx.ConnectError,
                ConnectionError,
                TimeoutError,
                OSError,  # Catches DNS failures
            )
        ),
        before_sleep=before_sleep_log(logger, logging.DEBUG),
        reraise=True,
    )


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def with_retry_context(
    operation_name: str,
    error_class: Type[Exception] = Exception,
    recoverable: bool = True,
):
    """
    Context manager wrapper that converts exceptions to custom error types.

    Usage:
        with with_retry_context("database query", DatabaseError):
            result = conn.execute(query)

    Args:
        operation_name: Name of the operation (for error messages)
        error_class: Custom exception class to raise
        recoverable: Whether the error is recoverable

    Raises:
        error_class: On any exception
    """
    from contextlib import contextmanager

    @contextmanager
    def context():
        try:
            yield
        except error_class:
            raise
        except Exception as e:
            raise error_class(f"{operation_name} failed: {str(e)}", recoverable=recoverable) from e

    return context()


def is_transient_error(error: Exception) -> bool:
    """
    Check if an error is transient and should trigger a retry.

    Args:
        error: The exception to check

    Returns:
        True if the error is transient, False otherwise
    """
    import httpx
    import psycopg

    transient_types = (
        httpx.TimeoutException,
        httpx.ConnectError,
        psycopg.OperationalError,
        psycopg.InterfaceError,
        ConnectionError,
        TimeoutError,
        OSError,
    )

    return isinstance(error, transient_types)
