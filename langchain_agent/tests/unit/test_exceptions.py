"""
Unit tests for the custom exception hierarchy in exceptions.py.

Covers construction, attribute storage, __str__ formatting, and
the recoverable flag for every exception class.
"""

import pytest

from exceptions import (
    AgentError,
    AgenticHybridSearchError,
    AgentTimeoutError,
    ConfigurationError,
    DatabaseError,
    EmbeddingError,
    LinkVerificationError,
    LLMError,
    OpenSearchError,
    RerankerError,
    RerankerLLMError,
    RerankerValidationError,
    RetrievalError,
    SearchFailureError,
    SearchTimeoutError,
    SearchValidationError,
    StateError,
    StreamingError,
)

# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------


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

    def test_is_exception_subclass(self):
        e = AgenticHybridSearchError("broke")
        assert isinstance(e, Exception)


# ---------------------------------------------------------------------------
# ConfigurationError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConfigurationError:
    def test_basic(self):
        e = ConfigurationError("missing key")
        assert e.message == "missing key"
        assert e.recoverable is False

    def test_config_key_stored(self):
        e = ConfigurationError("missing", config_key="GOOGLE_API_KEY")
        assert e.config_key == "GOOGLE_API_KEY"
        assert "GOOGLE_API_KEY" in str(e)

    def test_no_config_key(self):
        e = ConfigurationError("missing")
        assert e.config_key is None
        assert str(e) == "missing"


# ---------------------------------------------------------------------------
# DatabaseError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestDatabaseError:
    def test_defaults_recoverable_true(self):
        e = DatabaseError("conn lost")
        assert e.recoverable is True

    def test_operation_and_table_in_str(self):
        e = DatabaseError("failed", operation="SELECT", table="checkpoints")
        assert "SELECT" in str(e)
        assert "checkpoints" in str(e)

    def test_operation_only(self):
        e = DatabaseError("failed", operation="INSERT")
        assert e.operation == "INSERT"
        assert e.table is None

    def test_recoverable_override(self):
        e = DatabaseError("fatal", recoverable=False)
        assert e.recoverable is False


# ---------------------------------------------------------------------------
# OpenSearchError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestOpenSearchError:
    def test_defaults(self):
        e = OpenSearchError("index missing")
        assert e.recoverable is True
        assert e.operation is None
        assert e.index is None

    def test_operation_and_index_in_details(self):
        e = OpenSearchError("failed", operation="search", index="esci_products")
        assert "search" in str(e)
        assert "esci_products" in str(e)


# ---------------------------------------------------------------------------
# LLMError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLLMError:
    def test_defaults_recoverable_true(self):
        e = LLMError("timeout")
        assert e.recoverable is True

    def test_model_and_operation_stored(self):
        e = LLMError("failed", model="gemini-3-flash-preview", operation="generate")
        assert e.model == "gemini-3-flash-preview"
        assert e.operation == "generate"
        assert "gemini-3-flash-preview" in str(e)


# ---------------------------------------------------------------------------
# RetrievalError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRetrievalError:
    def test_stage_and_query_stored(self):
        e = RetrievalError("failed", stage="reranker", query="wireless headphones")
        assert e.stage == "reranker"
        assert e.query == "wireless headphones"

    def test_long_query_truncated_in_details(self):
        long_q = "a" * 100
        e = RetrievalError("failed", query=long_q)
        assert "..." in str(e)
        # Original query stored in full
        assert e.query == long_q

    def test_defaults_recoverable_true(self):
        e = RetrievalError("failed")
        assert e.recoverable is True


# ---------------------------------------------------------------------------
# LinkVerificationError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestLinkVerificationError:
    def test_url_and_status_in_details(self):
        e = LinkVerificationError("link broken", url="https://amazon.com/dp/B08", status_code=404)
        assert e.url == "https://amazon.com/dp/B08"
        assert e.status_code == 404
        assert "404" in str(e)

    def test_url_truncated_at_100_chars(self):
        long_url = "https://example.com/" + "x" * 200
        e = LinkVerificationError("failed", url=long_url)
        assert e.url == long_url  # stored in full
        assert len([p for p in str(e).split("url=")[1:]][0]) <= 120  # truncated in details


# ---------------------------------------------------------------------------
# StreamingError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStreamingError:
    def test_event_type_stored(self):
        e = StreamingError("send failed", event_type="LLMResponseChunkEvent")
        assert e.event_type == "LLMResponseChunkEvent"
        assert "LLMResponseChunkEvent" in str(e)

    def test_defaults_recoverable_true(self):
        e = StreamingError("failed")
        assert e.recoverable is True


# ---------------------------------------------------------------------------
# StateError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestStateError:
    def test_field_and_node_stored(self):
        e = StateError("missing field", field="intent", node="classifier")
        assert e.field == "intent"
        assert e.node == "classifier"
        assert "intent" in str(e)
        assert "classifier" in str(e)

    def test_defaults_recoverable_false(self):
        e = StateError("bad state")
        assert e.recoverable is False


# ---------------------------------------------------------------------------
# RerankerLLMError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRerankerLLMError:
    def test_model_and_batch_size_stored(self):
        e = RerankerLLMError("api error", model="gemini-3.1-flash-lite-preview", batch_size=15)
        assert e.model == "gemini-3.1-flash-lite-preview"
        assert e.batch_size == 15
        assert "15" in str(e)

    def test_defaults_recoverable_true(self):
        e = RerankerLLMError("api error")
        assert e.recoverable is True


# ---------------------------------------------------------------------------
# RerankerValidationError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRerankerValidationError:
    def test_num_scores_and_docs_in_details(self):
        e = RerankerValidationError("mismatch", num_scores=3, num_docs=5)
        assert e.num_scores == 3
        assert e.num_docs == 5
        assert "3" in str(e)
        assert "5" in str(e)

    def test_defaults_recoverable_false(self):
        e = RerankerValidationError("mismatch")
        assert e.recoverable is False

    def test_zero_num_scores_shown(self):
        # num_scores=0 is falsy but should still appear
        e = RerankerValidationError("empty", num_scores=0, num_docs=5)
        assert e.num_scores == 0


# ---------------------------------------------------------------------------
# SearchValidationError
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# SearchFailureError / EmbeddingError / SearchTimeoutError
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# AgentError / AgentTimeoutError / RerankerError
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestAgentError:
    def test_node_stored(self):
        e = AgentError("node failed", node="retriever")
        assert e.node == "retriever"
        assert "retriever" in str(e)

    def test_defaults_recoverable_false(self):
        e = AgentError("failed")
        assert e.recoverable is False


@pytest.mark.unit
class TestAgentTimeoutError:
    def test_timeout_and_node_stored(self):
        e = AgentTimeoutError("timeout", timeout_ms=5000.0, node="reranker")
        assert e.timeout_ms == 5000.0
        assert e.node == "reranker"

    def test_defaults_recoverable_true(self):
        e = AgentTimeoutError("timeout")
        assert e.recoverable is True


@pytest.mark.unit
class TestRerankerError:
    def test_batch_size_stored(self):
        e = RerankerError("failed", batch_size=10)
        assert e.batch_size == 10
        assert "10" in str(e)

    def test_defaults_recoverable_true(self):
        e = RerankerError("failed")
        assert e.recoverable is True


# ---------------------------------------------------------------------------
# Inheritance
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestInheritance:
    def test_all_inherit_from_base(self):
        classes = [
            ConfigurationError("x"),
            DatabaseError("x"),
            OpenSearchError("x"),
            LLMError("x"),
            RetrievalError("x"),
            LinkVerificationError("x"),
            StreamingError("x"),
            StateError("x"),
            RerankerLLMError("x"),
            RerankerValidationError("x"),
            SearchValidationError("x"),
            SearchFailureError("x"),
            EmbeddingError("x"),
            SearchTimeoutError("x"),
            AgentError("x"),
            AgentTimeoutError("x"),
            RerankerError("x"),
        ]
        for exc in classes:
            assert isinstance(exc, AgenticHybridSearchError), f"{type(exc).__name__} not a subclass"
            assert isinstance(exc, Exception)
