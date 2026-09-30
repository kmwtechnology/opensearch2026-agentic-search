"""Unit tests for the custom exception hierarchy in core/exceptions.py."""

from core.exceptions import (
    AgenticHybridSearchError,
    EmbeddingError,
    SearchFailureError,
    SearchTimeoutError,
    SearchValidationError,
)


def test_all_inherit_from_base():
    for exc in (
        SearchValidationError("x"),
        SearchFailureError("x"),
        EmbeddingError("x"),
        SearchTimeoutError("x"),
    ):
        assert isinstance(exc, AgenticHybridSearchError)
        assert str(exc) == "x"
