#!/usr/bin/env python3
"""Parity check for the precomputed-dump fast path.

Captures top-10 product IDs for a fixed set of hybrid queries against the
live index, so a load from data/precomputed/ can be checked against the full
Lucille ingest it was exported from. Run once against the freshly-ingested
index (capture), reload from the dump, then run again (compare).

Usage:
    PYTHONPATH=. python scripts/verify_precomputed_load.py capture  > /tmp/baseline.json
    # ... reset indices, run scripts/load_precomputed_indices.py ...
    PYTHONPATH=. python scripts/verify_precomputed_load.py compare /tmp/baseline.json
"""

import json
import sys

from core.config import VECTOR_COLLECTION_NAME
from retrieval.embeddings import build_embeddings
from retrieval.vector_store import OpenSearchVectorStore

QUERIES = [
    "wireless bluetooth headphones",
    "blue waterproof backpack",
    "mechanical keyboard",
    "running shoes for men",
    "4k monitor for gaming",
]


def fingerprint() -> dict:
    store = OpenSearchVectorStore(
        embeddings=build_embeddings(), collection_id=VECTOR_COLLECTION_NAME
    )
    out = {}
    for q in QUERIES:
        docs = store.hybrid_search(q, k=10, fetch_k=40, alpha=0.5)
        out[q] = [d.metadata.get("product_id") for d in docs]
    return out


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in ("capture", "compare"):
        print(__doc__)
        return 1

    mode = sys.argv[1]
    current = fingerprint()

    if mode == "capture":
        print(json.dumps(current, indent=2))
        return 0

    if len(sys.argv) < 3:
        print("compare mode requires a baseline file path", file=sys.stderr)
        return 1
    baseline = json.loads(open(sys.argv[2]).read())

    # Compare as sets, not ordered lists: OpenSearch's HNSW graph is an
    # approximate index, so two separate builds over the identical vectors
    # can legitimately tie-break near-equal scores in a different order.
    # The real parity bar is "same top-10 documents", not "same order" --
    # exact order isn't a guarantee HNSW gives even across two runs of the
    # same Lucille ingest.
    mismatches = 0
    for q in QUERIES:
        base_ids, cur_ids = baseline.get(q, []), current.get(q, [])
        if set(base_ids) != set(cur_ids):
            mismatches += 1
            print(f"MISMATCH for {q!r} (different documents, not just order):")
            print(f"  baseline: {base_ids}")
            print(f"  current:  {cur_ids}")
        elif base_ids != cur_ids:
            print(
                f"OK (reordered): {q!r} ({len(cur_ids)} results, same set, different tie-break order)"
            )
        else:
            print(f"OK: {q!r} ({len(cur_ids)} results, identical top-10 order)")

    if mismatches:
        print(f"\n{mismatches}/{len(QUERIES)} queries returned different documents")
        return 1
    print(f"\nAll {len(QUERIES)} queries return the same document set.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
