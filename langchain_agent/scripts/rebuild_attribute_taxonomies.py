"""
Rebuild the color attribute taxonomy from scratch via discovery against real
chunk_text — not migrated from color_mappings.json, not hand-authored. This
is the "mapping-building is part of enrichment, not hand-authored" principle.

Wipes any existing color docs from the OS-backed mapping store, then runs
attribute_discovery.bulk_discover against the real product catalog's
chunk_text (title + description + bullet_point, as already indexed) seeded
by COLOR_CANONICALS.

Deliberately does NOT touch the "waterproof" attribute type. Its seed dict
(WATERPROOF_CANONICALS in attribute_discovery.py) ships with zero variants
on purpose — it's grown entirely by the live enrichment flywheel
(trigger_enrichment / POST /api/admin/enrich), not bootstrapped here. Adding
a rebuild("waterproof", ...) call would call clear_attribute_type() first,
which would silently wipe out whatever the live demo has already taught the
catalog every time this script runs — the opposite of what a "seed" step
should do for an attribute type that's supposed to start empty and grow.

Used to validate discovery quality ahead of the live demo, and to rehearse
the color-correction arc end-to-end before the conference.

Also the seeding step behind `scripts/lucille_ingest.sh --seed-taxonomy`
(`make seed-taxonomy`; the `seed_taxonomy` input on the Re-Index OpenSearch
workflow), which runs it between two products passes so a cluster whose
mapping store is empty -- the hosted one was, see #71 -- ends up with
product_color_primary populated. Targets whatever cluster config.py's
OPENSEARCH_* point at, so it needs nothing beyond requirements-setup.txt (no
torch/pandas).

DESTRUCTIVE: every existing color mapping is deleted first, including
agent-learned ones from the enrichment flywheel.

Usage:
    PYTHONPATH=. python3 scripts/rebuild_attribute_taxonomies.py [--dry-run]
"""

import argparse
import sys
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.config import OPENSEARCH_INDEX_NAME
from retrieval.attribute_discovery import COLOR_CANONICALS, bulk_discover
from retrieval.attribute_mapping_store import INDEX_NAME, AttributeMappingStore


def fetch_chunk_texts(store: AttributeMappingStore) -> List[str]:
    """Fetch chunk_text for every product in the live index (scroll API)."""
    texts: List[str] = []
    response = store.client.search(
        index=OPENSEARCH_INDEX_NAME,
        body={"query": {"match_all": {}}, "_source": ["chunk_text"], "size": 1000},
        scroll="2m",
    )
    scroll_id = response.get("_scroll_id")

    while response["hits"]["hits"]:
        for hit in response["hits"]["hits"]:
            text = hit["_source"].get("chunk_text")
            if text:
                texts.append(text)
        response = store.client.scroll(scroll_id=scroll_id, scroll="2m")

    if scroll_id:
        store.client.clear_scroll(scroll_id=scroll_id)

    return texts


def clear_attribute_type(store: AttributeMappingStore, attribute_type: str) -> int:
    """Delete every doc for an attribute_type. Returns count deleted."""
    store.ensure_index_exists()
    response = store.client.delete_by_query(
        index=INDEX_NAME,
        body={"query": {"term": {"attribute_type": attribute_type}}},
        refresh=True,
    )
    return response.get("deleted", 0)


def rebuild(attribute_type: str, canonicals: dict, texts: List[str], dry_run: bool) -> None:
    store = AttributeMappingStore()

    deleted = 0 if dry_run else clear_attribute_type(store, attribute_type)
    print(f"[{attribute_type}] Cleared {deleted} existing mapping(s).")

    discovered = bulk_discover(texts, canonicals)
    print(
        f"[{attribute_type}] Discovered {len(discovered)} variants from {len(texts)} chunk_text samples."
    )

    by_canonical: dict = {}
    for variant, canonical in discovered.items():
        by_canonical.setdefault(canonical, []).append(variant)
    for canonical, variants in sorted(by_canonical.items()):
        print(f"  {canonical}: {sorted(variants)}")

    if dry_run:
        print(f"[{attribute_type}] Dry run — not writing to OpenSearch.")
        return

    if not discovered:
        print(f"[{attribute_type}] Nothing discovered — skipping seed.")
        return

    count = store.seed_from_discovery(attribute_type, discovered)
    print(f"[{attribute_type}] Seeded {count} mappings into OpenSearch.\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="Discover only, don't write or delete"
    )
    args = parser.parse_args()

    store = AttributeMappingStore()
    print("Fetching chunk_text from the live index...")
    texts = fetch_chunk_texts(store)
    print(f"Fetched {len(texts)} chunk_text values.\n")

    rebuild("color", COLOR_CANONICALS, texts, args.dry_run)

    # One-time migration for clusters provisioned before "material" was
    # retired (#142). Nothing else deletes these rows, and while they exist
    # config_generator.get_all_attribute_types() keeps emitting a
    # detectMaterial stage, so every reindex writes dead product_material*
    # fields -- now via dynamic mapping, since INDEX_MAPPING no longer
    # declares them. Harmless but it silently diverges an upgraded laptop
    # from a fresh `make setup`. A no-op on a cluster that never had them.
    if not args.dry_run:
        retired = clear_attribute_type(store, "material")
        if retired:
            print(f"[material] Cleared {retired} retired mapping(s) (attribute type removed).")


if __name__ == "__main__":
    main()
