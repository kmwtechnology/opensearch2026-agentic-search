"""Configuration tests that exercise the real `core.config` module and the
agent's startup prerequisite checks."""

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.mark.unit
@pytest.mark.phase1
class TestStartupPrerequisites:
    def test_ollama_settings_in_config_all(self):
        """OLLAMA_* settings must be exported so callers can import them."""
        from core import config

        for name in ("OLLAMA_HOST", "OLLAMA_KEEP_ALIVE", "OLLAMA_NUM_CTX"):
            assert name in config.__all__

    @staticmethod
    def _agent_with_healthy_stores(bare_agent):
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

    def test_llm_temperature_is_a_real_float_config_attribute(self):
        """Regression: `int(os.getenv("LLM_TEMPERATURE", 0))` made LLM_TEMPERATURE=0.7
        raise at import time. Check the real module attribute, not a re-parsed literal."""
        from core import config

        assert isinstance(config.LLM_TEMPERATURE, float)

        with patch.dict(os.environ, {"LLM_TEMPERATURE": "0.7"}):
            importlib.reload(config)
            try:
                assert config.LLM_TEMPERATURE == pytest.approx(0.7)
            finally:
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
            reloaded = importlib.reload(config)
            try:
                assert reloaded.QUERY_EVAL_MODEL == reloaded.LLM_MODEL
                assert reloaded.JUDGE_MODEL == reloaded.LLM_MODEL
            finally:
                importlib.reload(config)

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
