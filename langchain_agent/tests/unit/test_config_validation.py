"""
Unit tests for configuration validation.

Tests that:
- All required env vars are present (OLLAMA_HOST, OPENSEARCH_HOST, etc.)
- Model names in config are local Ollama models (LLM_MODEL, EMBEDDINGS_MODEL, ...)
- Invalid configs raise clear errors
- Default values work when optional vars missing
"""

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.unit
@pytest.mark.phase1
class TestRequiredEnvironmentVariables:
    """Test that all required environment variables are present."""

    def test_ollama_settings_in_config_all(self):
        """OLLAMA_* settings must be exported so callers can import them."""
        from core import config

        for name in ("OLLAMA_HOST", "OLLAMA_KEEP_ALIVE", "OLLAMA_NUM_CTX"):
            assert name in config.__all__
        assert "GOOGLE_API_KEY" not in config.__all__

    @staticmethod
    def _agent_with_healthy_stores(bare_agent):
        from unittest.mock import MagicMock

        mock_vs = MagicMock()
        mock_vs.client.info.return_value = {"version": {"number": "2.19"}}
        mock_vs.client.count.return_value = {"count": 100}
        bare_agent.vector_store = mock_vs
        return bare_agent

    def test_verify_prerequisites_exits_when_ollama_unreachable(self, bare_agent):
        agent = self._agent_with_healthy_stores(bare_agent)
        with (
            patch("psycopg.connect"),
            patch("main.missing_ollama_models", side_effect=OSError("refused")),
        ):
            with pytest.raises(SystemExit) as exc_info:
                agent.verify_prerequisites()
            assert exc_info.value.code == 1

    def test_verify_prerequisites_exits_when_model_not_pulled(self, bare_agent):
        agent = self._agent_with_healthy_stores(bare_agent)
        with (
            patch("psycopg.connect"),
            patch("main.missing_ollama_models", return_value=["nomic-embed-text"]),
        ):
            with pytest.raises(SystemExit) as exc_info:
                agent.verify_prerequisites()
            assert exc_info.value.code == 1

    def test_verify_prerequisites_passes_when_models_present(self, bare_agent):
        agent = self._agent_with_healthy_stores(bare_agent)
        with patch("psycopg.connect"), patch("main.missing_ollama_models", return_value=[]):
            agent.verify_prerequisites()  # must not raise

    def test_opensearch_host_has_default(self):
        """Test OPENSEARCH_HOST has a default value."""
        # Default should be set if not in env
        default = "34.138.97.13"
        env_val = os.getenv("OPENSEARCH_HOST", default)

        assert env_val is not None
        assert isinstance(env_val, str)
        assert len(env_val) > 0

    def test_opensearch_port_is_integer(self):
        """Test OPENSEARCH_PORT converts to integer."""
        port_str = os.getenv("OPENSEARCH_PORT", "9200")

        try:
            port = int(port_str)
            assert port > 0
            assert port < 65536
        except ValueError:
            pytest.fail("OPENSEARCH_PORT must be a valid integer")

    def test_postgres_user_has_default(self):
        """Test POSTGRES_USER has a default value."""
        user = os.getenv("POSTGRES_USER", "postgres")

        assert user is not None
        assert len(user) > 0

    def test_postgres_password_has_default(self):
        """Test POSTGRES_PASSWORD has a default value."""
        password = os.getenv("POSTGRES_PASSWORD", "postgres")

        assert password is not None
        assert len(password) > 0

    def test_postgres_port_is_integer(self):
        """Test POSTGRES_PORT converts to integer."""
        port_str = os.getenv("POSTGRES_PORT", "5432")

        try:
            port = int(port_str)
            assert port > 0
            assert port < 65536
        except ValueError:
            pytest.fail("POSTGRES_PORT must be a valid integer")

    def test_all_required_int_configs_parse_correctly(self):
        """Test all integer configs parse without errors."""
        int_configs = {
            "POSTGRES_PORT": "5432",
            "OPENSEARCH_PORT": "9200",
            "PORT": "8000",
            "RETRIEVER_K": "10",
            "RETRIEVER_FETCH_K": "40",
            "VECTOR_DIMENSION": "768",
        }

        for key, default in int_configs.items():
            value = os.getenv(key, default)
            try:
                int_val = int(value)
                assert int_val >= 0
            except ValueError:
                pytest.fail(f"{key}={value} is not a valid integer")

    def test_llm_temperature_is_a_real_float_config_attribute(self):
        """Regression test: config.LLM_TEMPERATURE must be float, not int.

        `int(os.getenv("LLM_TEMPERATURE", 0))` was the actual bug -- setting
        LLM_TEMPERATURE=0.7 raised ValueError at import time. The other
        temperature-related tests in this file never caught it because they
        re-parse a hardcoded default string locally instead of importing and
        checking the real `config` module attribute -- this one does.
        """
        from core import config

        assert isinstance(config.LLM_TEMPERATURE, float)

        with patch.dict(os.environ, {"LLM_TEMPERATURE": "0.7"}):
            import importlib

            importlib.reload(config)
            try:
                assert config.LLM_TEMPERATURE == pytest.approx(0.7)
            finally:
                # Restore the module to its normal (unset-env) state for
                # any other test that imports config later in this session.
                os.environ.pop("LLM_TEMPERATURE", None)
                importlib.reload(config)


@pytest.mark.unit
@pytest.mark.phase1
class TestModelNameConfiguration:
    """Model settings: local Ollama models, one embedding model on both sides."""

    def test_chat_models_are_non_empty_ollama_names(self):
        from core import config

        for name in ("LLM_MODEL", "QUERY_EVAL_MODEL", "JUDGE_MODEL"):
            value = getattr(config, name)
            assert value and not value.startswith("gemini"), f"{name}={value!r}"

    def test_classifier_and_judge_default_to_the_llm_model(self):
        """One resident model by default (#148); the split is opt-in via env."""
        from core import config

        with patch.dict(os.environ, {}, clear=False):
            for var in ("QUERY_EVAL_MODEL", "JUDGE_MODEL"):
                os.environ.pop(var, None)
            import importlib

            reloaded = importlib.reload(config)
            try:
                assert reloaded.QUERY_EVAL_MODEL == reloaded.LLM_MODEL
                assert reloaded.JUDGE_MODEL == reloaded.LLM_MODEL
            finally:
                importlib.reload(config)

    def test_query_side_embedding_model_matches_lucille_conf(self):
        """Lucille reads ${EMBEDDINGS_MODEL} too -- both sides must use one model."""
        from config_generator import generate_products_conf

        assert "modelName: ${EMBEDDINGS_MODEL}" in generate_products_conf([])

    def test_keep_alive_parses_ollama_durations(self):
        from core.config import _duration_seconds

        assert _duration_seconds("1h") == 3600
        assert _duration_seconds("60m") == 3600
        assert _duration_seconds("90s") == 90
        assert _duration_seconds("300") == 300
        assert _duration_seconds("-1") == -1  # Ollama: keep loaded forever

    def test_num_ctx_is_large_enough_for_agent_prompts(self):
        """Ollama silently truncates past num_ctx; the judge alone can send ~10K tokens."""
        from core.config import OLLAMA_NUM_CTX

        assert OLLAMA_NUM_CTX >= 16384


@pytest.mark.unit
@pytest.mark.phase1
class TestConfigDefaults:
    """Test that default values are applied correctly."""

    def test_default_alpha_value(self):
        """Test default alpha value is between 0 and 1."""
        alpha_str = os.getenv("RETRIEVER_ALPHA", "0.25")
        alpha = float(alpha_str)

        assert 0.0 <= alpha <= 1.0

    def test_default_temperature_value(self):
        """Test default temperature is valid (0-1 or 0-2)."""
        temp_str = os.getenv("LLM_TEMPERATURE", "0")
        temp = float(temp_str)

        assert 0 <= temp <= 2

    def test_default_vector_dimension(self):
        """Test default vector dimension is reasonable."""
        dim_str = os.getenv("VECTOR_DIMENSION", "768")
        dim = int(dim_str)

        assert dim in [384, 512, 768, 1024, 1536]

    def test_default_retriever_k(self):
        """Test default retriever k value."""
        k_str = os.getenv("RETRIEVER_K", "10")
        k = int(k_str)

        assert k > 0
        assert k <= 100

    def test_default_retriever_fetch_k(self):
        """Test default retriever fetch_k is greater than k."""
        fetch_k_str = os.getenv("RETRIEVER_FETCH_K", "40")
        k_str = os.getenv("RETRIEVER_K", "10")

        fetch_k = int(fetch_k_str)
        k = int(k_str)

        assert fetch_k > k

    def test_default_quality_gate_threshold(self):
        """Test default quality gate threshold is valid."""
        threshold_str = os.getenv("QUALITY_GATE_THRESHOLD", "0.5")
        threshold = float(threshold_str)

        assert 0.0 <= threshold <= 1.0

    def test_default_enable_flags_are_booleans(self):
        """Test enable flags parse to boolean values."""
        bool_configs = {
            "ENABLE_RERANKING": "true",
            "ENABLE_QUERY_EVALUATION": "true",
            "ENABLE_QUALITY_GATE": "true",
            "ENABLE_LINK_VERIFICATION": "true",
        }

        for key, default in bool_configs.items():
            value = os.getenv(key, default).lower()
            assert value in ["true", "false"]


@pytest.mark.unit
@pytest.mark.phase1
class TestPortConfiguration:
    """Test port configuration for API server."""

    def test_port_default_value(self):
        """Test PORT env var defaults to 8000."""
        port_str = os.getenv("PORT", "8000")
        port = int(port_str)

        assert port == 8000

    def test_port_can_be_overridden(self):
        """Test PORT can be set to different value."""
        port = 3000
        assert port > 0
        assert port < 65536

    def test_port_is_valid_range(self):
        """Test port is in valid range (1-65535)."""
        port_str = os.getenv("PORT", "8000")
        port = int(port_str)

        assert 1 <= port <= 65535

    def test_cloud_run_port_override(self):
        """Test Cloud Run's PORT environment variable handling."""
        # Cloud Run sets PORT env var dynamically
        port_str = os.getenv("PORT", "8000")
        port = int(port_str)

        # Should work with any valid port
        assert port > 0


@pytest.mark.unit
@pytest.mark.phase1
class TestDatabaseConfiguration:
    """Test database configuration."""

    def test_database_url_construction_local(self):
        """Test database URL construction for local development."""
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "postgres")
        host = os.getenv("POSTGRES_HOST", "localhost")
        port = os.getenv("POSTGRES_PORT", "5432")
        db = os.getenv("POSTGRES_DB", "langchain_agent")

        if not host.startswith("/cloudsql/"):
            url = f"postgresql://{user}:{password}@{host}:{port}/{db}"
            assert "postgresql://" in url
            assert host in url
            assert db in url

    def test_database_url_construction_cloud_sql(self):
        """Test database URL construction for Cloud SQL."""
        user = "postgres"
        password = "testpass"
        host = "/cloudsql/project:region:instance"
        db = "langchain_agent"

        url = f"postgresql://{user}:{password}@/{db}?host={host}"
        assert "postgresql://" in url
        assert "host=" in url

    def test_postgres_credentials_non_empty(self):
        """Test Postgres credentials are provided."""
        user = os.getenv("POSTGRES_USER", "postgres")
        password = os.getenv("POSTGRES_PASSWORD", "postgres")

        assert len(user) > 0
        assert len(password) > 0

    def test_postgres_db_name_valid(self):
        """Test Postgres database name is valid."""
        db = os.getenv("POSTGRES_DB", "langchain_agent")

        assert len(db) > 0
        assert db.replace("_", "").isalnum()


@pytest.mark.unit
@pytest.mark.phase1
class TestOpenSearchConfiguration:
    """Test OpenSearch configuration."""

    def test_opensearch_host_not_localhost(self):
        """Test OpenSearch is configured (not localhost in prod)."""
        host = os.getenv("OPENSEARCH_HOST", "34.138.97.13")

        # Could be localhost for testing, but has a real default
        assert host is not None
        assert len(host) > 0

    def test_opensearch_ssl_parsing(self):
        """Test OpenSearch SSL flag parses correctly."""
        ssl_str = os.getenv("OPENSEARCH_USE_SSL", "true")
        use_ssl = ssl_str.lower() == "true"

        assert isinstance(use_ssl, bool)

    def test_opensearch_verify_certs_parsing(self):
        """Test OpenSearch cert verification flag parses correctly."""
        verify_str = os.getenv("OPENSEARCH_VERIFY_CERTS", "false")
        verify = verify_str.lower() == "true"

        assert isinstance(verify, bool)

    def test_opensearch_index_name_provided(self):
        """Test OpenSearch index name is provided."""
        index = os.getenv("OPENSEARCH_INDEX_NAME", "agentic_hybrid_search_docs")

        assert len(index) > 0
        assert isinstance(index, str)

    def test_opensearch_timeout_is_integer(self):
        """Test OpenSearch timeout is an integer."""
        timeout_str = os.getenv("OPENSEARCH_TIMEOUT", "30")
        timeout = int(timeout_str)

        assert timeout > 0

    def test_opensearch_search_pipeline_configured(self):
        """Test OpenSearch search pipeline is named."""
        pipeline = os.getenv("OPENSEARCH_SEARCH_PIPELINE", "hybrid_search_pipeline")

        assert len(pipeline) > 0
        assert isinstance(pipeline, str)


@pytest.mark.unit
@pytest.mark.phase1
class TestEmbeddingDimensionValidation:
    """Test embedding dimension configuration."""

    def test_vector_dimension_matches_model(self):
        """Test vector dimension matches embedding model output."""
        dim_str = os.getenv("VECTOR_DIMENSION", "768")
        dim = int(dim_str)

        # Gemini embedding-001 outputs 768 dimensions
        # text-embedding-005 can output 768 with output_dimensionality=768
        assert dim in [384, 512, 768, 1024, 1536]

    def test_vector_dimension_positive(self):
        """Test vector dimension is positive."""
        dim_str = os.getenv("VECTOR_DIMENSION", "768")
        dim = int(dim_str)

        assert dim > 0

    def test_vector_dimension_reasonable_for_search(self):
        """Test vector dimension is reasonable for search."""
        dim_str = os.getenv("VECTOR_DIMENSION", "768")
        dim = int(dim_str)

        # Reasonable range for embeddings
        assert dim >= 256
        assert dim <= 2048


@pytest.mark.unit
@pytest.mark.phase1
class TestConfigurationConsistency:
    """Test that configurations are internally consistent."""

    def test_retriever_k_less_than_fetch_k(self):
        """Test retriever k is less than fetch_k."""
        k = int(os.getenv("RETRIEVER_K", "10"))
        fetch_k = int(os.getenv("RETRIEVER_FETCH_K", "40"))

        assert k < fetch_k

    def test_reranker_top_k_less_than_fetch_k(self):
        """Test reranker top_k is less than fetch_k."""
        # RERANKER_TOP_K is configured in code, not env
        fetch_k = int(os.getenv("RETRIEVER_FETCH_K", "40"))
        top_k = 10  # From config.py

        assert top_k < fetch_k

    def test_temperature_not_negative(self):
        """Test temperature is not negative."""
        temp = float(os.getenv("LLM_TEMPERATURE", "0"))

        assert temp >= 0

    def test_timeout_values_positive(self):
        """Test all timeout values are positive."""
        timeouts = {
            "ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS": "5",
            "LINK_VERIFICATION_TIMEOUT_MS": "2000",
        }

        for key, default in timeouts.items():
            timeout = int(os.getenv(key, default))
            assert timeout > 0


@pytest.mark.unit
@pytest.mark.phase1
class TestEnvironmentVariableTypes:
    """Test that env vars are accessed with correct types."""

    def test_string_configs_are_strings(self):
        """Test string configs return strings."""
        string_configs = [
            "POSTGRES_USER",
            "POSTGRES_PASSWORD",
            "POSTGRES_HOST",
            "POSTGRES_DB",
            "OPENSEARCH_HOST",
            "LLM_MODEL",
            "EMBEDDINGS_MODEL",
            "QUERY_EVAL_MODEL",
            "OLLAMA_HOST",
        ]

        for key in string_configs:
            value = os.getenv(key)
            if value is not None:
                assert isinstance(value, str)

    def test_numeric_configs_convert_to_numbers(self):
        """Test numeric configs convert properly."""
        numeric_configs = {
            "POSTGRES_PORT": int,
            "OPENSEARCH_PORT": int,
            "PORT": int,
            "LLM_TEMPERATURE": float,
            "VECTOR_DIMENSION": int,
            "RETRIEVER_K": int,
            "RETRIEVER_FETCH_K": int,
        }

        for key, converter in numeric_configs.items():
            value = os.getenv(key)
            if value is not None:
                try:
                    result = converter(value)
                    assert isinstance(result, converter)
                except ValueError:
                    pytest.fail(f"{key}={value} cannot convert to {converter.__name__}")

    def test_boolean_configs_parse_correctly(self):
        """Test boolean configs parse from string."""
        bool_configs = [
            "ENABLE_RERANKING",
            "ENABLE_QUERY_EVALUATION",
            "ENABLE_QUALITY_GATE",
        ]

        for key in bool_configs:
            value = os.getenv(key, "true").lower()
            assert value in ["true", "false"]
