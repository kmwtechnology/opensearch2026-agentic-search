"""
Unit tests for EcommerceSearchAgent._build_grounded_context's raw-vs-indexed
color fact lines, added so the agent can react to a mismatch between a
product's own listed color and the taxonomy bucket it's indexed under
(e.g. "Tan" indexed as "yellow") directly in its response, without relying
on the observability panel's DSL viewer.
"""

from langchain_core.documents import Document

from main import EcommerceSearchAgent


def _doc(**metadata) -> Document:
    return Document(page_content="Some description.", metadata=metadata)


class TestBuildGroundedContextColorFacts:
    def test_includes_both_raw_and_indexed_color_when_both_present(self):
        doc = _doc(title="Test Boot", product_color="Tan", product_color_primary="yellow")

        context = EcommerceSearchAgent._build_grounded_context([doc])

        assert "Color (as listed): Tan" in context
        assert "Color category (indexed): yellow" in context

    def test_omits_indexed_line_when_field_absent(self):
        doc = _doc(title="Test Boot", product_color="Tan")

        context = EcommerceSearchAgent._build_grounded_context([doc])

        assert "Color (as listed): Tan" in context
        assert "Color category (indexed)" not in context

    def test_omits_both_lines_when_no_color_data(self):
        doc = _doc(title="Wireless Mouse")

        context = EcommerceSearchAgent._build_grounded_context([doc])

        assert "Color (as listed)" not in context
        assert "Color category (indexed)" not in context

    def test_indexed_line_present_even_when_categories_agree(self):
        """Shown unconditionally, not only when wrong -- a selectively-shown
        field would itself tip off that something's off before the LLM
        says anything."""
        doc = _doc(title="Test Sneaker", product_color="Black", product_color_primary="black")

        context = EcommerceSearchAgent._build_grounded_context([doc])

        assert "Color (as listed): Black" in context
        assert "Color category (indexed): black" in context
