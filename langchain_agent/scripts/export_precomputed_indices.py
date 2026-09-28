#!/usr/bin/env python3
"""Export a freshly-ingested OpenSearch cluster to parquet dumps + a metadata
sidecar, for the fast-path loader (scripts/load_precomputed_indices.py).

This is a "run once" export: after `make setup` finishes a full Lucille
ingest (embeddings + attribute detection + seeded color taxonomy), this
script scrolls every document out of the three indices Lucille populated and
writes them to data/precomputed/*.parquet. Those dumps are committed to the
repo via Git LFS so a fresh `make setup` on someone else's machine can
bulk-load them directly instead of re-running the ~35-40 min embedding pass.

Exports (full `_source`, including the `embedding` float vector — nothing is
excluded here the way query-time reads exclude it for response size):
    - products index (OPENSEARCH_INDEX_NAME)              -> products_dump.parquet
    - attribute mapping store (agentic_hybrid_search_attribute_mappings)
                                                            -> attribute_mappings_dump.parquet
    - esci_judgments                                       -> judgments_dump.parquet

Also writes dump_metadata.json: source git commit, EMBEDDINGS_MODEL, and a
hash of the products INDEX_MAPPING at export time. The loader refuses to use
a dump whose mapping hash doesn't match the current INDEX_MAPPING, so a
schema change can't silently load stale-shaped documents.

Usage:
    PYTHONPATH=. python scripts/export_precomputed_indices.py
"""

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from core.config import EMBEDDINGS_MODEL, OPENSEARCH_INDEX_NAME
from retrieval.attribute_mapping_store import INDEX_NAME as ATTRIBUTE_INDEX_NAME
from retrieval.vector_store import INDEX_MAPPING, create_opensearch_client

REPO_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = REPO_DIR / "data" / "precomputed"
JUDGMENTS_INDEX_NAME = "esci_judgments"

SCROLL_SIZE = 2000
SCROLL_TTL = "5m"


def _scroll_all(client, index: str) -> list[dict]:
    """Scroll every document's full _source out of an index."""
    docs: list[dict] = []
    resp = client.search(
        index=index,
        body={"query": {"match_all": {}}},
        scroll=SCROLL_TTL,
        size=SCROLL_SIZE,
    )
    scroll_id = resp.get("_scroll_id")
    try:
        while True:
            hits = resp["hits"]["hits"]
            if not hits:
                break
            for hit in hits:
                doc = dict(hit["_source"])
                doc["_id"] = hit["_id"]
                docs.append(doc)
            resp = client.scroll(scroll_id=scroll_id, scroll=SCROLL_TTL)
            scroll_id = resp.get("_scroll_id")
    finally:
        if scroll_id:
            client.clear_scroll(scroll_id=scroll_id)
    return docs


def _write_parquet(docs: list[dict], path: Path) -> int:
    if not docs:
        raise RuntimeError(f"No documents found — refusing to write an empty dump to {path}")
    table = pa.Table.from_pylist(docs)
    # OpenSearch's knn_vector field (and the embedding model itself) is
    # float32 -- pa.Table.from_pylist infers Python floats as 64-bit,
    # silently doubling the embedding column's size on disk for no benefit.
    if "embedding" in table.column_names:
        idx = table.schema.get_field_index("embedding")
        f32_type = pa.list_(pa.float32())
        table = table.set_column(idx, "embedding", table.column("embedding").cast(f32_type))
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")
    return len(docs)


def _mapping_hash() -> str:
    return hashlib.sha256(json.dumps(INDEX_MAPPING, sort_keys=True).encode()).hexdigest()[:16]


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_DIR).decode().strip()
    except Exception:
        return "unknown"


def main() -> int:
    client = create_opensearch_client()

    print(f"Exporting products index '{OPENSEARCH_INDEX_NAME}'...")
    products = _scroll_all(client, OPENSEARCH_INDEX_NAME)
    n_products = _write_parquet(products, OUTPUT_DIR / "products_dump.parquet")
    print(f"  wrote {n_products} products")

    print(f"Exporting attribute mapping store '{ATTRIBUTE_INDEX_NAME}'...")
    mappings = _scroll_all(client, ATTRIBUTE_INDEX_NAME)
    waterproof_variants = [d for d in mappings if d.get("attribute_type") == "waterproof"]
    if waterproof_variants:
        print(
            f"  ERROR: found {len(waterproof_variants)} 'waterproof' variant mappings in the "
            "store — WATERPROOF_CANONICALS must stay empty and grow only from the live "
            "enrichment flywheel (see CLAUDE.md). Refusing to bake these into a committed "
            "seed. Did you use the chat app / enrichment tool before exporting?"
        )
        return 1
    n_mappings = _write_parquet(mappings, OUTPUT_DIR / "attribute_mappings_dump.parquet")
    print(f"  wrote {n_mappings} attribute mappings (0 waterproof, as expected)")

    print(f"Exporting judgments index '{JUDGMENTS_INDEX_NAME}'...")
    judgments = _scroll_all(client, JUDGMENTS_INDEX_NAME)
    n_judgments = _write_parquet(judgments, OUTPUT_DIR / "judgments_dump.parquet")
    print(f"  wrote {n_judgments} judgments")

    metadata = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": _git_commit(),
        "embeddings_model": EMBEDDINGS_MODEL,
        "products_index_mapping_hash": _mapping_hash(),
        "counts": {
            "products": n_products,
            "attribute_mappings": n_mappings,
            "judgments": n_judgments,
        },
    }
    metadata_path = OUTPUT_DIR / "dump_metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n")
    print(f"Wrote {metadata_path}")
    print(
        "\nDone. Review counts above, run the parity check, then commit data/precomputed/ (Git LFS)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
