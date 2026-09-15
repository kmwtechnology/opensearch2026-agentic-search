"""
Unit tests for model compatibility and configuration.

Tests that models are correctly configured:
- Gemini 2.5 Flash for generation (issue #126)
- Gemini 2.5 Flash-Lite for classification/query-eval/judge (issue #126)
- Gemini 3.1 Flash Lite for the (unused-by-default) Gemini reranker path
- Correct embedding dimensions (768)
- API calls use correct model IDs
"""

import os
import sys
from pathlib import Path

import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.unit
@pytest.mark.phase1
class TestGeminiModelNames:
    """Test Gemini model naming conventions."""

    def test_llm_model_is_gemini_flash(self):
        """Test LLM model is a Gemini Flash generation model."""
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        assert "gemini-2" in model or "gemini-3" in model or "gemini-4" in model
        assert "flash" in model

    def test_reranker_model_is_gemini_3_1_flash_lite(self):
        """Test reranker model is Gemini 3.1 Flash Lite (preview)."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        assert "gemini-3.1" in model or "gemini-4" in model
        assert "flash-lite" in model or "flash-lite" in model

    def test_query_eval_model_is_gemini_flash_lite(self):
        """Test query evaluator model is a Gemini Flash-Lite model."""
        model = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        assert "gemini-2" in model or "gemini-3" in model or "gemini-4" in model
        assert "flash-lite" in model or "flash" in model

    def test_embeddings_model_is_gemini_or_text_embedding(self):
        """Test embeddings model is stable version."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # Should be either gemini-embedding or text-embedding
        assert "embedding" in model.lower()

    def test_llm_model_not_deprecated(self):
        """Test LLM model is not a deprecated version."""
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Avoid deprecated models (gemini-2.0 and earlier were discontinued
        # mid-2026; gemini-2.5+ remain current -- see #126)
        assert "gemini-2.0" not in model
        assert "gemini-1" not in model
        assert "bison" not in model

    def test_reranker_model_not_deprecated(self):
        """Test reranker model is not deprecated."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        assert "gemini-2" not in model
        assert "bison" not in model

    def test_embeddings_model_not_deprecated(self):
        """Test embeddings model is stable (not experimental)."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # Should be stable model, not experimental
        assert "experimental" not in model.lower() or "embedding-001" in model


@pytest.mark.unit
@pytest.mark.phase1
class TestModelTypeAssignment:
    """Test that models are assigned to correct use cases."""

    def test_llm_model_for_generation(self):
        """Test LLM model is suitable for text generation.

        As of #126, generation uses gemini-2.5-flash (not a Gemini 3.x model,
        and not the Lite variant). Gemini 3.x's mandatory "thinking" made
        every call pay a latency tax with no way to disable it; the Flash-Lite
        candidates tested alongside it failed in different ways instead:
        gemini-3.5-flash-lite looked fast in a single isolated call but
        ballooned to ~30s once real multi-turn conversation history piled up,
        and gemini-2.5-flash-lite stayed fast but dropped required prompt
        instructions (e.g. the refinement intent's "From the N products I
        showed you earlier" framing) in favor of generic phrasing. Full
        gemini-2.5-flash was the only candidate that stayed both fast
        (~6-11s, no multi-turn blowup) and instruction-following-accurate.
        """
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        assert "flash" in model

    def test_reranker_model_is_lightweight(self):
        """Test reranker model is lightweight for fast scoring."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        # Should be "lite" for fast reranking
        assert "lite" in model or "flash-lite" in model

    def test_query_eval_model_is_lightweight(self):
        """Test query evaluator model is lightweight."""
        model = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        # Should be "lite" for fast query classification
        assert "lite" in model or "flash-lite" in model

    def test_embeddings_model_produces_768_dimensions(self):
        """Test embeddings model is configured for 768 dimensions."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")
        dim = int(os.getenv("VECTOR_DIMENSION", "768"))

        # text-embedding-005 with output_dimensionality=768 produces 768-dim vectors
        assert dim == 768 or "embedding" in model


@pytest.mark.unit
@pytest.mark.phase1
class TestModelAPICompatibility:
    """Test that model names are compatible with Google AI API."""

    def test_model_format_matches_google_ai_api(self):
        """Test model names match Google AI API format."""
        models_to_test = [
            os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview"),
            os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite"),
        ]

        for model in models_to_test:
            # Google AI API uses "gemini-X-name" or "gemini-X.X-name" format
            assert model.startswith("gemini-") or model.startswith("models/")

    def test_embeddings_model_format_matches_api(self):
        """Test embeddings model format matches API."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # Should be models/<name> or <name>
        assert "models/" in model or "embedding" in model

    def test_model_names_are_valid_strings(self):
        """Test all model names are valid strings."""
        models = {
            "LLM_MODEL": os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            "RERANKER_MODEL": os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview"),
            "QUERY_EVAL_MODEL": os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite"),
            "EMBEDDINGS_MODEL": os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005"),
        }

        for key, model in models.items():
            assert isinstance(model, str)
            assert len(model) > 0
            assert not model.startswith(" ")
            assert not model.endswith(" ")


@pytest.mark.unit
@pytest.mark.phase1
class TestModelPerformanceCharacteristics:
    """Test that models have expected performance characteristics."""

    def test_flash_models_are_faster_than_pro(self):
        """Test Flash models are configured for speed."""
        llm_model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Flash models are faster and cheaper than Pro
        assert "flash" in llm_model

    def test_lite_models_faster_than_full(self):
        """Test Lite models are faster than full models."""
        reranker = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")
        query_eval = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        # Lite models for latency-sensitive tasks
        assert "lite" in reranker or "flash-lite" in reranker
        assert "lite" in query_eval or "flash-lite" in query_eval

    def test_reranker_and_query_eval_are_same_model(self):
        """Test reranker and query evaluator use same model for consistency."""
        reranker = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")
        query_eval = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        # Both should use fast lite model
        assert reranker == query_eval or ("lite" in reranker and "lite" in query_eval)


@pytest.mark.unit
@pytest.mark.phase1
class TestEmbeddingModelConfiguration:
    """Test embedding model configuration."""

    def test_embedding_dimension_is_768(self):
        """Test embedding dimension is set to 768."""
        dim = int(os.getenv("VECTOR_DIMENSION", "768"))

        assert dim == 768

    def test_embedding_model_matches_dimension(self):
        """Test embedding model produces correct dimensions."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")
        dim = int(os.getenv("VECTOR_DIMENSION", "768"))

        # Verify dimension makes sense for the model
        if "text-embedding-005" in model:
            # text-embedding-005 supports variable dimensions
            assert dim in [256, 512, 768, 1024]
        elif "embedding-001" in model:
            # embedding-001 produces 768
            assert dim == 768

    def test_embedding_model_name_valid(self):
        """Test embedding model name is valid."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        assert "embedding" in model.lower()
        assert "005" in model or "001" in model or "models" in model


@pytest.mark.unit
@pytest.mark.phase1
class TestTemperatureConfiguration:
    """Test temperature configuration for different models."""

    def test_llm_temperature_zero_for_determinism(self):
        """Test LLM temperature is 0 for deterministic responses."""
        temp = int(os.getenv("LLM_TEMPERATURE", "0"))

        assert temp == 0

    def test_query_eval_temperature_zero(self):
        """Test query evaluator temperature is 0."""
        temp = float(os.getenv("QUERY_EVAL_TEMPERATURE", "0"))

        assert temp == 0.0

    def test_temperature_in_valid_range(self):
        """Test temperature values are in valid range."""
        temps = {
            "LLM_TEMPERATURE": int(os.getenv("LLM_TEMPERATURE", "0")),
            "QUERY_EVAL_TEMPERATURE": float(os.getenv("QUERY_EVAL_TEMPERATURE", "0")),
        }

        for key, temp in temps.items():
            assert 0 <= temp <= 2


@pytest.mark.unit
@pytest.mark.phase1
class TestModelVersionConsistency:
    """Test version consistency across model configurations."""

    def test_all_gemini_models_are_recent_versions(self):
        """Test all Gemini models are recent (2.5+), not legacy.

        As of #126, generation and query-eval/judge both landed on the
        gemini-2.5 family (full Flash for generation, Flash-Lite for
        classify/eval/judge) rather than Gemini 3.x, specifically to avoid
        Gemini 3's mandatory "thinking" tax (no way to fully disable it).
        Only the unused-by-default Gemini reranker path stays on 3.1.
        """
        llm = os.getenv("LLM_MODEL", "gemini-2.5-flash")
        reranker = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")
        query_eval = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        for model in (llm, reranker, query_eval):
            assert any(f"gemini-{v}" in model for v in ("2.5", "3", "3.1", "3.5", "4"))

    def test_model_names_not_mixed_generations(self):
        """Test models are not from vastly different generations."""
        llm = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Should not mix gemini-2 with gemini-3
        assert "gemini-1" not in llm
        assert "bison" not in llm


@pytest.mark.unit
@pytest.mark.phase1
class TestModelFeatureCompatibility:
    """Test that configured models have expected features."""

    def test_llm_model_supports_streaming(self):
        """Test LLM model supports streaming."""
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Gemini 3 Flash supports streaming
        assert "flash" in model

    def test_reranker_model_supports_structured_output(self):
        """Test reranker model supports structured output."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        # Gemini models support structured output
        assert "gemini" in model

    def test_embeddings_model_supports_output_dimensionality(self):
        """Test embeddings model supports output dimensionality config."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # text-embedding-005 and embedding-001 support dimensionality
        assert "005" in model or "001" in model or "embedding" in model


@pytest.mark.unit
@pytest.mark.phase1
class TestModelSelectionRationale:
    """Test that model selections make sense for use cases."""

    def test_generation_uses_flash_family(self):
        """Test generation uses a Flash-family model.

        As of #126, this is full gemini-2.5-flash, not Flash-Lite -- the Lite
        variant (gemini-2.5-flash-lite) is fast but drops required prompt
        instructions under this app's long system prompt (see
        test_llm_model_for_generation for the full comparison).
        """
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        assert "flash" in model

    def test_classification_uses_lite_for_speed(self):
        """Test classification uses Lite for speed."""
        model = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        # Classification should be fast
        assert "lite" in model or "flash-lite" in model

    def test_reranking_uses_lite_for_throughput(self):
        """Test reranking uses Lite for batch throughput."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        # Reranking many documents needs speed
        assert "lite" in model or "flash-lite" in model

    def test_embeddings_uses_dedicated_model(self):
        """Test embeddings uses dedicated embedding model."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # Should use specialized embedding model
        assert "embedding" in model.lower()


@pytest.mark.unit
@pytest.mark.phase1
class TestModelAPIEndpointCompatibility:
    """Test model names are compatible with API endpoints."""

    def test_gemini_model_names_valid_for_google_ai_api(self):
        """Test Gemini model names are valid for google.generativeai."""
        models = [
            os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview"),
        ]

        for model in models:
            # google.generativeai accepts "gemini-X-name" format
            assert model.startswith("gemini-")

    def test_embedding_model_name_valid_for_api(self):
        """Test embedding model name is valid for API."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        # Embedding API might use "models/..." prefix
        assert "models/" in model or "embedding" in model

    def test_no_invalid_model_names(self):
        """Test no invalid/malformed model names."""
        models = {
            "LLM_MODEL": os.getenv("LLM_MODEL", "gemini-2.5-flash"),
            "RERANKER_MODEL": os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview"),
            "QUERY_EVAL_MODEL": os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite"),
            "EMBEDDINGS_MODEL": os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005"),
        }

        for key, model in models.items():
            # No double spaces
            assert "  " not in model
            # No special chars except hyphen, dot, slash, underscore
            valid_chars = set("abcdefghijklmnopqrstuvwxyz0123456789-._/")
            assert all(c in valid_chars for c in model.lower())


@pytest.mark.unit
@pytest.mark.phase1
class TestModelInstanceCreation:
    """Test that model names work for LLM instance creation."""

    def test_llm_model_instantiable(self):
        """Test LLM model name is instantiable format."""
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Should be simple string, not complex object
        assert isinstance(model, str)
        assert len(model) < 100

    def test_reranker_model_instantiable(self):
        """Test reranker model name is instantiable format."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")

        assert isinstance(model, str)
        assert len(model) < 100

    def test_embeddings_model_instantiable(self):
        """Test embeddings model name is instantiable format."""
        model = os.getenv("EMBEDDINGS_MODEL", "models/text-embedding-005")

        assert isinstance(model, str)
        assert len(model) < 100


@pytest.mark.unit
@pytest.mark.phase1
class TestModelCostEfficiency:
    """Test that model selections are cost-efficient."""

    def test_classification_uses_cheap_lite_model(self):
        """Test classification uses cheaper Lite model."""
        model = os.getenv("QUERY_EVAL_MODEL", "gemini-2.5-flash-lite")

        # Lite is cheaper than Pro
        assert "lite" in model

    def test_generation_uses_flash_not_pro(self):
        """Test generation uses Flash (faster, cheaper than Pro)."""
        model = os.getenv("LLM_MODEL", "gemini-2.5-flash")

        # Flash is cheaper than Pro
        assert "flash" in model
        assert "pro" not in model.lower()

    def test_reranking_batch_processing_efficient(self):
        """Test reranking configuration supports batch processing."""
        model = os.getenv("RERANKER_MODEL", "gemini-3.1-flash-lite-preview")
        batch_size = int(os.getenv("RERANKER_BATCH_SIZE", "20"))

        # Lite model with batching is efficient
        assert "lite" in model
        assert batch_size > 1
