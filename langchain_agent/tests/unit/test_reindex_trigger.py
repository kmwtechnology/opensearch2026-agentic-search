"""
Unit tests for reindex_trigger — the scoped re-tag trigger and the factory.
"""

from unittest.mock import patch

from pipeline.reindex_trigger import (
    _LOCAL_REINDEX_LOCK,
    ScopedRetagTrigger,
    build_reindex_trigger,
)


class TestBuildReindexTrigger:
    def test_returns_scoped(self):
        assert isinstance(build_reindex_trigger(), ScopedRetagTrigger)


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
