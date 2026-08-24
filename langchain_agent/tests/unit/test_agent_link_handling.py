"""Tests for agent URL/citation handling — issue #4.

The agent_node prompt forbids the LLM from emitting hyperlinks in body text
(it hallucinates ASINs and many ESCI ASINs are delisted on Amazon). These
tests cover the two guards behind that policy:

1. `_strip_inline_links` post-processes any LLM-emitted markdown/bare URLs out
   of the response text.
2. `_citation_url_for_doc` builds the user-facing citation URL — preferring
   explicit `metadata['url']`, falling back to an Amazon search URL keyed on
   the product title (robust against delisted ASINs).
"""

from urllib.parse import quote_plus

import pytest
from langchain_core.documents import Document

from main import EcommerceSearchAgent

# ---------------------------------------------------------------------------
# _strip_inline_links
# ---------------------------------------------------------------------------


class TestStripInlineLinks:
    def test_no_url_is_passthrough(self):
        text = "Just some plain text without links."
        assert EcommerceSearchAgent._strip_inline_links(text) == text

    def test_collapses_markdown_link_to_visible_text(self):
        text = "Try [Sony WH-1000XM5](https://www.amazon.com/dp/B09YLDRQ7L) for noise cancelling."
        out = EcommerceSearchAgent._strip_inline_links(text)
        assert out == "Try Sony WH-1000XM5 for noise cancelling."

    def test_collapses_markdown_link_with_bolded_url_from_issue_4(self):
        # Reproduces the exact pattern from issue #4 — LLM wrapped the URL
        # in `**...**` markers inside the parens.
        text = "[Hanes Men's Tee](**https://www.amazon.com/dp/B07V6S6X6W**) is cotton."
        out = EcommerceSearchAgent._strip_inline_links(text)
        assert "http" not in out
        assert "Hanes Men's Tee" in out

    def test_drops_bare_url(self):
        text = "Buy it at https://www.amazon.com/dp/B07V6S6X6W today."
        out = EcommerceSearchAgent._strip_inline_links(text)
        assert "http" not in out
        assert "Buy it at" in out
        assert "today." in out

    def test_collapses_multiple_links_in_paragraph(self):
        text = (
            "Options: [A](https://amazon.com/dp/A), [B](https://amazon.com/dp/B), "
            "and [C](https://amazon.com/dp/C)."
        )
        out = EcommerceSearchAgent._strip_inline_links(text)
        assert "http" not in out
        assert "A" in out and "B" in out and "C" in out

    def test_empty_string_passthrough(self):
        assert EcommerceSearchAgent._strip_inline_links("") == ""

    def test_repeated_hallucinated_asin_pattern_from_issue(self):
        # The bug in issue #4: same ASIN reused across many distinct products.
        # After stripping, none of the URLs should remain — only product names.
        text = (
            "[Shedd Shirts](https://www.amazon.com/dp/B07V6S6X6W) is the Natitude tee. "
            "[Hanes Value Pack](https://www.amazon.com/dp/B07V6S6X6W) offers basic navy. "
            "[UGP Dayton](https://www.amazon.com/dp/B07V6S6X6W) is collegiate."
        )
        out = EcommerceSearchAgent._strip_inline_links(text)
        assert "http" not in out
        assert "amazon" not in out.lower()
        assert "Shedd Shirts" in out
        assert "Hanes Value Pack" in out
        assert "UGP Dayton" in out


# ---------------------------------------------------------------------------
# _citation_url_for_doc
# ---------------------------------------------------------------------------


class TestCitationUrlForDoc:
    def test_explicit_url_wins(self):
        doc = Document(
            page_content="x",
            metadata={"url": "https://example.com/p", "title": "T", "product_id": "A1"},
        )
        assert EcommerceSearchAgent._citation_url_for_doc(doc) == "https://example.com/p"

    def test_falls_back_to_amazon_search_by_title(self):
        title = "Shedd Shirts Navy Washington NATITUDE T-Shirt Adult"
        doc = Document(
            page_content="x",
            metadata={"title": title, "product_id": "B07V6S6X6W"},
        )
        url = EcommerceSearchAgent._citation_url_for_doc(doc)
        assert url == f"https://www.amazon.com/s?k={quote_plus(title)}"
        # Critical: must not be the ASIN-based /dp/ URL — issue #4 fix.
        assert "/dp/" not in url

    def test_title_with_special_chars_is_url_encoded(self):
        title = "Men's 100% Cotton Tee (Navy) — XL & up"
        doc = Document(page_content="x", metadata={"title": title})
        url = EcommerceSearchAgent._citation_url_for_doc(doc)
        # Must be parseable / safe. Using quote_plus produces a valid query
        # string with spaces as `+`.
        assert url.startswith("https://www.amazon.com/s?k=")
        assert " " not in url

    def test_falls_back_to_product_id_when_no_title(self):
        doc = Document(page_content="x", metadata={"product_id": "B07V6S6X6W"})
        url = EcommerceSearchAgent._citation_url_for_doc(doc)
        assert url == "https://www.amazon.com/s?k=B07V6S6X6W"
        assert "/dp/" not in url

    def test_returns_none_with_no_useful_metadata(self):
        doc = Document(page_content="x", metadata={})
        assert EcommerceSearchAgent._citation_url_for_doc(doc) is None
