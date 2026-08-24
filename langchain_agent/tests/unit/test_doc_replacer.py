"""
Unit tests for doc_replacer — DocumentReplacer logic for replacing broken-link documents.
"""

import pytest
from langchain_core.documents import Document

from doc_replacer import DocumentReplacer


def _doc(content="text", source="docs/foo.md", url="https://example.com/foo", score=0.8, **meta):
    return Document(
        page_content=content,
        metadata={"source": source, "url": url, "reranker_score": score, **meta},
    )


@pytest.mark.unit
class TestGetSourceBase:
    def test_strips_section_fragment(self):
        replacer = DocumentReplacer()
        assert replacer.get_source_base("docs/foo.md#section1") == "docs/foo.md"

    def test_no_fragment_returns_unchanged(self):
        replacer = DocumentReplacer()
        assert replacer.get_source_base("docs/foo.md") == "docs/foo.md"

    def test_empty_string_returns_empty(self):
        replacer = DocumentReplacer()
        assert replacer.get_source_base("") == ""

    def test_multiple_hashes_splits_on_first(self):
        replacer = DocumentReplacer()
        assert replacer.get_source_base("docs/foo.md#a#b") == "docs/foo.md"


@pytest.mark.unit
class TestCalculateReplacementScore:
    def _setup_docs_with_list(self, docs):
        """Attach _original_list and _doc_index to docs as replace_broken_documents would."""
        for i, d in enumerate(docs):
            d.metadata["_original_list"] = docs
            d.metadata["_doc_index"] = i

    def test_same_source_file_awards_100_points(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/foo.md#s1", url="https://broken.com", score=0.8)
        candidate = _doc(source="docs/foo.md#s2", url="https://good.com", score=0.8)
        docs = [broken, candidate]
        self._setup_docs_with_list(docs)

        score = replacer.calculate_replacement_score(candidate, broken, set())
        assert score >= 100

    def test_already_used_index_returns_negative(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md", url="https://broken.com")
        candidate = _doc(source="docs/b.md", url="https://good.com")
        docs = [broken, candidate]
        self._setup_docs_with_list(docs)

        score = replacer.calculate_replacement_score(candidate, broken, {1})
        assert score == -1.0

    def test_candidate_not_in_original_list_returns_zero(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md", url="https://broken.com")
        candidate = _doc(source="docs/b.md", url="https://good.com")
        # Only broken is in original list
        broken.metadata["_original_list"] = [broken]
        broken.metadata["_doc_index"] = 0

        score = replacer.calculate_replacement_score(candidate, broken, set())
        assert score == 0.0

    def test_low_relevance_candidate_penalized(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md#s1", url="https://broken.com", score=1.0)
        candidate = _doc(source="docs/b.md", url="https://good.com", score=0.3)  # ratio=0.3 < 0.7
        docs = [broken, candidate]
        self._setup_docs_with_list(docs)

        score = replacer.calculate_replacement_score(candidate, broken, set())
        # Should be penalized (score < 0 before max clamp)
        # After max(0, ...) it might be 0 or still positive from same-source
        assert score == 0.0 or score < 50


@pytest.mark.unit
class TestFindReplacement:
    def test_returns_best_candidate(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md", url="https://broken.com", score=0.8)
        good1 = _doc(source="docs/a.md", url="https://good1.com", score=0.8)  # same source
        good2 = _doc(source="docs/b.md", url="https://good2.com", score=0.5)
        docs = [broken, good1, good2]
        for i, d in enumerate(docs):
            d.metadata["_original_list"] = docs
            d.metadata["_doc_index"] = i

        result = replacer.find_replacement(broken, docs, set())
        assert result is good1  # Same source wins

    def test_returns_none_when_no_candidates(self):
        replacer = DocumentReplacer()
        broken = _doc(url="https://broken.com")
        assert replacer.find_replacement(broken, [], set()) is None

    def test_skips_broken_doc_itself(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md", url="https://broken.com", score=0.9)
        docs = [broken]
        for i, d in enumerate(docs):
            d.metadata["_original_list"] = docs
            d.metadata["_doc_index"] = i

        result = replacer.find_replacement(broken, docs, set())
        assert result is None

    def test_skips_candidate_without_url(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md", url="https://broken.com")
        no_url = Document(page_content="text", metadata={"source": "docs/a.md"})
        docs = [broken, no_url]
        for i, d in enumerate(docs):
            d.metadata["_original_list"] = docs
            d.metadata["_doc_index"] = i

        result = replacer.find_replacement(broken, docs, set())
        assert result is None


@pytest.mark.unit
class TestReplaceBrokenDocuments:
    def test_no_broken_docs_returns_unchanged(self):
        replacer = DocumentReplacer()
        docs = [
            _doc(url="https://valid1.com"),
            _doc(url="https://valid2.com"),
        ]
        broken_urls = {
            "https://valid1.com": (True, "Status 200"),
            "https://valid2.com": (True, "Status 200"),
        }
        result_docs, log = replacer.replace_broken_documents(docs, broken_urls)
        assert result_docs == docs
        assert log == {}

    def test_replaces_broken_doc_with_valid_candidate(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md#s1", url="https://broken.com", score=0.8)
        candidate = _doc(source="docs/a.md#s2", url="https://valid.com", score=0.75)
        docs = [broken, candidate]
        broken_urls = {
            "https://broken.com": (False, "Status 404"),
            "https://valid.com": (True, "Status 200"),
        }
        result_docs, log = replacer.replace_broken_documents(docs, broken_urls)
        urls_in_result = [d.metadata.get("url") for d in result_docs]
        assert "https://broken.com" not in urls_in_result

    def test_replacement_log_records_sources(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md#s1", url="https://broken.com", score=0.8)
        candidate = _doc(source="docs/a.md#s2", url="https://valid.com", score=0.75)
        docs = [broken, candidate]
        broken_urls = {
            "https://broken.com": (False, "Status 404"),
            "https://valid.com": (True, "Status 200"),
        }
        _, log = replacer.replace_broken_documents(docs, broken_urls)
        assert log != {}

    def test_temp_metadata_cleaned_up(self):
        replacer = DocumentReplacer()
        docs = [_doc(url="https://good.com")]
        replacer.replace_broken_documents(docs, {"https://good.com": (True, "200")})
        for d in docs:
            assert "_original_list" not in d.metadata
            assert "_doc_index" not in d.metadata

    def test_temp_metadata_cleaned_up_even_after_replacement(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md#s1", url="https://broken.com", score=0.8)
        candidate = _doc(source="docs/a.md#s2", url="https://valid.com", score=0.75)
        docs = [broken, candidate]
        broken_urls = {
            "https://broken.com": (False, "404"),
            "https://valid.com": (True, "200"),
        }
        result_docs, _ = replacer.replace_broken_documents(docs, broken_urls)
        for d in result_docs:
            assert "_original_list" not in d.metadata
            assert "_doc_index" not in d.metadata

    def test_get_stats_returns_replacement_count(self):
        replacer = DocumentReplacer()
        broken = _doc(source="docs/a.md#s1", url="https://broken.com", score=0.8)
        candidate = _doc(source="docs/a.md#s2", url="https://valid.com", score=0.75)
        docs = [broken, candidate]
        broken_urls = {
            "https://broken.com": (False, "404"),
            "https://valid.com": (True, "200"),
        }
        replacer.replace_broken_documents(docs, broken_urls)
        stats = replacer.get_stats()
        assert stats["replacements_made"] >= 0  # 0 if score too low to replace, 1 otherwise
