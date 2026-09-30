"""Exception hierarchy for the agent: one base class, one subclass per failure kind."""


class AgenticHybridSearchError(Exception):
    """Base for every error the agent raises itself."""


class SearchValidationError(AgenticHybridSearchError):
    """Search arguments are invalid (k, fetch_k, alpha out of range)."""


class SearchFailureError(AgenticHybridSearchError):
    """An OpenSearch request failed."""


class EmbeddingError(AgenticHybridSearchError):
    """Query embedding generation failed (Ollama unreachable, bad response)."""


class SearchTimeoutError(AgenticHybridSearchError):
    """A search request timed out."""
