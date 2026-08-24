"""
Contract tests for langchain_agent/lucille-esci/conf/products.conf and judgments.conf.

These tests guard against ingest-contract regressions — fields that the search API,
health check, or retrieval pipeline depend on. A missing stage in the HOCON config
produces zero search results even when doc counts look correct in OpenSearch.

Lessons learned:
- collection_id=esci_products must be set on every product doc; every query in
  vector_store.py filters on it. The field was set by the old Python ingest
  automatically via OpenSearchVectorStore but Lucille does not set it by default.
  PR #41 missed this; caught by health check returning document_count=0 post-ingest.
"""

import re
from pathlib import Path

CONF_DIR = Path(__file__).parent.parent.parent / "lucille-esci" / "conf"
PRODUCTS_CONF = CONF_DIR / "products.conf"
JUDGMENTS_CONF = CONF_DIR / "judgments.conf"


def _read(path: Path) -> str:
    assert path.exists(), f"Config not found: {path}"
    return path.read_text()


# ── products.conf ─────────────────────────────────────────────────────────────


def test_products_conf_exists():
    assert PRODUCTS_CONF.exists()


def test_products_conf_sets_collection_id():
    """collection_id=esci_products must appear via SetStaticValues.

    Every search query in vector_store.py adds a filter on this field.
    Without it all searches return 0 results regardless of doc count.
    """
    text = _read(PRODUCTS_CONF)
    assert "SetStaticValues" in text, "SetStaticValues stage missing from products.conf"
    assert "collection_id" in text, "collection_id not configured in products.conf"
    assert "esci_products" in text, "collection_id value 'esci_products' missing from products.conf"


def test_products_conf_collection_id_value():
    """The collection_id value must exactly match VECTOR_COLLECTION_NAME in config.py."""
    text = _read(PRODUCTS_CONF)
    # Match: "collection_id": "esci_products"  (with optional whitespace)
    assert re.search(
        r'"collection_id"\s*:\s*"esci_products"', text
    ), "collection_id field not set to 'esci_products' in products.conf"


def test_products_conf_builds_chunk_text():
    """chunk_text must be built from product fields (required by BM25 and knn retrieval)."""
    text = _read(PRODUCTS_CONF)
    assert "chunk_text" in text
    assert "Concatenate" in text


def test_products_conf_has_opensearch_indexer():
    text = _read(PRODUCTS_CONF)
    assert 'type: "OpenSearch"' in text or "type: OpenSearch" in text


def test_products_conf_uses_env_var_for_parquet_path():
    """PARQUET_PATH must come from env — never hardcoded."""
    text = _read(PRODUCTS_CONF)
    assert "${PARQUET_PATH}" in text
    # Sanity check: no hardcoded absolute paths
    assert "/Users/" not in text
    assert "/home/" not in text


def test_products_conf_uses_env_var_for_opensearch_url():
    text = _read(PRODUCTS_CONF)
    assert "${OPENSEARCH_URL}" in text
    assert "${OPENSEARCH_INDEX}" in text


def test_products_conf_id_field_is_product_id():
    """product_id must be the OpenSearch document _id to allow idempotent re-ingest."""
    text = _read(PRODUCTS_CONF)
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
