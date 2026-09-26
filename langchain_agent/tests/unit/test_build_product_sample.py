"""Unit tests for scripts/build_product_sample.py (#147) -- pure functions only."""

import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
from build_product_sample import (  # noqa: E402
    PLACEHOLDER_IMAGE_MARKER,
    load_image_urls,
    product_text,
    select_product_ids,
)


def _judgments(rows):
    """rows: (split, small_version, [product_ids])"""
    return pd.DataFrame(
        [
            {
                "split": split,
                "small_version": small,
                "judgments_json": json.dumps({"judgments": [{"product_id": p} for p in pids]}),
            }
            for split, small, pids in rows
        ]
    )


class TestSelectProductIds:
    def test_only_test_small_queries_are_used(self):
        df = _judgments(
            [
                ("test", True, ["A", "B"]),
                ("train", True, ["TRAIN"]),
                ("test", False, ["LARGE_ONLY"]),
            ]
        )
        assert set(select_product_ids(df, None, 42)) == {"A", "B"}

    def test_products_shared_across_queries_appear_once(self):
        df = _judgments([("test", True, ["A", "B"]), ("test", True, ["B", "C"])])
        ids = select_product_ids(df, None, 42)
        assert sorted(ids) == ["A", "B", "C"]

    def test_cap_never_splits_a_query(self):
        # Every query carries 3 products; a cap of 4 must stop after whole
        # queries, never keep 1 of a query's 3 judged products.
        df = _judgments([("test", True, [f"{q}{i}" for i in range(3)]) for q in "PQRS"])
        ids = select_product_ids(df, 4, 42)
        assert len(ids) == 6
        prefixes = {i[0] for i in ids}
        for prefix in prefixes:
            assert sum(i.startswith(prefix) for i in ids) == 3

    def test_seed_is_deterministic(self):
        df = _judgments([("test", True, [f"{q}"]) for q in "ABCDEFGH"])
        assert select_product_ids(df, 3, 7) == select_product_ids(df, 3, 7)


class TestLoadImageUrls:
    def test_missing_and_placeholder_urls_are_dropped(self, tmp_path):
        csv = tmp_path / "urls.csv"
        csv.write_text(
            "product_id,image_url\n"
            "B1,https://m.media-amazon.com/images/I/real.jpg\n"
            "B2,\n"
            f"B3,https://m.media-amazon.com/images/G/01/{PLACEHOLDER_IMAGE_MARKER}_LTR.jpg\n"
        )
        assert load_image_urls([csv]) == {"B1": "https://m.media-amazon.com/images/I/real.jpg"}

    def test_later_files_supplement_earlier_ones(self, tmp_path):
        a, b = tmp_path / "a.csv", tmp_path / "b.csv"
        a.write_text("product_id,image_url\nB1,https://x/1.jpg\n")
        b.write_text("product_id,image_url\nB2,https://x/2.jpg\n")
        assert load_image_urls([a, b]) == {"B1": "https://x/1.jpg", "B2": "https://x/2.jpg"}


class TestProductText:
    def test_joins_fields_and_skips_nulls(self):
        row = pd.Series(
            {"product_title": "Boot", "product_description": None, "product_bullet_point": "Tan"}
        )
        assert product_text(row) == "Boot\n\nTan"


class TestLoadProducts:
    def test_null_text_fields_become_empty_strings(self, tmp_path, monkeypatch):
        """Null text would leave "{product_description}" in Lucille's chunk_text."""
        import build_product_sample as b

        raw = tmp_path / "products.parquet"
        pd.DataFrame(
            [
                {
                    "product_id": "B1",
                    "product_title": "Waterproof leather hiking boot, long enough to clear the length floor",
                    "product_description": None,
                    "product_bullet_point": None,
                    "product_brand": "X",
                    "product_color": "Tan",
                    "product_locale": "us",
                }
            ]
        ).to_parquet(raw)
        monkeypatch.setattr(b, "RAW_PRODUCTS", raw)

        df = b.load_products({"B1"})

        assert df.loc[0, "product_description"] == ""
        assert df.loc[0, "product_bullet_point"] == ""
