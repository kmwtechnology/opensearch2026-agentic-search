"""
Unit tests for reindex_trigger — the local subprocess mechanism and the
config factory. No network: the local trigger runs against a patched
subprocess.run.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pipeline.reindex_trigger import (
    LocalReindexTrigger,
    ReindexConfigurationError,
    build_reindex_trigger,
)


class TestLocalReindexTrigger:
    @patch("subprocess.run")
    def test_parses_docs_succeeded(self, mock_run):
        result = MagicMock(returncode=0, stderr="")
        result.stdout = "esciProductsConnector: complete. 9618 docs succeeded. 0 docs failed."
        mock_run.return_value = result

        outcome = LocalReindexTrigger(timeout_seconds=1).trigger()

        assert outcome.success is True
        assert outcome.mode == "local"
        assert outcome.docs_processed == 9618
        args, kwargs = mock_run.call_args
        assert args[0] == ["bash", "scripts/lucille_ingest.sh", "--skip-judgments"]
        assert kwargs["timeout"] == 1

    @patch("subprocess.run")
    def test_nonzero_exit_reports_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="lucille error")

        outcome = LocalReindexTrigger().trigger()

        assert outcome.success is False
        assert outcome.docs_processed == 0
        assert "exited 1" in outcome.error

    @patch("subprocess.run")
    def test_timeout_reports_failure(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="lucille_ingest.sh", timeout=1)

        outcome = LocalReindexTrigger(timeout_seconds=1).trigger()

        assert outcome.success is False
        assert "timed out" in outcome.error


class TestBuildReindexTrigger:
    @patch("pipeline.reindex_trigger.REINDEX_TRIGGER", "local")
    def test_default_is_local(self):
        assert isinstance(build_reindex_trigger(), LocalReindexTrigger)

    def test_unknown_mode_raises(self):
        with pytest.raises(ReindexConfigurationError, match="Unknown REINDEX_TRIGGER"):
            build_reindex_trigger("carrier-pigeon")
