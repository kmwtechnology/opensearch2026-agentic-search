"""
Integration tests for enrichment_service.enrich_attribute — the generic
(color/waterproof/any future type) synchronous flow the live agent enrichment
tool calls: classify -> write mapping -> ensure index fields -> trigger a
scoped re-tag (pipeline/scoped_retag.py).

Most tests inject a fake ReindexTrigger (via enrich_attribute's `trigger=`
param) so they stay fast and don't touch the real product index — the
classification/mapping/mapping-field logic is what's under test there. One
test (TestRealReindexEndToEnd) exercises the actual ScopedRetagTrigger
end-to-end against the live index and is slow by nature; it uses a
disposable test attribute type/variant, cleaned up after, so it never
touches real color/waterproof data or the demo's reserved gap terms.

Uses a dedicated test index for the attribute mapping store so these tests
never touch real taxonomy data.

Requires a live local OpenSearch (docker compose up -d).
"""

from unittest.mock import MagicMock

import pytest

from pipeline.reindex_trigger import ReindexOutcome
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


def _fake_trigger(success: bool = True, docs_processed: int = 31, docs_scanned: int = 274):
    """A ReindexTrigger stand-in that never touches OpenSearch -- injected via
    enrich_attribute's `trigger=` param so these tests can't accidentally
    write to the real product index."""
    trigger = MagicMock()
    trigger.trigger.return_value = ReindexOutcome(
        triggered=True,
        success=success,
        mode="scoped",
        docs_processed=docs_processed if success else 0,
        docs_scanned=docs_scanned if success else 0,
        error=None if success else "scoped re-tag failed",
    )
    return trigger


class TestEnrichAttributeClassification:
    """Classification/mapping logic, reindex trigger faked."""

    def test_dictionary_match_succeeds_without_llm(self, store):
        # "chrome" is a real COLOR_CANONICALS variant (under the "gray"
        # bucket) — proves static dictionary matching without needing
        # llm_classify_fn or explicit_canonical.
        result = enrichment_service.enrich_attribute(
            "color", "chrome", store=store, trigger=_fake_trigger()
        )

        assert result.success is True
        assert result.canonical == "gray"
        assert result.reindex_success is True
        assert result.docs_processed == 31

    def test_color_attribute_type_works_too(self, store):
        result = enrichment_service.enrich_attribute(
            "color", "charcoal", store=store, trigger=_fake_trigger()
        )

        assert result.success is True
        assert result.canonical == "black"

    def test_llm_fallback_invoked_for_novel_term(self, store):
        # WATERPROOF_CANONICALS ships with zero seed variants by design (see
        # attribute_discovery.py), so ANY term -- even "weatherproof" itself
        # -- structurally cannot dictionary-match and must go through the
        # LLM fallback. That's a stronger guarantee than material's old
        # sparse-dictionary version of this test ever gave.
        def fake_llm(term, canonicals):
            assert term == "weatherproof"
            return "waterproof"

        result = enrichment_service.enrich_attribute(
            "waterproof",
            "weatherproof",
            llm_classify_fn=fake_llm,
            store=store,
            trigger=_fake_trigger(),
        )

        assert result.success is True
        assert result.canonical == "waterproof"

    def test_unknown_attribute_type_fails_without_touching_reindex(self, store):
        result = enrichment_service.enrich_attribute("pattern", "polka-dot", store=store)

        assert result.success is False
        assert "unknown attribute_type" in result.reason
        assert result.reindex_triggered is False

    def test_unclassifiable_term_fails_gracefully_without_reindex(self, store):
        result = enrichment_service.enrich_attribute(
            "waterproof", "xyznonsense", llm_classify_fn=lambda t, c: None, store=store
        )

        assert result.success is False
        assert result.reindex_triggered is False

    def test_already_mapped_term_is_idempotent(self, store):
        store.add_mapping("waterproof", "weatherproof", "waterproof", source="seed")

        result = enrichment_service.enrich_attribute("waterproof", "weatherproof", store=store)

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

    def test_explicit_canonical_differing_from_existing_corrects_the_mapping(self, store):
        """The real bug this exists for: 'tan' was mis-seeded to 'yellow'.
        Supplying a different explicit_canonical overwrites the wrong
        mapping instead of bouncing off the 'already mapped' guard --
        without this, a wrong mapping could never be corrected."""
        store.add_mapping("color", "tan", "yellow", source="seed")

        result = enrichment_service.enrich_attribute(
            "color", "tan", store=store, explicit_canonical="brown", trigger=_fake_trigger()
        )

        assert result.success is True
        assert result.canonical == "brown"
        assert result.corrected_from == "yellow"
        assert result.reindex_triggered is True
        # The store itself must reflect the correction, not just the result.
        assert store.get_lookup_table("color")["tan"] == "brown"

    def test_fresh_mapping_has_no_corrected_from(self, store):
        """A genuinely new (not previously mapped) variant is an addition,
        not a correction -- corrected_from must stay None so callers don't
        say "corrected" for something that was never wrong."""
        result = enrichment_service.enrich_attribute(
            "waterproof",
            "weatherproof",
            store=store,
            explicit_canonical="waterproof",
            trigger=_fake_trigger(),
        )

        assert result.success is True
        assert result.corrected_from is None

    def test_empty_term_fails_gracefully(self, store):
        result = enrichment_service.enrich_attribute("waterproof", "", store=store)
        assert result.success is False
        assert result.reason == "empty term"

    def test_explicit_canonical_bypasses_classification(self, store):
        def failing_classify(term, canonicals):
            raise AssertionError("classification should be skipped when explicit_canonical is set")

        result = enrichment_service.enrich_attribute(
            "waterproof",
            "weatherproof",
            llm_classify_fn=failing_classify,
            store=store,
            explicit_canonical="waterproof",
            trigger=_fake_trigger(),
        )

        assert result.success is True
        assert result.canonical == "waterproof"

    def test_explicit_canonical_rejects_unknown_bucket(self, store):
        result = enrichment_service.enrich_attribute(
            "waterproof", "weatherproof", store=store, explicit_canonical="unobtainium_bucket"
        )

        assert result.success is False
        assert "not a known canonical" in result.reason

    def test_writes_mapping_before_triggering_reindex(self, store):
        fake = _fake_trigger()
        enrichment_service.enrich_attribute(
            "waterproof",
            "weatherproof",
            store=store,
            explicit_canonical="waterproof",
            trigger=fake,
        )

        lookup = store.get_lookup_table("waterproof")
        assert lookup.get("weatherproof") == "waterproof"
        fake.trigger.assert_called_once()


class TestReindexFailureHandling:
    def test_failed_reindex_reports_reindex_failure_not_overall_failure(self, store):
        """Mapping was still written (real taxonomy growth) even if the
        triggered reindex itself failed — success=True, reindex_success=False."""
        outcome = enrichment_service.enrich_attribute(
            "waterproof",
            "weatherproof",
            store=store,
            explicit_canonical="waterproof",
            trigger=_fake_trigger(success=False),
        )

        assert outcome.success is True  # mapping write succeeded
        assert outcome.reindex_triggered is True
        assert outcome.reindex_success is False
        assert outcome.docs_processed == 0

        # Mapping was still persisted despite the reindex failure
        assert store.get_lookup_table("waterproof").get("weatherproof") == "waterproof"


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

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.config.OPENSEARCH_INDEX_NAME", test_docs_index)
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
            body={"mappings": {"properties": {"product_waterproof_primary": {"type": "keyword"}}}},
        )

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr("core.config.OPENSEARCH_INDEX_NAME", test_docs_index)
            # Should not raise, should not error on an existing field
            enrichment_service._ensure_attribute_fields_mapped(store, "waterproof")

        store.client.indices.delete(index=test_docs_index, ignore=[404])


class TestRealReindexEndToEnd:
    """The one test that triggers an actual scoped re-tag (pipeline/
    scoped_retag.py) against the live product index. Uses a disposable
    attribute type + a variant that matches nothing real, so it never
    touches real color/waterproof taxonomy or the demo's reserved live-gap
    term, and never mutates any real product."""

    @pytest.mark.slow
    def test_real_reindex_completes_and_reports_zero_candidates(self, store):
        # Register a throwaway attribute type's canonical seed just for this
        # test, since enrich_attribute validates against known types.
        enrichment_service._CANONICAL_SEEDS_BY_TYPE["_test_only"] = {
            "test_bucket": ["zzz_test_variant_no_product_mentions_this"]
        }
        try:
            result = enrichment_service.enrich_attribute(
                "_test_only", "zzz_test_variant_no_product_mentions_this", store=store
            )

            assert result.success is True
            assert result.reindex_triggered is True
            assert result.reindex_success is True
            # Nothing in the real catalog mentions this made-up term, so the
            # scoped candidate query finds (and updates) nothing -- this
            # still proves the real ScopedRetagTrigger path runs end-to-end
            # against live OpenSearch without mutating any real product.
            assert result.docs_processed == 0
            assert result.duration_seconds >= 0
        finally:
            del enrichment_service._CANONICAL_SEEDS_BY_TYPE["_test_only"]
