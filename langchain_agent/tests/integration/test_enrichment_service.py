"""
Integration tests for enrichment_service.enrich_attribute — the generic
(color/material/any future type) synchronous flow the live agent enrichment
tool calls: classify -> write mapping -> ensure index fields -> trigger a
real Lucille reindex (which regenerates products.generated.conf itself).

Most tests mock the reindex subprocess call (subprocess.run) so they stay
fast and don't require a full ~20s Lucille run for every assertion — the
classification/mapping/mapping-field logic is what's under test there. One
test (TestRealReindexEndToEnd) exercises the actual subprocess trigger
end-to-end and is slow (~20s) by nature; it uses a disposable test attribute
type/variant, cleaned up after, so it never touches real color/material data
or the demo's reserved gap terms.

Uses a dedicated test index for the attribute mapping store so these tests
never touch real taxonomy data.

Requires a live local OpenSearch (docker compose up -d).
"""

import subprocess
from unittest.mock import MagicMock, patch

import pytest

from pipeline import reindex_trigger
from quality import enrichment_service
from retrieval import attribute_mapping_store as store_module
from retrieval.attribute_mapping_store import AttributeMappingStore

pytestmark = pytest.mark.integration

MAPPING_TEST_INDEX = "test_attribute_mappings_enrichment_v2"


@pytest.fixture
def store(monkeypatch):
    """AttributeMappingStore.get_lookup_table() caches by (INDEX_NAME,
    attribute_type) (see #25). Every test in this file shares the same
    MAPPING_TEST_INDEX name, so without clearing the cache on both sides,
    a lookup cached by one test (e.g. an assertion's own
    store.get_lookup_table(...) call) would leak into the next test's
    freshly-deleted-and-recreated index."""
    monkeypatch.setattr(store_module, "INDEX_NAME", MAPPING_TEST_INDEX)
    store_module._clear_lookup_cache()
    s = AttributeMappingStore()
    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])
    yield s
    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])
    store_module._clear_lookup_cache()


def _mock_successful_subprocess():
    result = MagicMock()
    result.returncode = 0
    result.stdout = "esciProductsConnector: complete. 9618 docs succeeded. 0 docs failed."
    result.stderr = ""
    return result


class TestEnrichAttributeClassification:
    """Classification/mapping logic, subprocess mocked."""

    @patch("subprocess.run")
    def test_dictionary_match_succeeds_without_llm(self, mock_run, store):
        mock_run.return_value = _mock_successful_subprocess()

        result = enrichment_service.enrich_attribute("material", "cowhide", store=store)

        assert result.success is True
        assert result.canonical == "leather"
        assert result.reindex_success is True
        assert result.docs_processed == 9618

    @patch("subprocess.run")
    def test_color_attribute_type_works_too(self, mock_run, store):
        mock_run.return_value = _mock_successful_subprocess()

        result = enrichment_service.enrich_attribute("color", "charcoal", store=store)

        assert result.success is True
        assert result.canonical == "black"

    @patch("subprocess.run")
    def test_llm_fallback_invoked_for_novel_term(self, mock_run, store):
        mock_run.return_value = _mock_successful_subprocess()

        def fake_llm(term, canonicals):
            assert term == "unobtainium"
            return "metal"

        result = enrichment_service.enrich_attribute(
            "material", "unobtainium", llm_classify_fn=fake_llm, store=store
        )

        assert result.success is True
        assert result.canonical == "metal"

    def test_unknown_attribute_type_fails_without_touching_reindex(self, store):
        result = enrichment_service.enrich_attribute("pattern", "polka-dot", store=store)

        assert result.success is False
        assert "unknown attribute_type" in result.reason
        assert result.reindex_triggered is False

    def test_unclassifiable_term_fails_gracefully_without_reindex(self, store):
        result = enrichment_service.enrich_attribute(
            "material", "xyznonsense", llm_classify_fn=lambda t, c: None, store=store
        )

        assert result.success is False
        assert result.reindex_triggered is False

    def test_already_mapped_term_is_idempotent(self, store):
        store.add_mapping("material", "cowhide", "leather", source="seed")

        result = enrichment_service.enrich_attribute("material", "cowhide", store=store)

        assert result.success is False
        assert result.reason == "already mapped"
        assert result.reindex_triggered is False

    def test_already_mapped_with_same_explicit_canonical_is_still_idempotent(self, store):
        """Re-requesting the SAME canonical the variant is already mapped to
        (not a real correction) stays a no-op, even with explicit_canonical
        set -- only a genuinely DIFFERENT canonical should trigger the
        correction path."""
        store.add_mapping("color", "tan", "yellow", source="seed")

        result = enrichment_service.enrich_attribute(
            "color", "tan", store=store, explicit_canonical="yellow"
        )

        assert result.success is False
        assert result.reason == "already mapped"
        assert result.reindex_triggered is False
        assert result.corrected_from is None

    @patch("subprocess.run")
    def test_explicit_canonical_differing_from_existing_corrects_the_mapping(self, mock_run, store):
        """The real bug this exists for: 'tan' was mis-seeded to 'yellow'.
        Supplying a different explicit_canonical overwrites the wrong
        mapping instead of bouncing off the 'already mapped' guard --
        without this, a wrong mapping could never be corrected."""
        mock_run.return_value = _mock_successful_subprocess()
        store.add_mapping("color", "tan", "yellow", source="seed")

        result = enrichment_service.enrich_attribute(
            "color", "tan", store=store, explicit_canonical="brown"
        )

        assert result.success is True
        assert result.canonical == "brown"
        assert result.corrected_from == "yellow"
        assert result.reindex_triggered is True
        # The store itself must reflect the correction, not just the result.
        assert store.get_lookup_table("color")["tan"] == "brown"

    @patch("subprocess.run")
    def test_fresh_mapping_has_no_corrected_from(self, mock_run, store):
        """A genuinely new (not previously mapped) variant is an addition,
        not a correction -- corrected_from must stay None so callers don't
        say "corrected" for something that was never wrong."""
        mock_run.return_value = _mock_successful_subprocess()

        result = enrichment_service.enrich_attribute(
            "material", "chrome", store=store, explicit_canonical="metal"
        )

        assert result.success is True
        assert result.corrected_from is None

    def test_empty_term_fails_gracefully(self, store):
        result = enrichment_service.enrich_attribute("material", "", store=store)
        assert result.success is False
        assert result.reason == "empty term"

    @patch("subprocess.run")
    def test_explicit_canonical_bypasses_classification(self, mock_run, store):
        mock_run.return_value = _mock_successful_subprocess()

        def failing_classify(term, canonicals):
            raise AssertionError("classification should be skipped when explicit_canonical is set")

        result = enrichment_service.enrich_attribute(
            "material",
            "chrome",
            llm_classify_fn=failing_classify,
            store=store,
            explicit_canonical="metal",
        )

        assert result.success is True
        assert result.canonical == "metal"

    def test_explicit_canonical_rejects_unknown_bucket(self, store):
        result = enrichment_service.enrich_attribute(
            "material", "chrome", store=store, explicit_canonical="unobtainium_bucket"
        )

        assert result.success is False
        assert "not a known canonical" in result.reason

    @patch("subprocess.run")
    def test_writes_mapping_before_triggering_reindex(self, mock_run, store):
        mock_run.return_value = _mock_successful_subprocess()

        enrichment_service.enrich_attribute("material", "cowhide", store=store)

        lookup = store.get_lookup_table("material")
        assert lookup.get("cowhide") == "leather"
        mock_run.assert_called_once()


class TestReindexFailureHandling:
    @patch("subprocess.run")
    def test_nonzero_exit_code_reports_reindex_failure_not_overall_failure(self, mock_run, store):
        """Mapping was still written (real taxonomy growth) even if the
        triggered reindex itself failed — success=True, reindex_success=False."""
        result = MagicMock()
        result.returncode = 1
        result.stdout = ""
        result.stderr = "some lucille error"
        mock_run.return_value = result

        outcome = enrichment_service.enrich_attribute("material", "cowhide", store=store)

        assert outcome.success is True  # mapping write succeeded
        assert outcome.reindex_triggered is True
        assert outcome.reindex_success is False
        assert outcome.docs_processed == 0

        # Mapping was still persisted despite the reindex failure
        assert store.get_lookup_table("material").get("cowhide") == "leather"

    @patch("subprocess.run")
    def test_timeout_reports_reindex_failure(self, mock_run, store):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="lucille_ingest.sh", timeout=180)

        outcome = enrichment_service.enrich_attribute("material", "cowhide", store=store)

        assert outcome.success is True
        assert outcome.reindex_success is False


_MINIMAL_ANALYSIS_SETTINGS = {
    "settings": {
        "analysis": {
            "analyzer": {
                "light_english_analyzer": {"tokenizer": "standard", "filter": ["lowercase"]},
                "heavy_english_analyzer": {"tokenizer": "standard", "filter": ["lowercase"]},
            }
        }
    }
}


class TestEnsureAttributeFieldsMapped:
    def test_adds_fields_when_missing(self, store):
        # Use a throwaway index (with the same custom analyzers the real
        # product index already has configured) so this test doesn't depend
        # on the real product index's current mapping state.
        test_docs_index = "test_enrichment_mapping_fields"
        store.client.indices.delete(index=test_docs_index, ignore=[404])
        store.client.indices.create(index=test_docs_index, body=_MINIMAL_ANALYSIS_SETTINGS)

        with patch("core.config.OPENSEARCH_INDEX_NAME", test_docs_index):
            enrichment_service._ensure_attribute_fields_mapped(store, "pattern")

            mapping = store.client.indices.get_mapping(index=test_docs_index)
            props = mapping[test_docs_index]["mappings"]["properties"]
            assert "product_pattern" in props
            assert "product_pattern_primary" in props
            assert "product_pattern_secondary" in props

        store.client.indices.delete(index=test_docs_index, ignore=[404])

    def test_noop_when_fields_already_present(self, store):
        test_docs_index = "test_enrichment_mapping_fields_existing"
        store.client.indices.delete(index=test_docs_index, ignore=[404])
        store.client.indices.create(
            index=test_docs_index,
            body={"mappings": {"properties": {"product_material_primary": {"type": "keyword"}}}},
        )

        with patch("core.config.OPENSEARCH_INDEX_NAME", test_docs_index):
            # Should not raise, should not error on an existing field
            enrichment_service._ensure_attribute_fields_mapped(store, "material")

        store.client.indices.delete(index=test_docs_index, ignore=[404])


class TestParseDocsSucceeded:
    def test_parses_real_lucille_output(self):
        output = (
            "esciProductsConnector: complete. 9618 docs succeeded. 0 docs failed. 0 docs dropped."
        )
        assert reindex_trigger._parse_docs_succeeded(output) == 9618

    def test_returns_zero_when_no_match(self):
        assert reindex_trigger._parse_docs_succeeded("some unrelated output") == 0


class TestRealReindexEndToEnd:
    """The one test that triggers an actual Lucille reindex (~20s). Uses a
    disposable attribute type + variant so it never touches real color/
    material taxonomy or the demo's reserved live-gap term.

    Note: the reindex subprocess is a separate Python process — it doesn't
    see the store fixture's monkeypatched test index, so it regenerates
    products.generated.conf from and reindexes against the REAL production
    attribute types/index. That's fine here: this test validates the
    subprocess-orchestration mechanism (wait, capture output, parse doc
    count, measure duration), not that the disposable type is reflected in
    that specific run."""

    @pytest.mark.slow
    def test_real_reindex_completes_and_reports_docs_processed(self, store):
        # Register a throwaway attribute type's canonical seed just for this
        # test, since enrich_attribute validates against known types.
        enrichment_service._CANONICAL_SEEDS_BY_TYPE["_test_only"] = {
            "test_bucket": ["zzz_test_variant"]
        }
        try:
            result = enrichment_service.enrich_attribute(
                "_test_only", "zzz_test_variant", store=store
            )

            assert result.success is True
            assert result.reindex_triggered is True
            assert result.reindex_success is True
            assert result.docs_processed > 9000  # full catalog reindexed
            assert result.duration_seconds > 0
        finally:
            del enrichment_service._CANONICAL_SEEDS_BY_TYPE["_test_only"]
