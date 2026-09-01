"""
Contract tests for the generated products pipeline config
(config_generator.generate_products_conf) and langchain_agent/lucille-esci/conf/judgments.conf.

These tests guard against ingest-contract regressions — fields that the search API,
health check, or retrieval pipeline depend on. A missing stage in the HOCON config
produces zero search results even when doc counts look correct in OpenSearch.

products.conf itself is retired — the pipeline config is now generated fresh
before every Lucille run (config_generator.py), so these contract tests
validate generate_products_conf()'s *output* rather than a static file. This
preserves the regression coverage below across the rework.

Lessons learned:
- collection_id=esci_products must be set on every product doc; every query in
  vector_store.py filters on it. The field was set by the old Python ingest
  automatically via OpenSearchVectorStore but Lucille does not set it by default.
  PR #41 missed this; caught by health check returning document_count=0 post-ingest.
"""

import re
from pathlib import Path

from config_generator import generate_products_conf

CONF_DIR = Path(__file__).parent.parent.parent / "lucille-esci" / "conf"
JUDGMENTS_CONF = CONF_DIR / "judgments.conf"

# Representative attribute types — the contract being tested here is about
# the fixed prelude/epilogue stages, not the per-type detector blocks.
_SAMPLE_ATTRIBUTE_TYPES = ["color", "material"]


def _read(path: Path) -> str:
    assert path.exists(), f"Config not found: {path}"
    return path.read_text()


# ── generated products config ───────────────────────────────────────────────


def test_generated_conf_sets_collection_id():
    """collection_id=esci_products must appear via SetStaticValues.

    Every search query in vector_store.py adds a filter on this field.
    Without it all searches return 0 results regardless of doc count.
    """
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert "SetStaticValues" in text, "SetStaticValues stage missing from generated config"
    assert "collection_id" in text, "collection_id not configured in generated config"
    assert (
        "esci_products" in text
    ), "collection_id value 'esci_products' missing from generated config"


def test_generated_conf_collection_id_value():
    """The collection_id value must exactly match VECTOR_COLLECTION_NAME in config.py."""
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert re.search(
        r'"collection_id"\s*:\s*"esci_products"', text
    ), "collection_id field not set to 'esci_products' in generated config"


def test_generated_conf_builds_chunk_text():
    """chunk_text must be built from product fields (required by BM25 and knn retrieval)."""
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert "chunk_text" in text
    assert "Concatenate" in text


def test_generated_conf_has_opensearch_indexer():
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert 'type: "OpenSearch"' in text or "type: OpenSearch" in text


def test_generated_conf_uses_env_var_for_parquet_path():
    """PARQUET_PATH must come from env — never hardcoded."""
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert "${PARQUET_PATH}" in text
    # Sanity check: no hardcoded absolute paths
    assert "/Users/" not in text
    assert "/home/" not in text


def test_generated_conf_uses_env_var_for_opensearch_url():
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert "${OPENSEARCH_URL}" in text
    assert "${OPENSEARCH_INDEX}" in text


def test_generated_conf_id_field_is_product_id():
    """product_id must be the OpenSearch document _id to allow idempotent re-ingest."""
    text = generate_products_conf(_SAMPLE_ATTRIBUTE_TYPES)
    assert 'idField: "product_id"' in text


# ── judgments.conf ────────────────────────────────────────────────────────────


def test_judgments_conf_exists():
    assert JUDGMENTS_CONF.exists()


def test_judgments_conf_parses_judgments_json():
    """ParseJson stage must expand the judgments_json column into nested fields."""
    text = _read(JUDGMENTS_CONF)
    assert "ParseJson" in text
    assert "judgments_json" in text


def test_judgments_conf_id_field_is_query_id():
    """query_id must be the document _id for exact-match lookup in lookup_judgments()."""
    text = _read(JUDGMENTS_CONF)
    assert 'idField: "query_id"' in text


def test_judgments_conf_drops_json_string_field():
    """judgments_json must be dropped after parsing to avoid storing the raw string."""
    text = _read(JUDGMENTS_CONF)
    assert "judgments_json" in text
    assert "DeleteFields" in text
