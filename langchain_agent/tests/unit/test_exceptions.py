"""Unit tests for the custom exception hierarchy in core/exceptions.py."""

import pytest

from core.exceptions import (
    AgenticHybridSearchError,
    EmbeddingError,
    LLMError,
    SearchFailureError,
    SearchTimeoutError,
    SearchValidationError,
)


@pytest.mark.unit
class TestAgenticHybridSearchError:
    def test_message_stored(self):
        e = AgenticHybridSearchError("something broke")
        assert e.message == "something broke"
        assert str(e) == "something broke"

    def test_details_appended_to_str(self):
        e = AgenticHybridSearchError("broke", details="extra context")
        assert "extra context" in str(e)

    def test_no_details_clean_str(self):
        e = AgenticHybridSearchError("broke")
        assert str(e) == "broke"

    def test_recoverable_default_false(self):
        e = AgenticHybridSearchError("broke")
        assert e.recoverable is False

    def test_recoverable_can_be_set_true(self):
        e = AgenticHybridSearchError("broke", recoverable=True)
        assert e.recoverable is True


@pytest.mark.unit
class TestLLMError:
    def test_defaults_recoverable_true(self):
        e = LLMError("timeout")
        assert e.recoverable is True

    def test_model_and_operation_stored(self):
        e = LLMError("failed", model="qwen3.6:35b-a3b-q4_K_M", operation="generate")
        assert e.model == "qwen3.6:35b-a3b-q4_K_M"
        assert e.operation == "generate"
        assert "qwen3.6:35b-a3b-q4_K_M" in str(e)


@pytest.mark.unit
class TestSearchValidationError:
    def test_short_query_in_details(self):
        e = SearchValidationError("empty", query="headphones")
        assert e.query == "headphones"
        assert "headphones" in str(e)

    def test_long_query_truncated(self):
        long_q = "a" * 100
        e = SearchValidationError("too long", query=long_q)
        assert "..." in str(e)

    def test_defaults_recoverable_false(self):
        e = SearchValidationError("bad query")
        assert e.recoverable is False


@pytest.mark.unit
class TestSearchFailureError:
    def test_index_stored(self):
        e = SearchFailureError("not found", index="esci_products")
        assert e.index == "esci_products"
        assert "esci_products" in str(e)

    def test_defaults_recoverable_true(self):
        e = SearchFailureError("failed")
        assert e.recoverable is True


@pytest.mark.unit
class TestEmbeddingError:
    def test_dimension_stored(self):
        e = EmbeddingError("bad dim", dimension=512)
        assert e.dimension == 512
        assert "512" in str(e)

    def test_defaults_recoverable_true(self):
        e = EmbeddingError("failed")
        assert e.recoverable is True


@pytest.mark.unit
class TestSearchTimeoutError:
    def test_operation_and_timeout_stored(self):
        e = SearchTimeoutError("timed out", operation="hybrid_search", timeout_ms=3000.0)
        assert e.operation == "hybrid_search"
        assert e.timeout_ms == 3000.0
        assert "3000" in str(e)

    def test_defaults_recoverable_true(self):
        e = SearchTimeoutError("timed out")
        assert e.recoverable is True


@pytest.mark.unit
def test_all_inherit_from_base():
    for exc in (
        LLMError("x"),
        SearchValidationError("x"),
        SearchFailureError("x"),
        EmbeddingError("x"),
        SearchTimeoutError("x"),
    ):
        assert isinstance(exc, AgenticHybridSearchError)
        assert isinstance(exc, Exception)
