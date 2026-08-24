"""
Attribute normalization for colors and brands.

Provides deterministic, rules-based normalization for product attributes:
- Colors: normalize to 16 canonical forms with primary/secondary extraction
- Brands: normalize case and consolidate generic placeholders

Used at index time (Lucille) and query time (LangGraph filters).
"""

import json
import re
from pathlib import Path
from typing import Dict, Optional, Tuple


class AttributeNormalizer:
    """Normalize product colors and brands."""

    GENERIC_BRAND_PATTERNS = {
        "generic",
        "unknown",
        "unbranded",
        "brand not specified",
        "as shown",
        "various",
        "multiple",
        "not specified",
    }

    def __init__(self, color_mappings_path: Optional[str] = None):
        """
        Initialize normalizer.

        Args:
            color_mappings_path: path to color_mappings.json (auto-detected if None)
        """
        if color_mappings_path is None:
            # Auto-detect path relative to this file
            default_path = Path(__file__).parent / "lucille-esci" / "conf" / "color_mappings.json"
            color_mappings_path = str(default_path)

        with open(color_mappings_path) as f:
            mappings = json.load(f)

        self.base_colors: Dict[str, list] = mappings["base_colors"]

        # Build reverse lookup: variant -> canonical
        self.color_lookup: Dict[str, str] = {}
        for canonical, variants in self.base_colors.items():
            for variant in variants:
                self.color_lookup[variant.lower()] = canonical

    def normalize_color(self, color_str: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
        """
        Normalize color to (primary, secondary).

        Args:
            color_str: raw color string from product data

        Returns:
            (primary_canonical, secondary_canonical or None)
        """
        if not color_str or (
            isinstance(color_str, float) and color_str != color_str
        ):  # isnan check
            return None, None

        normalized = str(color_str).lower()

        # Strip leading single letter + space (e.g., "A Black")
        normalized = re.sub(r"^[a-z]\s+", "", normalized)

        # Strip trailing noise (numbers, symbols)
        normalized = re.sub(r"[\s#]*\d+\s*$", "", normalized)
        normalized = re.sub(r"[\s]*[.!?]\s*$", "", normalized)

        # Normalize special characters (split on &, /, +, ,)
        normalized = re.sub(r"\s*[&/+,]\s*", "|", normalized)

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
                if clean_word in self.color_lookup:
                    found_colors.append(self.color_lookup[clean_word])
                    break  # Use first found color per part

        # Deduplicate while preserving order
        found_colors = list(dict.fromkeys(found_colors))

        primary = found_colors[0] if found_colors else None
        secondary = found_colors[1] if len(found_colors) > 1 else None

        return primary, secondary

    def normalize_brand(self, brand_str: Optional[str]) -> str:
        """
        Normalize brand name.

        Args:
            brand_str: raw brand string from product data

        Returns:
            normalized brand (lowercase; "generic" if placeholder, otherwise original lowercased)
        """
        if not brand_str or (
            isinstance(brand_str, float) and brand_str != brand_str
        ):  # isnan check
            return "generic"

        normalized = str(brand_str).lower().strip()

        # Consolidate generic/placeholder brands
        if normalized in self.GENERIC_BRAND_PATTERNS:
            return "generic"

        return normalized
