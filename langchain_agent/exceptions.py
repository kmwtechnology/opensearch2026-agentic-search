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


class ConfigurationError(AgenticHybridSearchError):
    """
    Raised when configuration is invalid or missing.

    Examples:
    - API_KEY not set
    - Invalid database URL
    - Missing required model
    """

    def __init__(self, message: str, config_key: Optional[str] = None):
        details = f"config_key={config_key}" if config_key else None
        super().__init__(message, details=details, recoverable=False)
        self.config_key = config_key


class DatabaseError(AgenticHybridSearchError):
    """
    Raised when database operations fail.

    Examples:
    - Connection timeout
    - Query execution error
    - Transaction failure
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        table: Optional[str] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if operation:
            details_parts.append(f"operation={operation}")
        if table:
            details_parts.append(f"table={table}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.operation = operation
        self.table = table


class OpenSearchError(AgenticHybridSearchError):
    """
    Raised when OpenSearch operations fail.

    Examples:
    - Connection timeout
    - Index not found
    - Search query failure
    """

    def __init__(
        self,
        message: str,
        operation: Optional[str] = None,
        index: Optional[str] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if operation:
            details_parts.append(f"operation={operation}")
        if index:
            details_parts.append(f"index={index}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.operation = operation
        self.index = index


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


class RetrievalError(AgenticHybridSearchError):
    """
    Raised when document retrieval fails.

    Examples:
    - Vector search failure
    - Embedding generation error
    - Reranking failure
    """

    def __init__(
        self,
        message: str,
        stage: Optional[str] = None,
        query: Optional[str] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if stage:
            details_parts.append(f"stage={stage}")
        if query:
            # Truncate long queries
            truncated = query[:50] + "..." if len(query) > 50 else query
            details_parts.append(f"query={truncated}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.stage = stage
        self.query = query


class LinkVerificationError(AgenticHybridSearchError):
    """
    Raised when link verification fails.

    Examples:
    - All URLs timing out
    - Network connectivity issue
    - Cache corruption
    """

    def __init__(
        self,
        message: str,
        url: Optional[str] = None,
        status_code: Optional[int] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if url:
            details_parts.append(f"url={url[:100]}")
        if status_code:
            details_parts.append(f"status={status_code}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.url = url
        self.status_code = status_code


class StreamingError(AgenticHybridSearchError):
    """
    Raised when streaming operations fail.

    Examples:
    - WebSocket connection lost
    - Event serialization error
    - Stream timeout
    """

    def __init__(self, message: str, event_type: Optional[str] = None, recoverable: bool = True):
        details = f"event_type={event_type}" if event_type else None
        super().__init__(message, details=details, recoverable=recoverable)
        self.event_type = event_type


class StateError(AgenticHybridSearchError):
    """
    Raised when agent state is invalid.

    Examples:
    - Missing required state field
    - Invalid state transition
    - Checkpoint corruption
    """

    def __init__(
        self,
        message: str,
        field: Optional[str] = None,
        node: Optional[str] = None,
        recoverable: bool = False,
    ):
        details_parts = []
        if field:
            details_parts.append(f"field={field}")
        if node:
            details_parts.append(f"node={node}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.field = field
        self.node = node


class RerankerLLMError(AgenticHybridSearchError):
    """
    Raised when LLM-based reranking fails.

    Examples:
    - LLM API call timeout
    - Invalid response format from LLM
    - LLM rate limiting
    """

    def __init__(
        self,
        message: str,
        model: Optional[str] = None,
        batch_size: Optional[int] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if model:
            details_parts.append(f"model={model}")
        if batch_size:
            details_parts.append(f"batch_size={batch_size}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.model = model
        self.batch_size = batch_size


class RerankerValidationError(AgenticHybridSearchError):
    """
    Raised when reranked output validation fails.

    Examples:
    - Score outside [0.0, 1.0]
    - Number of scores doesn't match documents
    - Invalid score format
    """

    def __init__(
        self,
        message: str,
        num_scores: Optional[int] = None,
        num_docs: Optional[int] = None,
        recoverable: bool = False,
    ):
        details_parts = []
        if num_scores is not None:
            details_parts.append(f"num_scores={num_scores}")
        if num_docs is not None:
            details_parts.append(f"num_docs={num_docs}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.num_scores = num_scores
        self.num_docs = num_docs


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
    - API quota exceeded
    - Invalid embedding dimension
    - Embedding API error
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


class AgentError(AgenticHybridSearchError):
    """
    Raised when agent execution fails.

    Examples:
    - Node execution error
    - Graph state error
    - Agent completion failure
    """

    def __init__(self, message: str, node: Optional[str] = None, recoverable: bool = False):
        details = f"node={node}" if node else None
        super().__init__(message, details=details, recoverable=recoverable)
        self.node = node


class AgentTimeoutError(AgenticHybridSearchError):
    """
    Raised when agent execution times out.

    Examples:
    - Graph execution timeout
    - Node processing timeout
    - LLM response timeout
    """

    def __init__(
        self,
        message: str,
        timeout_ms: Optional[float] = None,
        node: Optional[str] = None,
        recoverable: bool = True,
    ):
        details_parts = []
        if timeout_ms:
            details_parts.append(f"timeout_ms={timeout_ms}")
        if node:
            details_parts.append(f"node={node}")
        details = ", ".join(details_parts) if details_parts else None

        super().__init__(message, details=details, recoverable=recoverable)
        self.timeout_ms = timeout_ms
        self.node = node


class RerankerError(AgenticHybridSearchError):
    """
    Raised when reranking operation fails.

    Examples:
    - Reranking API error
    - Invalid scores returned
    - Batch processing failure
    """

    def __init__(self, message: str, batch_size: Optional[int] = None, recoverable: bool = True):
        details = f"batch_size={batch_size}" if batch_size else None
        super().__init__(message, details=details, recoverable=recoverable)
        self.batch_size = batch_size
