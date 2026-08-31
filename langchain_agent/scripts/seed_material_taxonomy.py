"""
One-time bootstrap: run attribute_discovery.bulk_discover over the real ESCI
product dataset to find material_or_feature signal in title/description/
bullet_point text, then seed the discovered variant->canonical mappings into
the OpenSearch-backed attribute mapping store as attribute_type="material".

This is the "mapping-building is part of enrichment, not hand-authored" step:
the taxonomy is produced by running the same discovery service the live agent
flywheel uses later, against the real data, rather than a hand-curated file.

Usage:
    PYTHONPATH=. python3 scripts/seed_material_taxonomy.py
"""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

from attribute_discovery import MATERIAL_CANONICALS, bulk_discover
from attribute_mapping_store import AttributeMappingStore

PARQUET_PATH = Path(__file__).parent.parent.parent / "data" / "esci_products_sample_10000.parquet"


def main() -> None:
    print(f"Loading {PARQUET_PATH}...")
    df = pd.read_parquet(PARQUET_PATH)

    text_columns = ["product_title", "product_description", "product_bullet_point"]
    texts = []
    for col in text_columns:
        if col in df.columns:
            texts.extend(df[col].dropna().tolist())

    print(f"Scanning {len(texts)} text fields across {len(df)} products...")

    store = AttributeMappingStore()
    existing = store.get_lookup_table("material")
    if existing:
        print(
            f"Existing material taxonomy already has {len(existing)} variants — skipping already-mapped terms."
        )

    discovered = bulk_discover(texts, MATERIAL_CANONICALS, existing_lookup=existing)

    print(f"\nDiscovered {len(discovered)} new variant->canonical mappings:")
    by_canonical: dict = {}
    for variant, canonical in discovered.items():
        by_canonical.setdefault(canonical, []).append(variant)
    for canonical, variants in sorted(by_canonical.items()):
        print(f"  {canonical}: {sorted(variants)}")

    if not discovered:
        print("Nothing new to seed.")
        return

    count = store.seed_from_discovery("material", discovered)
    print(f"\n✅ Seeded {count} new material mappings into OpenSearch.")

    # Verify
    lookup = store.get_lookup_table("material")
    print(
        f"Material taxonomy now has {len(lookup)} total variants across "
        f"{len(set(lookup.values()))} canonical buckets."
    )


if __name__ == "__main__":
    main()
