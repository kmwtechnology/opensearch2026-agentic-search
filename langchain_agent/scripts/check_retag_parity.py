#!/usr/bin/env python3
"""Check the scoped re-tag against a real, Lucille-built index (#147).

The scoped re-tag (pipeline/scoped_retag.py) is only safe if two things hold
on real data -- neither is provable from unit tests alone:

1. Detection parity: the Python port of AttributeDetectorStage produces the
   exact product_<type>/_primary/_secondary values Lucille's Java stage wrote,
   for every product and every registered attribute type.
2. Candidate recall: for every variant, every product whose chunk_text the
   Java regex would match is returned by candidate_query() -- otherwise a
   scoped re-tag silently skips products a full ingest would have changed.

Read-only. Run after a full ingest, with the backend's .env:

    PYTHONPATH=. python scripts/check_retag_parity.py [--index NAME] [--sample N]

Exit status 0 = both hold; 1 = a mismatch or a recall miss (details printed).
"""

import argparse
import random
import re
import sys
from collections import defaultdict
from typing import Dict, List, Set

from core.config import OPENSEARCH_INDEX_NAME
from pipeline.scoped_retag import build_variant_pattern, candidate_query, tag_fields
from retrieval.attribute_mapping_store import AttributeMappingStore
from retrieval.vector_store import get_shared_opensearch_client

PAGE = 2000


def scan(client, index: str, query: dict, source) -> List[dict]:
    hits, search_after = [], None
    while True:
        body = {"size": PAGE, "query": query, "_source": source, "sort": [{"_id": "asc"}]}
        if search_after is not None:
            body["search_after"] = search_after
        page = client.search(index=index, body=body)["hits"]["hits"]
        if not page:
            return hits
        hits.extend(page)
        search_after = page[-1]["sort"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--index", default=OPENSEARCH_INDEX_NAME)
    parser.add_argument(
        "--sample", type=int, default=0, help="recall check on N random products (0 = all)"
    )
    args = parser.parse_args()

    client = get_shared_opensearch_client()
    store = AttributeMappingStore()
    types = store.get_all_attribute_types()
    lookups = {t: store.get_lookup_table(t) for t in types}
    fields = [f for t in types for f in tag_fields(t, "", {})]

    print(f"Index {args.index}: attribute types {types}")
    docs = scan(client, args.index, {"match_all": {}}, ["chunk_text", *fields])
    print(f"Scanned {len(docs):,} products")
    ok = True

    # 1. Detection parity ------------------------------------------------------
    for t in types:
        pattern = build_variant_pattern(lookups[t])
        mismatches = []
        for d in docs:
            src = d.get("_source", {})
            want = tag_fields(t, src.get("chunk_text", ""), lookups[t], pattern)
            if want[f"product_{t}"] is None:
                del want[f"product_{t}"]  # raw field: dataset value kept, not compared
            got = {k: src.get(k) for k in want}
            if got != want:
                mismatches.append((d["_id"], got, want))
        print(f"[parity] {t}: {len(mismatches)} mismatches of {len(docs):,}")
        for m in mismatches[:5]:
            print(f"    {m[0]}: indexed={m[1]} python={m[2]}")
        ok &= not mismatches

    # 2. Candidate recall ------------------------------------------------------
    pool = docs if not args.sample else random.Random(0).sample(docs, min(args.sample, len(docs)))
    pool_ids = {d["_id"] for d in pool}
    for t in types:
        misses: Dict[str, Set[str]] = defaultdict(set)
        for variant in lookups[t]:
            java_regex = re.compile(rf"\b(?:{re.escape(variant)})\b", re.IGNORECASE | re.ASCII)
            expected = {
                d["_id"] for d in pool if java_regex.search(d["_source"].get("chunk_text", ""))
            }
            if not expected:
                continue
            got = {h["_id"] for h in scan(client, args.index, candidate_query(t, [variant]), False)}
            missed = expected - got
            if missed:
                misses[variant] = missed
        total = sum(len(v) for v in misses.values())
        print(
            f"[recall] {t}: {len(lookups[t])} variants over {len(pool_ids):,} products, "
            f"{total} missed candidates"
        )
        for variant, ids in list(misses.items())[:10]:
            sample_id = next(iter(ids))
            text = next(d for d in pool if d["_id"] == sample_id)["_source"]["chunk_text"]
            at = re.search(re.escape(variant), text, re.IGNORECASE)
            ctx = text[max(0, at.start() - 30) : at.end() + 30] if at else text[:60]
            print(f"    '{variant}': {len(ids)} missed, e.g. {sample_id}: ...{ctx!r}...")
        ok &= not misses

    print("PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
