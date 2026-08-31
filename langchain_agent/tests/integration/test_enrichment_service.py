"""
Integration tests for enrichment_service — the synchronous flow the live
agent enrichment tool calls: classify -> write mapping -> scoped
update_by_query.

Uses dedicated test indices for both the attribute mapping store and the
product documents, so these tests never touch real material taxonomy data
(including the actual demo gap term reserved for the live on-stage trigger).

Requires a live local OpenSearch (docker compose up -d).
"""

import pytest

import attribute_mapping_store as store_module
import config
import enrichment_service
from attribute_mapping_store import AttributeMappingStore

pytestmark = pytest.mark.integration

MAPPING_TEST_INDEX = "test_attribute_mappings_enrichment"
DOCS_TEST_INDEX = "test_enrichment_products"

DOCS_MAPPING = {
    "mappings": {
        "properties": {
            "title": {"type": "text"},
            "chunk_text": {"type": "text"},
            "product_material": {"type": "keyword"},
            "product_material_primary": {"type": "keyword"},
        }
    }
}


@pytest.fixture
def store(monkeypatch):
    monkeypatch.setattr(store_module, "INDEX_NAME", MAPPING_TEST_INDEX)
    monkeypatch.setattr(config, "OPENSEARCH_INDEX_NAME", DOCS_TEST_INDEX)

    s = AttributeMappingStore()
    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])
    s.client.indices.delete(index=DOCS_TEST_INDEX, ignore=[404])
    s.client.indices.create(index=DOCS_TEST_INDEX, body=DOCS_MAPPING)

    yield s

    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])
    s.client.indices.delete(index=DOCS_TEST_INDEX, ignore=[404])


def _index_doc(store: AttributeMappingStore, doc_id: str, title: str, chunk_text: str) -> None:
    store.client.index(
        index=DOCS_TEST_INDEX,
        id=doc_id,
        body={"title": title, "chunk_text": chunk_text},
        refresh=True,
    )


class TestEnrichMaterial:
    def test_dictionary_match_succeeds_without_llm(self, store):
        _index_doc(store, "1", "Wallet", "Genuine Cowhide Wallet for Men")

        result = enrichment_service.enrich_material("cowhide", store=store)

        assert result.success is True
        assert result.canonical == "leather"
        assert result.docs_updated == 1

    def test_llm_fallback_invoked_for_novel_term(self, store):
        _index_doc(store, "1", "Faucet", "Unobtainium Bathroom Faucet Fixture")

        def fake_llm(term, canonicals):
            assert term == "unobtainium"
            return "metal"

        result = enrichment_service.enrich_material(
            "unobtainium", llm_classify_fn=fake_llm, store=store
        )

        assert result.success is True
        assert result.canonical == "metal"
        assert result.docs_updated == 1

    def test_unclassifiable_term_fails_gracefully(self, store):
        result = enrichment_service.enrich_material(
            "xyznonsense", llm_classify_fn=lambda t, c: None, store=store
        )

        assert result.success is False
        assert result.reason == "could not classify to a known material bucket"
        assert result.docs_updated == 0

    def test_already_mapped_term_is_idempotent(self, store):
        store.add_mapping("material", "cowhide", "leather", source="seed")

        result = enrichment_service.enrich_material("cowhide", store=store)

        assert result.success is False
        assert result.reason == "already mapped"
        assert result.canonical == "leather"

    def test_empty_term_fails_gracefully(self, store):
        result = enrichment_service.enrich_material("", store=store)
        assert result.success is False
        assert result.reason == "empty term"

    def test_writes_mapping_to_store(self, store):
        _index_doc(store, "1", "Wallet", "Genuine Cowhide Wallet")

        enrichment_service.enrich_material("cowhide", store=store)

        lookup = store.get_lookup_table("material")
        assert lookup.get("cowhide") == "leather"

    def test_only_updates_matching_untagged_documents(self, store):
        _index_doc(store, "1", "Cowhide Boots", "Genuine Cowhide Leather Boots")
        _index_doc(store, "2", "Unrelated", "Plastic Phone Case")
        _index_doc(store, "3", "Already Tagged", "Cowhide Belt")
        store.client.update(
            index=DOCS_TEST_INDEX,
            id="3",
            body={"doc": {"product_material_primary": "leather"}},
            refresh=True,
        )

        result = enrichment_service.enrich_material("cowhide", store=store)

        # doc 1 (matching, untagged) updated; doc 2 (no match) and doc 3
        # (matching but already tagged) are not touched.
        assert result.docs_updated == 1

        doc1 = store.client.get(index=DOCS_TEST_INDEX, id="1")["_source"]
        assert doc1["product_material_primary"] == "leather"
        assert doc1["product_material"] == "cowhide"

        doc2 = store.client.get(index=DOCS_TEST_INDEX, id="2")["_source"]
        assert "product_material_primary" not in doc2

    def test_no_matching_documents_returns_zero_updated(self, store):
        result = enrichment_service.enrich_material("cowhide", store=store)

        assert result.success is True
        assert result.canonical == "leather"
        assert result.docs_updated == 0

    def test_explicit_canonical_bypasses_classification(self, store):
        _index_doc(store, "1", "Faucet", "Chrome Bathroom Faucet Fixture")

        def failing_classify(term, canonicals):
            raise AssertionError("classification should be skipped when explicit_canonical is set")

        result = enrichment_service.enrich_material(
            "chrome", llm_classify_fn=failing_classify, store=store, explicit_canonical="metal"
        )

        assert result.success is True
        assert result.canonical == "metal"
        assert result.docs_updated == 1

    def test_explicit_canonical_rejects_unknown_bucket(self, store):
        result = enrichment_service.enrich_material(
            "chrome", store=store, explicit_canonical="unobtainium_bucket"
        )

        assert result.success is False
        assert "not a known canonical" in result.reason
