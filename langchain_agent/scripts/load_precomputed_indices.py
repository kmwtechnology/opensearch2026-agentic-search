#!/usr/bin/env python3
"""Fast-path loader: bulk-load the committed precomputed dumps (data/precomputed/*.parquet)
straight into OpenSearch instead of running the full Lucille ETL + Ollama embedding pass.

The dumps are a one-time, already-committed full `_source` export of an index Lucille
actually built (embeddings, attribute detection, seeded color taxonomy) -- this script
recreates each index's mapping fresh, then bulk-loads the exported documents verbatim.
No Ollama call, no Lucille/Docker/Java involved. The export that produced these dumps was
a one-off data-processing exercise against a static corpus and isn't expected to run again;
see data/README.md.

Refuses to load if data/precomputed/dump_metadata.json's products_index_mapping_hash
doesn't match the current INDEX_MAPPING in retrieval/vector_store.py -- a mapping change
means the dump's document shape may no longer match. There's no supported way to refresh
the dump for a new mapping; fall back to `--from-scratch` (the full Lucille ingest) instead.

Usage:
    PYTHONPATH=. python scripts/load_precomputed_indices.py [--reset-index]
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
from opensearchpy import helpers

from core.config import OPENSEARCH_INDEX_NAME
from retrieval.attribute_mapping_store import INDEX_MAPPING as ATTRIBUTE_INDEX_MAPPING
from retrieval.attribute_mapping_store import INDEX_NAME as ATTRIBUTE_INDEX_NAME
from retrieval.vector_store import INDEX_MAPPING, create_opensearch_client

REPO_DIR = Path(__file__).resolve().parent.parent.parent
DUMP_DIR = REPO_DIR / "data" / "precomputed"
JUDGMENTS_INDEX_NAME = "esci_judgments"
JUDGMENTS_MAPPING_PATH = (
    Path(__file__).resolve().parent.parent / "lucille-esci" / "mapping" / "judgments_mapping.json"
)

BULK_CHUNK_SIZE = 2000


def _mapping_hash() -> str:
    return hashlib.sha256(json.dumps(INDEX_MAPPING, sort_keys=True).encode()).hexdigest()[:16]


def _load_metadata() -> dict:
    metadata_path = DUMP_DIR / "dump_metadata.json"
    if not metadata_path.exists():
        raise SystemExit(
            f"No precomputed dump found at {DUMP_DIR}. Run a full ingest instead:\n"
            "  bash scripts/lucille_ingest.sh --reset-index --seed-taxonomy"
        )
    return json.loads(metadata_path.read_text())


def _check_mapping_hash(metadata: dict) -> None:
    current = _mapping_hash()
    dumped = metadata.get("products_index_mapping_hash")
    if current != dumped:
        raise SystemExit(
            f"Precomputed dump's products index mapping (hash {dumped}) doesn't match the "
            f"current INDEX_MAPPING (hash {current}) in retrieval/vector_store.py.\n"
            "The mapping changed since the dump was exported. There's no supported way to "
            "refresh the dump for a new mapping (the one-time export tooling was retired) -- "
            "run the full ingest instead:\n"
            "  python setup.py --from-scratch"
        )


def _recreate_index(client, index: str, mapping_body: dict, reset: bool) -> None:
    exists = client.indices.exists(index=index)
    if exists and reset:
        client.indices.delete(index=index)
        exists = False
    if not exists:
        client.indices.create(index=index, body=mapping_body)


def _bulk_load(client, index: str, parquet_path: Path) -> int:
    table = pq.read_table(parquet_path)
    docs = table.to_pylist()

    # Disable refresh during the bulk load for speed; restore + force a
    # refresh afterward so counts are immediately visible.
    client.indices.put_settings(index=index, body={"index": {"refresh_interval": "-1"}})

    def _actions():
        for doc in docs:
            doc_id = doc.pop("_id", None)
            action = {"_index": index, "_source": doc}
            if doc_id is not None:
                action["_id"] = doc_id
            yield action

    success, errors = helpers.bulk(
        client, _actions(), chunk_size=BULK_CHUNK_SIZE, request_timeout=120, raise_on_error=False
    )
    if errors:
        raise RuntimeError(f"{len(errors)} documents failed to index into {index}: {errors[:5]}")

    client.indices.put_settings(index=index, body={"index": {"refresh_interval": "1s"}})
    client.indices.refresh(index=index)
    return success


def main() -> int:
    parser = argparse.ArgumentParser(description="Bulk-load precomputed index dumps")
    parser.add_argument(
        "--reset-index",
        action="store_true",
        help="Delete existing indices before loading (use when re-loading over a dirty cluster)",
    )
    args = parser.parse_args()

    metadata = _load_metadata()
    _check_mapping_hash(metadata)

    client = create_opensearch_client()

    print(f"Loading products -> {OPENSEARCH_INDEX_NAME}...")
    _recreate_index(client, OPENSEARCH_INDEX_NAME, INDEX_MAPPING, args.reset_index)
    n_products = _bulk_load(client, OPENSEARCH_INDEX_NAME, DUMP_DIR / "products_dump.parquet")
    print(f"  loaded {n_products} products")

    print(f"Loading attribute mappings -> {ATTRIBUTE_INDEX_NAME}...")
    _recreate_index(client, ATTRIBUTE_INDEX_NAME, ATTRIBUTE_INDEX_MAPPING, args.reset_index)
    n_mappings = _bulk_load(
        client, ATTRIBUTE_INDEX_NAME, DUMP_DIR / "attribute_mappings_dump.parquet"
    )
    print(f"  loaded {n_mappings} attribute mappings")

    print(f"Loading judgments -> {JUDGMENTS_INDEX_NAME}...")
    judgments_mapping = json.loads(JUDGMENTS_MAPPING_PATH.read_text())
    _recreate_index(client, JUDGMENTS_INDEX_NAME, judgments_mapping, args.reset_index)
    n_judgments = _bulk_load(client, JUDGMENTS_INDEX_NAME, DUMP_DIR / "judgments_dump.parquet")
    print(f"  loaded {n_judgments} judgments")

    expected = metadata.get("counts", {})
    mismatches = []
    for name, actual in (
        ("products", n_products),
        ("attribute_mappings", n_mappings),
        ("judgments", n_judgments),
    ):
        exp = expected.get(name)
        if exp is not None and exp != actual:
            mismatches.append(f"{name}: expected {exp}, loaded {actual}")
    if mismatches:
        print("WARNING: document count mismatch vs. dump_metadata.json:")
        for m in mismatches:
            print(f"  {m}")

    print("\nPrecomputed load complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
