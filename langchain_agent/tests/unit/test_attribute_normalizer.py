"""Unit tests for attribute normalization."""

import pytest

from attribute_normalizer import AttributeNormalizer


@pytest.fixture
def normalizer():
    """Load normalizer with generated mappings."""
    return AttributeNormalizer()


class TestColorNormalization:
    """Test color normalization rules."""

    def test_simple_black(self, normalizer):
        """Black variants normalize to black."""
        assert normalizer.normalize_color("Black") == ("black", None)
        assert normalizer.normalize_color("black") == ("black", None)
        assert normalizer.normalize_color("BLACK") == ("black", None)

    def test_case_folding_with_descriptors(self, normalizer):
        """Case folding + descriptor stripping."""
        assert normalizer.normalize_color("Light Grey") == ("gray", None)
        assert normalizer.normalize_color("Deep Black") == ("black", None)
        assert normalizer.normalize_color("Dark Blue") == ("blue", None)

    def test_leading_letter_noise(self, normalizer):
        """Strip leading single letter."""
        assert normalizer.normalize_color("A Black") == ("black", None)
        assert normalizer.normalize_color("B White") == ("white", None)

    def test_trailing_noise(self, normalizer):
        """Strip trailing numbers and punctuation."""
        assert normalizer.normalize_color("Grey#1") == ("gray", None)
        assert normalizer.normalize_color("Black1") == ("black", None)
        assert normalizer.normalize_color("White.") == ("white", None)

    def test_special_character_splitting(self, normalizer):
        """Split on & and extract both colors."""
        primary, secondary = normalizer.normalize_color("Black & Purple")
        assert primary == "black"
        assert secondary == "purple"

    def test_slash_splitting(self, normalizer):
        """Split on / and extract both colors."""
        primary, secondary = normalizer.normalize_color("Black/White")
        assert primary == "black"
        assert secondary == "white"

    def test_plus_splitting(self, normalizer):
        """Split on + and extract both colors."""
        primary, secondary = normalizer.normalize_color("Blue+Red")
        assert primary == "blue"
        assert secondary == "red"

    def test_synonym_expansion(self, normalizer):
        """Synonyms normalize to canonical."""
        assert normalizer.normalize_color("Grey") == ("gray", None)
        assert normalizer.normalize_color("Charcoal") == ("black", None)
        assert normalizer.normalize_color("Navy") == ("blue", None)
        assert normalizer.normalize_color("Burgundy") == ("red", None)
        assert normalizer.normalize_color("Taupe") == ("brown", None)

    def test_multicolor_variants(self, normalizer):
        """Multicolor variants consolidate."""
        assert normalizer.normalize_color("Multicolor") == ("multicolor", None)
        assert normalizer.normalize_color("Multicolored") == ("multicolor", None)
        assert normalizer.normalize_color("Multi-color") == ("multicolor", None)
        assert normalizer.normalize_color("Rainbow") == ("multicolor", None)

    def test_parenthetical_content_stripped(self, normalizer):
        """Remove content in parentheses."""
        primary, secondary = normalizer.normalize_color("Pitch Gray Light Heather (012)/Jet Gray")
        assert primary == "gray"
        assert secondary is not None

    def test_compound_with_description(self, normalizer):
        """Extract colors from compound entries with descriptions."""
        primary, secondary = normalizer.normalize_color("White, Red")
        assert primary == "white"
        assert secondary == "red"

    def test_unclassified(self, normalizer):
        """Unknown colors return None."""
        primary, secondary = normalizer.normalize_color("XyzColor")
        assert primary is None
        assert secondary is None

    def test_none_input(self, normalizer):
        """Handle None input gracefully."""
        assert normalizer.normalize_color(None) == (None, None)

    def test_empty_string(self, normalizer):
        """Handle empty string gracefully."""
        assert normalizer.normalize_color("") == (None, None)

    def test_natural_wood(self, normalizer):
        """Natural/wood colors normalize."""
        assert normalizer.normalize_color("Natural") == ("natural", None)
        assert normalizer.normalize_color("Wood") == ("natural", None)

    def test_mixed_assorted(self, normalizer):
        """Assorted/mixed items normalize."""
        assert normalizer.normalize_color("Assorted") == ("mixed", None)
        assert normalizer.normalize_color("Mixed") == ("mixed", None)


class TestBrandNormalization:
    """Test brand normalization rules."""

    def test_case_folding(self, normalizer):
        """Case folding on brands."""
        assert normalizer.normalize_brand("Nike") == "nike"
        assert normalizer.normalize_brand("NIKE") == "nike"
        assert normalizer.normalize_brand("ADIDAS") == "adidas"

    def test_generic_consolidation(self, normalizer):
        """Generic/placeholder brands consolidate."""
        assert normalizer.normalize_brand("Generic") == "generic"
        assert normalizer.normalize_brand("Unknown") == "generic"
        assert normalizer.normalize_brand("Unbranded") == "generic"
        assert normalizer.normalize_brand("As Shown") == "generic"
        assert normalizer.normalize_brand("Various") == "generic"

    def test_real_brands_preserved(self, normalizer):
        """Real brands remain (lowercased)."""
        assert normalizer.normalize_brand("Apple") == "apple"
        assert normalizer.normalize_brand("Sony") == "sony"
        assert normalizer.normalize_brand("Amazon Basics") == "amazon basics"

    def test_none_input(self, normalizer):
        """Handle None as generic."""
        assert normalizer.normalize_brand(None) == "generic"

    def test_whitespace_trimmed(self, normalizer):
        """Whitespace trimmed."""
        assert normalizer.normalize_brand("  Nike  ") == "nike"
