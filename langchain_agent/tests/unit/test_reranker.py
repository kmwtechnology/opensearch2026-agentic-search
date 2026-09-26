"""
Unit tests for CrossEncoderReranker — document scoring.

CrossEncoder.predict() is fully mocked; no real model calls are made.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from retrieval.reranker import CrossEncoderReranker

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _doc(title: str, score: float = 0.0) -> Document:
    return Document(
        page_content=f"{title} content for testing",
        metadata={"title": title, "reranker_score": score},
    )


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

    def test_rescale_ceiling_stays_below_quality_gate_thresholds(self):
        """A uniformly-irrelevant batch (all raw sigmoid scores < 0.15) gets
        linearly rescaled so citations aren't suppressed, but the rescale
        must not produce a score that reads as confident to quality_gate_node
        (thresholds range 0.45-0.55). Regression test for a live-confirmed
        bug where the old [0.1, 1.0] rescale range could turn a genuinely
        irrelevant top document into a false-confident 1.000, silently
        defeating the Quality Gate's low-confidence retry."""
        reranker = _make_cross_reranker()
        docs = [_doc("A"), _doc("B"), _doc("C")]
        reranker.model = MagicMock()
        # All raw logits heavily negative -> sigmoid scores well under 0.15,
        # triggering the rescale path.
        reranker.model.predict.return_value = np.array([-8.0, -6.0, -7.0])
        result = reranker.score_documents("query", docs)
        scores = [s for _, s in result]
        assert max(scores) < 0.45, (
            f"rescaled max score {max(scores)} would falsely pass every "
            "quality_gate_node intent threshold (lowest is 0.45)"
        )
        # Still above the citation-suppression floor so citations aren't
        # wrongly hidden for a merely miscalibrated (not irrelevant) batch.
        assert min(scores) >= 0.10

    def test_rescale_flat_fallback_stays_below_quality_gate_thresholds(self):
        """All-identical raw scores hit the flat-fallback branch of the
        rescale; that fallback must also stay below every quality-gate
        threshold (0.45-0.55), not the old flat 0.5."""
        reranker = _make_cross_reranker()
        docs = [_doc("A"), _doc("B")]
        reranker.model = MagicMock()
        reranker.model.predict.return_value = np.array([-8.0, -8.0])
        result = reranker.score_documents("query", docs)
        scores = [s for _, s in result]
        assert all(s < 0.45 for s in scores)

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
