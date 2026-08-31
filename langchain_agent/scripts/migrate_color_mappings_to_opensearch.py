"""
One-time migration: load lucille-esci/conf/color_mappings.json's base_colors
into the OpenSearch-backed attribute mapping store
(agentic_hybrid_search_attribute_mappings), so the Lucille Java stage and the
Python AttributeNormalizer can both read color mappings from OpenSearch
instead of the bundled JSON file.

Usage:
    PYTHONPATH=. python3 scripts/migrate_color_mappings_to_opensearch.py

Idempotent — safe to re-run; existing mappings with the same canonical are
skipped, differing ones are updated in place.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from attribute_mapping_store import AttributeMappingStore


def main() -> None:
    color_mappings_path = (
        Path(__file__).parent.parent / "lucille-esci" / "conf" / "color_mappings.json"
    )

    with open(color_mappings_path) as f:
        data = json.load(f)

    base_colors = data["base_colors"]
    total_variants = sum(len(variants) for variants in base_colors.values())

    print(f"Migrating {len(base_colors)} canonical colors, {total_variants} variants...")

    store = AttributeMappingStore()
    added_count = store.migrate_from_dict("color", base_colors)

    print(f"Migration complete: {added_count} new mappings added.")

    # Verify: rebuild the expected lookup the same way AttributeNormalizer/
    # AttributeNormalizerStage do (dict-order iteration, last-write-wins),
    # since a handful of variants (e.g. "coral") legitimately appear under
    # more than one canonical in the source JSON — the LAST occurrence in
    # file order is each implementation's real, existing behavior today.
    expected_lookup = {}
    duplicates = []
    for canonical, variants in base_colors.items():
        for variant in variants:
            key = variant.lower()
            if key in expected_lookup and expected_lookup[key] != canonical:
                duplicates.append((variant, expected_lookup[key], canonical))
            expected_lookup[key] = canonical

    if duplicates:
        print(
            f"\n⚠️  {len(duplicates)} variant(s) listed under multiple canonicals "
            f"in color_mappings.json (pre-existing; last one wins, matching current behavior):"
        )
        for variant, first, second in duplicates:
            print(f"  '{variant}': '{first}' -> '{second}' (resolves to '{second}')")

    lookup = store.get_lookup_table("color")
    mismatches = [
        (variant, expected, lookup.get(variant))
        for variant, expected in expected_lookup.items()
        if lookup.get(variant) != expected
    ]

    if mismatches:
        print(f"\n❌ VERIFICATION FAILED: {len(mismatches)} mismatches:")
        for variant, expected, actual in mismatches[:20]:
            print(f"  '{variant}': expected '{expected}', got '{actual}'")
        sys.exit(1)

    print(
        f"✅ Verification passed: all {len(expected_lookup)} unique variants "
        f"resolve identically to the pre-migration normalizer."
    )


if __name__ == "__main__":
    main()
