"""
Unit tests for reindex_trigger — the local subprocess mechanism and the
config factory. No network: the local trigger runs against a patched
subprocess.run.
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pipeline.reindex_trigger import (
    _LOCAL_REINDEX_LOCK,
    LocalReindexTrigger,
    ReindexConfigurationError,
    ScopedRetagTrigger,
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
    def test_configured_default_is_scoped(self):
        """A full Lucille run re-embeds ~158K products (30+ min) -- never the default."""
        from core.config import REINDEX_TRIGGER

        assert REINDEX_TRIGGER == "scoped"
        assert isinstance(build_reindex_trigger("scoped"), ScopedRetagTrigger)

    def test_local_is_still_selectable(self):
        assert isinstance(build_reindex_trigger("local"), LocalReindexTrigger)

    def test_unknown_mode_raises(self):
        with pytest.raises(ReindexConfigurationError, match="Unknown REINDEX_TRIGGER"):
            build_reindex_trigger("carrier-pigeon")


class TestScopedRetagTrigger:
    def test_requires_attribute_type_and_variant(self):
        outcome = ScopedRetagTrigger().trigger()
        assert outcome.triggered is False
        assert outcome.success is False

    @patch("retrieval.vector_store.get_shared_opensearch_client")
    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("pipeline.scoped_retag.retag")
    def test_success_reports_updated_and_scanned(self, mock_retag, mock_store, _client):
        from pipeline.scoped_retag import RetagResult

        mock_store.return_value.get_lookup_table.return_value = {"tan": "brown"}
        mock_retag.return_value = RetagResult(candidates=274, updated=31)

        outcome = ScopedRetagTrigger().trigger("color", ["tan"])

        assert (outcome.success, outcome.mode) == (True, "scoped")
        assert (outcome.docs_processed, outcome.docs_scanned) == (31, 274)
        assert mock_retag.call_args.args[2:] == ("color", ["tan"], {"tan": "brown"})

    @patch("retrieval.vector_store.get_shared_opensearch_client")
    @patch("retrieval.attribute_mapping_store.AttributeMappingStore")
    @patch("pipeline.scoped_retag.retag", side_effect=RuntimeError("bulk failed"))
    def test_failure_is_reported_not_raised_and_releases_lock(self, *_):
        outcome = ScopedRetagTrigger().trigger("color", ["tan"])
        assert (outcome.triggered, outcome.success) == (True, False)
        assert "RuntimeError" in outcome.error
        assert not _LOCAL_REINDEX_LOCK.locked()

    def test_refuses_while_another_reindex_holds_the_lock(self):
        assert _LOCAL_REINDEX_LOCK.acquire(blocking=False)
        try:
            outcome = ScopedRetagTrigger().trigger("color", ["tan"])
        finally:
            _LOCAL_REINDEX_LOCK.release()
        assert outcome.triggered is False
        assert "already running" in outcome.error
