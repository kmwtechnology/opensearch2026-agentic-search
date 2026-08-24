"""Unit tests for scripts/prepare_judgments_parquet.py aggregate()."""

import json
import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

# Import aggregate() directly without touching the filesystem paths at module level
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from prepare_judgments_parquet import ESCI_RELEVANCE, aggregate


def _make_examples(rows: list[dict]) -> pd.DataFrame:
    """Build a minimal examples DataFrame matching the ESCI parquet schema."""
    return pd.DataFrame(rows)


SAMPLE_ROWS = [
    {
        "query_id": "q1",
        "query": "wireless headphones",
        "product_id": "B001",
        "esci_label": "E",
        "product_locale": "us",
        "split": "test",
        "small_version": 1,
        "large_version": 0,
    },
    {
        "query_id": "q1",
        "query": "wireless headphones",
        "product_id": "B002",
        "esci_label": "S",
        "product_locale": "us",
        "split": "test",
        "small_version": 1,
        "large_version": 0,
    },
    {
        "query_id": "q1",
        "query": "wireless headphones",
        "product_id": "B003",
        "esci_label": "I",
        "product_locale": "us",
        "split": "test",
        "small_version": 1,
        "large_version": 0,
    },
    {
        "query_id": "q2",
        "query": "blue backpack",
        "product_id": "B004",
        "esci_label": "C",
        "product_locale": "us",
        "split": "train",
        "small_version": 0,
        "large_version": 1,
    },
    {
        "query_id": "q3",
        "query": "foreign product",
        "product_id": "B005",
        "esci_label": "E",
        "product_locale": "es",
        "split": "train",
        "small_version": 0,
        "large_version": 1,
    },
]


@pytest.fixture
def mock_parquet(tmp_path):
    """Write a minimal ESCI examples parquet and patch the module-level path."""
    parquet_path = tmp_path / "shopping_queries_dataset_examples.parquet"
    df = _make_examples(SAMPLE_ROWS)
    df.to_parquet(parquet_path, index=False)
    return parquet_path


def test_aggregate_one_row_per_query(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    # q3 is locale=es, filtered out
    assert len(result) == 2
    assert set(result["query_id"]) == {"q1", "q2"}


def test_aggregate_judgments_json_is_valid(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    q1 = result[result["query_id"] == "q1"].iloc[0]
    parsed = json.loads(q1["judgments_json"])
    assert "judgments" in parsed
    assert len(parsed["judgments"]) == 3


def test_aggregate_relevance_scores_mapped(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    q1 = result[result["query_id"] == "q1"].iloc[0]
    parsed = json.loads(q1["judgments_json"])
    by_product = {j["product_id"]: j["relevance"] for j in parsed["judgments"]}
    assert by_product["B001"] == ESCI_RELEVANCE["E"]  # 4.0
    assert by_product["B002"] == ESCI_RELEVANCE["S"]  # 1.0
    assert by_product["B003"] == ESCI_RELEVANCE["I"]  # 0.0


def test_aggregate_sorted_by_relevance_desc(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    q1 = result[result["query_id"] == "q1"].iloc[0]
    parsed = json.loads(q1["judgments_json"])
    relevances = [j["relevance"] for j in parsed["judgments"]]
    assert relevances == sorted(relevances, reverse=True)


def test_aggregate_num_judgments_correct(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    q1 = result[result["query_id"] == "q1"].iloc[0]
    assert q1["num_judgments"] == 3
    q2 = result[result["query_id"] == "q2"].iloc[0]
    assert q2["num_judgments"] == 1


def test_aggregate_locale_filter(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result_us = aggregate(locale="us")
        result_es = aggregate(locale="es")
    assert len(result_us) == 2
    assert len(result_es) == 1
    assert result_es.iloc[0]["query_id"] == "q3"


def test_aggregate_boolean_fields(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    q1 = result[result["query_id"] == "q1"].iloc[0]
    assert q1["small_version"] == True  # noqa: E712 — np.True_ vs True
    assert q1["large_version"] == False  # noqa: E712


def test_aggregate_required_columns(mock_parquet):
    with patch("prepare_judgments_parquet.EXAMPLES_PARQUET", mock_parquet):
        result = aggregate(locale="us")
    required = {
        "query_id",
        "query",
        "locale",
        "split",
        "small_version",
        "large_version",
        "num_judgments",
        "judgments_json",
    }
    assert required.issubset(set(result.columns))


def test_esci_relevance_mapping():
    assert ESCI_RELEVANCE["E"] == 4.0
    assert ESCI_RELEVANCE["S"] == 1.0
    assert ESCI_RELEVANCE["C"] == 0.1
    assert ESCI_RELEVANCE["I"] == 0.0
