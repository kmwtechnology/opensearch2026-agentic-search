#!/usr/bin/env python3
"""
Analyze product color attributes and generate normalization mappings.

Usage:
    python scripts/analyze_color_attributes.py

Outputs:
    langchain_agent/lucille-esci/conf/color_mappings.json - canonical colors + synonyms

This script is idempotent and can be re-run as data changes.
"""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import pandas as pd

# Base colors with comprehensive synonyms
BASE_COLORS: Dict[str, List[str]] = {
    "black": ["black", "jet", "charcoal", "ebony", "onyx"],
    "white": ["white", "ivory", "cream", "off-white", "ecru", "beige", "bone"],
    "blue": [
        "blue",
        "navy",
        "cyan",
        "turquoise",
        "teal",
        "aqua",
        "indigo",
        "cobalt",
        "denim",
    ],
    "red": ["red", "crimson", "scarlet", "maroon", "burgundy", "wine", "rust", "brick"],
    "green": [
        "green",
        "lime",
        "emerald",
        "sage",
        "olive",
        "mint",
        "forest",
        "moss",
        "hunter",
    ],
    "yellow": ["yellow", "gold", "amber", "tan", "khaki", "mustard", "champagne"],
    "pink": ["pink", "rose", "mauve", "salmon", "blush", "coral", "fuchsia", "magenta"],
    "purple": ["purple", "violet", "lavender", "plum", "lilac", "eggplant"],
    "brown": [
        "brown",
        "chocolate",
        "bronze",
        "copper",
        "cognac",
        "taupe",
        "mocha",
        "espresso",
        "coffee",
        "caramel",
    ],
    "gray": [
        "gray",
        "grey",
        "silver",
        "ash",
        "slate",
        "pewter",
        "graphite",
        "nickel",
        "chrome",
        "titanium",
    ],
    "orange": ["orange", "coral", "peach", "tangerine", "apricot"],
    "clear": ["clear", "transparent", "translucent", "crystal"],
    "multicolor": [
        "multicolor",
        "multicolored",
        "multi-color",
        "multi-colored",
        "multi",
        "rainbow",
        "colorful",
    ],
    "natural": ["natural", "wood", "natural wood", "unfinished", "raw"],
    "mixed": ["assorted", "mixed", "various", "pattern"],
}


def build_color_lookup() -> Dict[str, str]:
    """Build reverse lookup: variant -> canonical."""
    lookup = {}
    for canonical, variants in BASE_COLORS.items():
        for variant in variants:
            lookup[variant.lower()] = canonical
    return lookup


def normalize_color(
    color_str: str, color_lookup: Dict[str, str]
) -> Tuple[Optional[str], Optional[str]]:
    """
    Normalize a color string to (primary, secondary) canonical forms.

    Args:
        color_str: raw color string from parquet
        color_lookup: variant -> canonical mapping

    Returns:
        (primary_color, secondary_color or None)
    """
    if not color_str or pd.isna(color_str):
        return None, None

    normalized = color_str.lower()

    # Strip leading single letter + space
    normalized = re.sub(r"^[a-z]\s+", "", normalized)

    # Strip trailing noise (numbers, symbols)
    normalized = re.sub(r"[\s#]*\d+\s*$", "", normalized)
    normalized = re.sub(r"[\s]*[.!?]\s*$", "", normalized)

    # Normalize special characters (split on &, /, +)
    normalized = re.sub(r"\s*[&/+]\s*", "|", normalized)

    # Strip descriptive prefixes
    normalized = re.sub(
        r"^(light|dark|pale|deep|bright|soft|matte|glossy|metallic|neon|electric|hot|cool|warm|baby|vintage|antique|distressed|faded|heather|sparkle)\s+",
        "",
        normalized,
    )

    # Remove parenthetical content
    normalized = re.sub(r"\s*\([^)]*\)", "", normalized)

    # Split by separator and find base colors
    parts = [p.strip() for p in normalized.split("|")]
    found_colors = []

    for part in parts:
        words = part.split()
        for word in words:
            clean_word = word.rstrip("s,.-")
            if clean_word in color_lookup:
                found_colors.append(color_lookup[clean_word])
                break  # Use first found color per part

    # Deduplicate while preserving order
    found_colors = list(dict.fromkeys(found_colors))

    primary = found_colors[0] if found_colors else None
    secondary = found_colors[1] if len(found_colors) > 1 else None

    return primary, secondary


def analyze_colors(parquet_path: str) -> Dict:
    """Analyze color attributes from parquet file."""
    df = pd.read_parquet(parquet_path)
    color_values = df["product_color"].dropna()

    color_lookup = build_color_lookup()

    # Apply normalization
    results = []
    for color in color_values.unique():
        count = (color_values == color).sum()
        primary, secondary = normalize_color(color, color_lookup)
        results.append(
            {
                "original": color,
                "count": count,
                "primary": primary or "unclassified",
                "secondary": secondary,
            }
        )

    results_df = pd.DataFrame(results)

    # Build statistics
    primary_dist = (
        results_df.groupby("primary")["count"].sum().sort_values(ascending=False)
    )
    secondary_dist = (
        results_df[results_df["secondary"].notna()]
        .groupby("secondary")["count"]
        .sum()
        .sort_values(ascending=False)
    )

    return {
        "base_colors": BASE_COLORS,
        "statistics": {
            "original_unique_colors": int(color_values.nunique()),
            "total_products": int(len(color_values)),
            "classified_products": int(
                primary_dist.sum() - primary_dist.get("unclassified", 0)
            ),
            "unclassified_products": int(primary_dist.get("unclassified", 0)),
            "products_with_secondary": int(
                results_df[results_df["secondary"].notna()]["count"].sum()
            ),
        },
        "primary_distribution": primary_dist.head(16).to_dict(),
        "secondary_distribution": secondary_dist.head(10).to_dict(),
        "top_examples": [
            {
                "original": row["original"],
                "count": int(row["count"]),
                "primary": row["primary"],
                "secondary": row["secondary"],
            }
            for _, row in results_df.nlargest(30, "count").iterrows()
        ],
    }


def main():
    """Generate color mappings from ESCI parquet."""
    repo_root = Path(__file__).parent.parent
    parquet_path = repo_root / "data" / "esci_products_sample_10000.parquet"
    output_path = (
        repo_root / "langchain_agent" / "lucille-esci" / "conf" / "color_mappings.json"
    )

    if not parquet_path.exists():
        raise FileNotFoundError(f"Parquet file not found: {parquet_path}")

    print(f"Analyzing colors from {parquet_path}")
    analysis = analyze_colors(str(parquet_path))

    # Write output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(analysis, f, indent=2)

    print(f"\nResults:")
    print(
        f"  Original unique colors: {analysis['statistics']['original_unique_colors']}"
    )
    print(f"  Classified products: {analysis['statistics']['classified_products']}")
    print(f"  Unclassified products: {analysis['statistics']['unclassified_products']}")
    print(
        f"  Products with secondary colors: {analysis['statistics']['products_with_secondary']}"
    )
    print(f"\nMappings written to: {output_path}")


if __name__ == "__main__":
    main()
