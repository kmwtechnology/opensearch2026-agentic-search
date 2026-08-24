#!/usr/bin/env python3
"""
Pre-aggregate ESCI judgments for Lucille ingest.

Reads the raw 2.6M-row shopping_queries_dataset_examples.parquet (one row per
query+product pair) and produces a 97k-row esci_judgments_aggregated.parquet
(one row per unique query).

The `judgments_json` column stores a JSON object {"judgments": [...]} that
Lucille's ParseJson stage expands into the nested `judgments` field required
by the esci_judgments OpenSearch index.

Output: esci/shopping_queries_dataset/esci_judgments_aggregated.parquet

Usage:
    python scripts/prepare_judgments_parquet.py
    python scripts/prepare_judgments_parquet.py --locale us
    python scripts/prepare_judgments_parquet.py --force   # re-aggregate even if output exists
"""

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ESCI_RELEVANCE = {"E": 4.0, "S": 1.0, "C": 0.1, "I": 0.0}

BASE_DIR = Path(__file__).parent.parent.parent
# Raw ESCI dataset — external clone, not tracked in git
EXAMPLES_PARQUET = (
    BASE_DIR / "esci" / "shopping_queries_dataset" / "shopping_queries_dataset_examples.parquet"
)
# Output goes to data/ — tracked in git alongside the precomputed products sample
OUTPUT_PARQUET = BASE_DIR / "data" / "esci_judgments_aggregated.parquet"


def aggregate(locale: str = "us") -> pd.DataFrame:
    if not EXAMPLES_PARQUET.exists():
        print(f"ERROR: {EXAMPLES_PARQUET} not found", file=sys.stderr)
        sys.exit(1)

    print(f"Loading {EXAMPLES_PARQUET} ...", flush=True)
    df = pd.read_parquet(EXAMPLES_PARQUET)
    print(f"  Loaded {len(df):,} rows", flush=True)

    if locale:
        df = df[df["product_locale"] == locale].copy()
        print(f"  Filtered to locale={locale}: {len(df):,} rows", flush=True)

    df["relevance"] = df["esci_label"].map(ESCI_RELEVANCE).astype(float)
    df = df.sort_values(["query_id", "relevance"], ascending=[True, False])

    rows = []
    for query_id, group in df.groupby("query_id", sort=False):
        first = group.iloc[0]
        label_counts = group["esci_label"].value_counts().to_dict()
        judgments = [
            {
                "product_id": str(r.product_id),
                "esci_label": str(r.esci_label),
                "relevance": float(r.relevance),
            }
            for r in group.itertuples(index=False)
        ]
        rows.append(
            {
                "query_id": str(query_id),
                "query": str(first.query).strip(),
                "locale": str(first.product_locale),
                "split": str(first.split),
                "small_version": bool(int(first.small_version)),
                "large_version": bool(int(first.large_version)),
                "num_judgments": len(judgments),
                # JSON object wrapper so Lucille's ParseJson stage can extract
                # the array without needing jsonFieldPaths config
                "judgments_json": json.dumps({"judgments": judgments}),
            }
        )

    out = pd.DataFrame(rows)
    print(f"  Aggregated {len(out):,} queries", flush=True)
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--locale", default="us", help="ESCI locale (default: us)")
    parser.add_argument(
        "--force", action="store_true", help="Re-aggregate even if output already exists"
    )
    args = parser.parse_args()

    if OUTPUT_PARQUET.exists() and not args.force:
        print(f"Output already exists: {OUTPUT_PARQUET}", flush=True)
        print("  Use --force to re-aggregate.", flush=True)
        return

    df = aggregate(args.locale)
    OUTPUT_PARQUET.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(OUTPUT_PARQUET, index=False)
    print(
        f"Written: {OUTPUT_PARQUET} ({OUTPUT_PARQUET.stat().st_size // 1024 / 1024:.1f} MB)",
        flush=True,
    )


if __name__ == "__main__":
    main()
