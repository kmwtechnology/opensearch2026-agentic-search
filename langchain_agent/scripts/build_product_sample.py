#!/usr/bin/env python3
"""Build the product corpus parquet from ESCI + SQID image URLs (#147).

Replaces the old random 10k sample. Two things were wrong with sampling
products at random: judgments were nearly useless (a random product set
leaves ~1 judged product per query in the corpus), and almost nothing had a
product image.

This builds the corpus **query-first** instead: take the ESCI US
``split == "test"`` + ``small_version`` queries -- exactly the subset SQID
(Shopping Queries Image Dataset, Crossing Minds, MIT) scraped image URLs for
-- and include *every* judged product for each query. So every query in the
corpus is fully judged, and ~95% of products carry a real ``image_url``.

By default all ~8,956 such queries are used (~165K products). ``--max-products``
caps it (queries are taken in a seeded shuffle and always whole), for a
smaller corpus during development.

Inputs (external, gitignored under ``<repo>/esci/``):

* ``esci/shopping_queries_dataset/shopping_queries_dataset_products.parquet``
  -- the raw ESCI products (1.1 GB, from amazon-science/esci-data).
* ``esci/sqid/product_image_urls.csv`` and ``supp_product_image_urls.csv``
  -- from Crossing-Minds/shopping-queries-image-dataset.
* ``data/esci_judgments_aggregated.parquet`` -- committed; supplies the
  query -> judged-products mapping, so the 2.6M-row examples file isn't needed.

The output is **text only** -- no vectors. Lucille embeds ``chunk_text`` at
ingest with a local Ollama model (``OllamaEmbedStage``, #148), so nothing here
calls a model and the committed parquet stays small.

Usage::

    PYTHONPATH=. python scripts/build_product_sample.py --dry-run   # stats only
    PYTHONPATH=. python scripts/build_product_sample.py             # full build
    PYTHONPATH=. python scripts/build_product_sample.py --max-products 10000
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import pandas as pd

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
REPO_DIR = PROJECT_DIR.parent
ESCI_DIR = REPO_DIR / "esci"

RAW_PRODUCTS = ESCI_DIR / "shopping_queries_dataset" / "shopping_queries_dataset_products.parquet"
SQID_FILES = (
    ESCI_DIR / "sqid" / "product_image_urls.csv",
    ESCI_DIR / "sqid" / "supp_product_image_urls.csv",
)
JUDGMENTS = REPO_DIR / "data" / "esci_judgments_aggregated.parquet"
DEFAULT_OUTPUT = REPO_DIR / "data" / "esci_products.parquet"

LOCALE = "us"
# Data-quality floor carried over from the old BigQuery embedding path:
# products with less text than this are near-empty listings.
MIN_TEXT_LENGTH = 50
# SQID's marker for "no product-specific image exists" (442 rows).
PLACEHOLDER_IMAGE_MARKER = "Default_Background_Art"

TEXT_COLUMNS = ("product_title", "product_description", "product_bullet_point")
OUTPUT_COLUMNS = [
    "product_id",
    "product_title",
    "product_description",
    "product_bullet_point",
    "product_brand",
    "product_color",
    "product_locale",
    "product_image_url",
]


def select_product_ids(
    judgments: pd.DataFrame, max_products: Optional[int], seed: int
) -> List[str]:
    """Product IDs for whole test/small queries, in seeded query order.

    Queries are never split: a query's judged products all go in, or none do.
    That's the point -- a partially-present judgment set is what made the old
    random sample's NDCG meaningless.
    """
    test = judgments[(judgments["split"] == "test") & (judgments["small_version"])]
    queries = list(test["judgments_json"])
    random.Random(seed).shuffle(queries)

    selected: Dict[str, None] = {}  # insertion-ordered set
    for raw in queries:
        if max_products is not None and len(selected) >= max_products:
            break
        for j in json.loads(raw)["judgments"]:
            selected.setdefault(j["product_id"], None)
    return list(selected)


def load_image_urls(paths: Sequence[Path]) -> Dict[str, str]:
    """ASIN -> real image URL. Missing and placeholder URLs are left out."""
    frames = [pd.read_csv(p, dtype=str) for p in paths]
    urls = pd.concat(frames).dropna(subset=["image_url"])
    urls = urls[~urls["image_url"].str.contains(PLACEHOLDER_IMAGE_MARKER, regex=False)]
    return dict(zip(urls["product_id"], urls["image_url"]))


def product_text(row: pd.Series) -> str:
    """Title + description + bullets -- the text the length floor applies to."""
    return "\n".join(str(row[c]) if pd.notna(row[c]) else "" for c in TEXT_COLUMNS).strip()


def load_products(ids: Set[str]) -> pd.DataFrame:
    cols = [c for c in OUTPUT_COLUMNS if c != "product_image_url"]
    df = pd.read_parquet(RAW_PRODUCTS, columns=cols)
    df = df[(df["product_locale"] == LOCALE) & (df["product_id"].isin(ids))].copy()
    df = df.drop_duplicates(subset="product_id")
    df["text"] = df.apply(product_text, axis=1)
    # Lucille's Concatenate (buildChunkText) leaves a literal "{product_description}"
    # placeholder in chunk_text when the field is null -- the old sample shipped
    # that in 45% of products, polluting both BM25 and the embeddings. An empty
    # string substitutes cleanly (RemoveEmptyFields drops it afterwards).
    df[list(TEXT_COLUMNS)] = df[list(TEXT_COLUMNS)].fillna("")
    return df[df["text"].str.len() >= MIN_TEXT_LENGTH].reset_index(drop=True)


def report(df: pd.DataFrame, requested: int) -> None:
    has_image = df["product_image_url"].notna()
    text = df["text"].str.lower()
    print(f"  selected product IDs:     {requested:,}")
    print(f"  kept (US, text >= {MIN_TEXT_LENGTH}):  {len(df):,}")
    print(f"  with real image URL:      {has_image.sum():,} ({has_image.mean():.1%})")
    # Preconditions the scripted demos depend on (see web/src/demos/registry.ts).
    print("  demo preconditions:")
    print(f"    product_color == tan:    {(df['product_color'].str.lower() == 'tan').sum():,}")
    print(
        f"    'boot' in title:         {df['product_title'].str.lower().str.contains('boot').sum():,}"
    )
    print(f"    waterproof in text:      {text.str.contains('waterproof').sum():,}")
    print(f"    'running shoe' in text:  {text.str.contains('running shoe').sum():,}")
    print(
        f"    'sewing machine' title:  {df['product_title'].str.lower().str.contains('sewing machine').sum():,}"
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--max-products", type=int, default=None, help="cap the corpus (default: all test queries)"
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dry-run", action="store_true", help="select + report only; write nothing"
    )
    args = parser.parse_args(argv)

    for path in (RAW_PRODUCTS, JUDGMENTS, *SQID_FILES):
        if not path.exists():
            print(f"ERROR: {path} not found (see data/README.md)", file=sys.stderr)
            return 1

    print("Selecting products query-first ...", flush=True)
    ids = select_product_ids(pd.read_parquet(JUDGMENTS), args.max_products, args.seed)
    df = load_products(set(ids))
    images = load_image_urls(SQID_FILES)
    df["product_image_url"] = df["product_id"].map(images)
    report(df, len(ids))
    if args.dry_run:
        return 0

    out = df[OUTPUT_COLUMNS].sort_values("product_id").reset_index(drop=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    out.to_parquet(args.output, compression="snappy", index=False)
    print(f"Wrote {len(out):,} products -> {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
