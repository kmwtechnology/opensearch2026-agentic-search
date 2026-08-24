"""
Unit tests for GeminiReranker and CrossEncoderReranker — document scoring.

GeminiReranker: LLM (structured_llm) is fully mocked; no real API calls are made.
CrossEncoderReranker: CrossEncoder.predict() is fully mocked; no real model calls are made.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from reranker import CrossEncoderReranker, GeminiReranker, RerankerScore, RerankerScores

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(title: str, score: float = 0.0) -> Document:
    return Document(
        page_content=f"{title} content for testing",
        metadata={"title": title, "reranker_score": score},
    )


def _make_reranker() -> GeminiReranker:
    """Return a GeminiReranker with a mocked LLM (no real API calls)."""
    with patch("reranker.ChatGoogleGenerativeAI"):
        reranker = GeminiReranker(model_name="gemini-3.1-flash-lite-preview")
    return reranker


def _mock_scores(*pairs) -> RerankerScores:
    """Build a RerankerScores from (index, score) pairs."""
    return RerankerScores(scores=[RerankerScore(index=i, score=s) for i, s in pairs])


# ---------------------------------------------------------------------------
# Pydantic model validation
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRerankerScoreValidation:
    def test_valid_score_accepted(self):
        s = RerankerScore(index=0, score=0.85)
        assert s.score == 0.85

    def test_score_below_zero_rejected(self):
        with pytest.raises(ValidationError):
            RerankerScore(index=0, score=-0.1)

    def test_score_above_one_rejected(self):
        with pytest.raises(ValidationError):
            RerankerScore(index=0, score=1.01)

    def test_boundary_values_accepted(self):
        assert RerankerScore(index=0, score=0.0).score == 0.0
        assert RerankerScore(index=0, score=1.0).score == 1.0

    def test_negative_index_rejected(self):
        with pytest.raises(ValidationError):
            RerankerScore(index=-1, score=0.5)


@pytest.mark.unit
class TestRerankerScoresValidation:
    def test_empty_scores_rejected(self):
        with pytest.raises(ValidationError):
            RerankerScores(scores=[])

    def test_duplicate_indices_rejected(self):
        with pytest.raises(ValidationError):
            RerankerScores(
                scores=[
                    RerankerScore(index=0, score=0.8),
                    RerankerScore(index=0, score=0.5),
                ]
            )

    def test_valid_scores_accepted(self):
        rs = RerankerScores(
            scores=[RerankerScore(index=0, score=0.9), RerankerScore(index=1, score=0.4)]
        )
        assert len(rs.scores) == 2


# ---------------------------------------------------------------------------
# _build_prompt
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestBuildPrompt:
    def test_prompt_contains_query(self):
        reranker = _make_reranker()
        docs = [_doc("Sony WH-1000XM5")]
        prompt = reranker._build_prompt("wireless headphones", docs)
        assert "wireless headphones" in prompt

    def test_prompt_truncates_doc_to_500_chars(self):
        reranker = _make_reranker()
        long_content = "x" * 1000
        doc = Document(page_content=long_content, metadata={})
        prompt = reranker._build_prompt("query", [doc])
        # The excerpt in the prompt should be at most 500 chars of the content
        assert "x" * 501 not in prompt

    def test_prompt_numbers_documents(self):
        reranker = _make_reranker()
        docs = [_doc("Doc A"), _doc("Doc B")]
        prompt = reranker._build_prompt("q", docs)
        assert "[0]" in prompt
        assert "[1]" in prompt


# ---------------------------------------------------------------------------
# score_documents
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestScoreDocuments:
    def test_empty_documents_returns_empty_list(self):
        reranker = _make_reranker()
        assert reranker.score_documents("query", []) == []

    def test_returns_docs_sorted_descending_by_score(self):
        reranker = _make_reranker()
        docs = [_doc("low"), _doc("high"), _doc("mid")]
        reranker.structured_llm = MagicMock()
        reranker.structured_llm.invoke.return_value = _mock_scores((0, 0.3), (1, 0.9), (2, 0.6))
        result = reranker.score_documents("query", docs)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)
        assert scores[0] == pytest.approx(0.9)

    def test_missing_doc_scores_get_fallback_05(self):
        reranker = _make_reranker()
        docs = [_doc("A"), _doc("B"), _doc("C")]
        reranker.structured_llm = MagicMock()
        # LLM only returns scores for index 0 and 2, missing index 1
        reranker.structured_llm.invoke.return_value = _mock_scores((0, 0.8), (2, 0.6))
        result = reranker.score_documents("query", docs)
        score_map = {doc.page_content: score for doc, score in result}
        # Missing index 1 gets fallback of 0.5
        assert any(abs(s - 0.5) < 0.001 for s in score_map.values())

    def test_llm_error_raises_reranker_llm_error(self):
        from exceptions import RerankerLLMError

        reranker = _make_reranker()
        docs = [_doc("A")]
        reranker.structured_llm = MagicMock()
        reranker.structured_llm.invoke.side_effect = RuntimeError("API down")

        with pytest.raises(RerankerLLMError):
            reranker.score_documents("query", docs)

    def test_batching_splits_large_document_lists(self):
        reranker = _make_reranker()
        docs = [_doc(f"Doc {i}") for i in range(6)]
        reranker.batch_size = 3
        reranker.structured_llm = MagicMock()
        # Return valid scores for each batch of 3
        reranker.structured_llm.invoke.side_effect = [
            _mock_scores((0, 0.9), (1, 0.8), (2, 0.7)),
            _mock_scores((0, 0.6), (1, 0.5), (2, 0.4)),
        ]
        result = reranker.score_documents("query", docs)
        assert len(result) == 6
        # Should have called LLM twice (two batches of 3)
        assert reranker.structured_llm.invoke.call_count == 2


# ---------------------------------------------------------------------------
# rerank
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRerank:
    def test_rerank_returns_top_k(self):
        reranker = _make_reranker()
        docs = [_doc(f"Doc {i}") for i in range(5)]
        reranker.structured_llm = MagicMock()
        reranker.structured_llm.invoke.return_value = _mock_scores(
            (0, 0.9), (1, 0.7), (2, 0.5), (3, 0.3), (4, 0.1)
        )
        result = reranker.rerank("query", docs, top_k=3)
        assert len(result) == 3
        scores = [s for _, s in result]
        assert scores[0] >= scores[1] >= scores[2]

    def test_rerank_top_k_larger_than_docs_returns_all(self):
        reranker = _make_reranker()
        docs = [_doc("A"), _doc("B")]
        reranker.structured_llm = MagicMock()
        reranker.structured_llm.invoke.return_value = _mock_scores((0, 0.8), (1, 0.4))
        result = reranker.rerank("query", docs, top_k=10)
        assert len(result) == 2


# ---------------------------------------------------------------------------
# CrossEncoderReranker tests
# ---------------------------------------------------------------------------


def _make_cross_reranker() -> CrossEncoderReranker:
    """Return a CrossEncoderReranker with a mocked CrossEncoder model."""
    with patch("sentence_transformers.CrossEncoder"):
        reranker = CrossEncoderReranker(model_name="cross-encoder/ms-marco-MiniLM-L-12-v2")
    return reranker


@pytest.mark.unit
class TestCrossEncoderReranker:
    def test_empty_documents_returns_empty_list(self):
        reranker = _make_cross_reranker()
        assert reranker.score_documents("query", []) == []

    def test_returns_docs_sorted_descending_by_score(self):
        reranker = _make_cross_reranker()
        docs = [_doc("low"), _doc("high"), _doc("mid")]
        reranker.model = MagicMock()
        # Return raw logits from cross-encoder
        reranker.model.predict.return_value = np.array([-1.0, 2.0, 0.5])
        result = reranker.score_documents("query", docs)
        scores = [s for _, s in result]
        assert scores == sorted(scores, reverse=True)
        # Sigmoid of 2.0 ≈ 0.88 should be first
        assert scores[0] > scores[1] > scores[2]

    def test_sigmoid_normalization_maps_to_0_1(self):
        reranker = _make_cross_reranker()
        docs = [_doc("A"), _doc("B")]
        reranker.model = MagicMock()
        # Extreme logits: -10 and +10
        reranker.model.predict.return_value = np.array([-10.0, 10.0])
        result = reranker.score_documents("query", docs)
        # After sigmoid: sigmoid(-10) ≈ 0.0, sigmoid(10) ≈ 1.0
        _, score_low = result[1]  # Lower logit score
        _, score_high = result[0]  # Higher logit score
        assert 0.0 <= score_low <= 1.0
        assert 0.0 <= score_high <= 1.0
        assert score_high > score_low

    def test_truncates_document_content_to_500_chars(self):
        reranker = _make_cross_reranker()
        long_content = "x" * 1000
        doc = Document(page_content=long_content, metadata={})
        reranker.model = MagicMock()
        reranker.model.predict.return_value = np.array([0.5])
        reranker.score_documents("query", [doc])
        # Check that the model was called with truncated content (<=500 chars)
        call_args = reranker.model.predict.call_args
        pairs = call_args[0][0]
        assert len(pairs[0][1]) == 500

    def test_rerank_returns_top_k(self):
        reranker = _make_cross_reranker()
        docs = [_doc(f"Doc {i}") for i in range(5)]
        reranker.model = MagicMock()
        reranker.model.predict.return_value = np.array([2.0, 1.5, 0.0, -0.5, -1.0])
        result = reranker.rerank("query", docs, top_k=3)
        assert len(result) == 3
        scores = [s for _, s in result]
        assert scores[0] >= scores[1] >= scores[2]

    def test_rerank_top_k_larger_than_docs_returns_all(self):
        reranker = _make_cross_reranker()
        docs = [_doc("A"), _doc("B")]
        reranker.model = MagicMock()
        reranker.model.predict.return_value = np.array([0.8, -0.5])
        result = reranker.rerank("query", docs, top_k=10)
        assert len(result) == 2

    def test_warmup_calls_score_documents(self):
        reranker = _make_cross_reranker()
        reranker.model = MagicMock()
        reranker.model.predict.return_value = np.array([0.0])
        warmup_time = reranker.warmup()
        assert isinstance(warmup_time, float)
        assert warmup_time >= 0.0
        # Should have called predict() at least once (for warmup)
        assert reranker.model.predict.called

    def test_attributes_required_by_main_py(self):
        reranker = _make_cross_reranker()
        # reranker_node in main.py uses these attributes for logging
        assert hasattr(reranker, "batch_size")
        assert hasattr(reranker, "device")
        assert hasattr(reranker, "model_name")
        assert reranker.batch_size == 32
        assert reranker.device == "cpu"
        assert reranker.model_name == "cross-encoder/ms-marco-MiniLM-L-12-v2"
