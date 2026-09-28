"""
Custom exceptions for Agentic Hybrid Search agent.

Provides a structured exception hierarchy for better error handling,
debugging, and user feedback.
"""

from typing import Optional


class AgenticHybridSearchError(Exception):
    """
    Base exception for all Agentic Hybrid Search errors.

    All custom exceptions inherit from this class, making it easy to
    catch any agent-related error with a single except clause.

    Attributes:
        message: Human-readable error description
        details: Optional additional context (e.g., stack traces, state)
        recoverable: Whether the error is potentially recoverable
    """

    def __init__(self, message: str, details: Optional[str] = None, recoverable: bool = False):
        self.message = message
        self.details = details
        self.recoverable = recoverable
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.details:
            return f"{self.message} ({self.details})"
        return self.message


class LLMError(AgenticHybridSearchError):
    """
    Raised when LLM operations fail.

    Examples:
    - Model not found
    - Inference timeout
    - Context length exceeded
    - Rate limiting
    """

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        operation: Optional[str] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if model:
            details_parts.append(f"model={model}")
        if operation:
            details_parts.append(f"operation={operation}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.model = model
        self.operation = operation


class SearchValidationError(AgenticHybridSearchError):
    """
    Raised when search query validation fails.

    Examples:
    - Query string is empty
    - Query exceeds max length
    - Query format is invalid
    """

    def __init__(self, message: str, query: Optional[str] = None, recoverable: bool = False):
        details = (
            f"query={query[:50] + '...' if query and len(query) > 50 else query}" if query else None
        )
        super().__init__(message, details=details, recoverable=recoverable)
        self.query = query


class SearchFailureError(AgenticHybridSearchError):
    """
    Raised when search operation fails.

    Examples:
    - Index not found
    - Search query parsing error
    - Index corruption
    """

    def __init__(self, message: str, index: Optional[str] = None, recoverable: bool = True):
        details = f"index={index}" if index else None
        super().__init__(message, details=details, recoverable=recoverable)
        self.index = index


class EmbeddingError(AgenticHybridSearchError):
    """
    Raised when embedding generation fails.

    Examples:
    - Ollama unreachable
    - Invalid embedding dimension
    """

    def __init__(self, message: str, dimension: Optional[int] = None, recoverable: bool = True):
        details = f"dimension={dimension}" if dimension else None
        super().__init__(message, details=details, recoverable=recoverable)
        self.dimension = dimension


class SearchTimeoutError(AgenticHybridSearchError):
    """
    Raised when search operation times out.

    Examples:
    - OpenSearch request timeout
    - Embedding generation timeout
    - Network timeout
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        timeout_ms: Optional[float] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if operation:
            details_parts.append(f"operation={operation}")
        if timeout_ms:
            details_parts.append(f"timeout_ms={timeout_ms}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.operation = operation
        self.timeout_ms = timeout_ms
