"""
Integration tests for config_generator's live-store default: confirm
generate_products_conf(None) actually queries AttributeMappingStore rather
than requiring attribute_types to always be passed explicitly.

Uses a dedicated test index for the attribute mapping store, seeded and torn
down per test, so these never touch real taxonomy data. generate_products_conf
builds its own AttributeMappingStore internally, but the store reads the
module-level INDEX_NAME at call time -- so patching it here redirects that
internal store too, the same way the sibling store/enrichment suites do.

Requires a live local OpenSearch (docker compose up -d).
"""

import re

import pytest

from config_generator import generate_products_conf
from retrieval import attribute_mapping_store as store_module
from retrieval.attribute_mapping_store import AttributeMappingStore

pytestmark = pytest.mark.integration

MAPPING_TEST_INDEX = "test_attribute_mappings_config_generator"

# Underscored on purpose: also pins the attribute_type -> camelCase stage-name
# derivation (test_fabric -> detectTestFabric).
SEEDED_TYPE = "test_fabric"


@pytest.fixture
def store(monkeypatch):
    """Mapping store pointed at a throwaway index, cleaned up after the test."""
    monkeypatch.setattr(store_module, "INDEX_NAME", MAPPING_TEST_INDEX)
    s = AttributeMappingStore()
    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])
    yield s
    s.client.indices.delete(index=MAPPING_TEST_INDEX, ignore=[404])


def test_none_queries_live_store(store):
    """A type registered only in the store must show up as a generated stage.

    Asserting on the seeded type specifically (not merely that *some*
    AttributeDetectorStage was rendered) is what makes this a test of the
    store->config plumbing rather than of the template string.
    """
    store.add_mapping(SEEDED_TYPE, "sailcloth", "canvas", source="test")

    conf = generate_products_conf(None)

    assert "connectors:" in conf
    assert re.search(r'class: "com\.kmwllc\.esci\.AttributeDetectorStage"', conf)
    assert f'attributeType: "{SEEDED_TYPE}"' in conf
    assert 'name: "detectTestFabric"' in conf


def test_empty_store_renders_conf_without_detector_stages(store):
    """No registered types -> still a well-formed conf, just no detector stages.

    Covers the never-created-index path in get_all_attribute_types (the `store`
    fixture deletes the index and nothing recreates it without a write).

    Matches on the rendered `class:` line rather than the bare class name: the
    static prelude mentions AttributeDetectorStage in a comment, so the plain
    substring is present in every generated conf and would never fail here.
    """
    conf = generate_products_conf(None)

    assert "connectors:" in conf
    assert not re.search(r'class: "com\.kmwllc\.esci\.AttributeDetectorStage"', conf)
