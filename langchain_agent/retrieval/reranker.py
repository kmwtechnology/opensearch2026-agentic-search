"""
Cross-encoder reranker: local (query, document) relevance scoring.

The only reranker since #148 removed the Gemini LLM-as-reranker option -- the
pipeline runs entirely on local models. See CrossEncoderReranker below.
"""

import logging
import time
from typing import List, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class CrossEncoderReranker:
    """
    Cross-encoder reranker using sentence-transformers for fast local document scoring.

    Replaces LLM-based reranking (~500ms per batch) with a specialized cross-encoder model.
    Cross-encoders are designed for pair-wise relevance scoring, unlike general-purpose LLMs.

    ## Why Cross-Encoders?

    Cross-encoders directly score (query, document) pairs, capturing interaction between
    query and document tokens. This is more accurate and faster than LLM reranking for
    classification tasks like relevance scoring.

    ## Scoring Approach

    Uses `sentence-transformers.CrossEncoder` to score (query, document) pairs:
    - Model: `cross-encoder/ms-marco-MiniLM-L-12-v2` (default; 12M params)
    - Raw output: logits (unbounded); normalized via sigmoid to [0.0, 1.0]
    - Batching: all documents scored in a single `predict()` call
    - Documents: content truncated to 500 chars

    ## Performance

    - Latency: measured directly from production logs (see #26) at ~1.9–2.0s for a
      RERANKER_FETCH_K=40-document batch on Cloud Run's CPU-only instance -- not the
      ~10ms/batch figure this docstring and several other docs previously claimed
      (that number doesn't match observed behavior at real batch size / real hardware;
      don't propagate it further without re-measuring).
    - Quality: Comparable or better than Gemini on ESCI benchmarks (cross-encoders are
      rank-trained on MS MARCO)
    - Memory: ~200MB model weights (baked into the Docker image at build time, not
      downloaded at runtime — see the HF_HOME/HF_HUB_OFFLINE comments in the Dockerfile)

    ## Parameters

    Args:
        model_name: Cross-encoder model from sentence-transformers Hub.
                    Default: "cross-encoder/ms-marco-MiniLM-L-12-v2"
                    Alternatives: "ms-marco-MiniLM-L-6-v2" (6M params, faster),
                                  "qnli-distilroberta-base" (lighter)

    ## Usage Example

        reranker = CrossEncoderReranker()
        reranker.warmup()

        documents = [Document(page_content="Sony headphones...", metadata={...}), ...]
        query = "best wireless headphones under 200 dollars"

        scored = reranker.score_documents(query, documents)
        for doc, score in scored:
            print(f"{score:.2f}: {doc.metadata['title']}")

    ## Extension Points

    **Switch to a different cross-encoder**: Update `model_name` in `config.py`.

    **Adjust device**: Change `self.device` to "cuda" for GPU acceleration (if available).
    """

    def __init__(self, model_name: str = "cross-encoder/ms-marco-MiniLM-L-12-v2"):
        from sentence_transformers import CrossEncoder

        self.model_name = model_name
        self.device = "cpu"
        self.batch_size = 32

        self.model = CrossEncoder(model_name, device=self.device)
        logger.info(f"CrossEncoderReranker loaded: model={model_name}, device={self.device}")

    def warmup(self) -> float:
        """Prime the model with a test scoring call."""
        start_time = time.time()

        dummy_query = "What is the purpose of this warmup function?"
        dummy_doc = Document(
            page_content="This is a warmup document with enough content to be realistic. " * 5,
            metadata={"source": "warmup"},
        )
        self.score_documents(dummy_query, [dummy_doc])

        elapsed = time.time() - start_time
        logger.info(f"CrossEncoderReranker warmup complete in {elapsed:.3f}s")
        return elapsed

    def score_documents(
        self, query: str, documents: List[Document], batch_size: int = None
    ) -> List[Tuple[Document, float]]:
        """
        Score documents by relevance to query using cross-encoder pairwise scoring.

        Args:
            query: The search query string
            documents: List of LangChain Document objects to score
            batch_size: Unused (kept for call-site compatibility).
                        All documents are scored in a single predict() call.

        Returns:
            List of (Document, score) tuples sorted by score descending.
            Scores are in range [0.0, 1.0] (normalized via sigmoid).

        Raises:
            RuntimeError: If model prediction fails
        """
        if not documents:
            return []

        import time as time_module

        start_time = time_module.time()

        pairs = [(query, doc.page_content[:500]) for doc in documents]
        prep_time = time_module.time() - start_time
        logger.info(f"CrossEncoder: prep took {prep_time*1000:.1f}ms")

        try:
            predict_start = time_module.time()
            raw_scores = self.model.predict(pairs)
            predict_time = time_module.time() - predict_start
            logger.info(
                f"CrossEncoder: predict() took {predict_time*1000:.1f}ms for {len(documents)} docs"
            )
        except Exception as e:
            logger.error(
                "cross_encoder_error: %s",
                type(e).__name__,
                extra={
                    "error_type": type(e).__name__,
                    "error": str(e),
                    "query_length": len(query),
                    "num_docs": len(documents),
                },
            )
            raise RuntimeError(f"Cross-encoder scoring failed: {type(e).__name__}") from e

        # Normalize raw logits to [0, 1] via sigmoid: 1 / (1 + e^(-x))
        import numpy as np

        raw_scores_array = np.array(raw_scores)

        # Apply sigmoid activation
        sigmoid_scores = 1.0 / (1.0 + np.exp(-raw_scores_array))

        # If all scores are very low (< 0.15), apply rescaling to ensure citations work
        # This handles cases where the raw logits are heavily negative.
        #
        # The rescale ceiling MUST stay below every quality_gate_node intent
        # threshold (0.45-0.55, see pipeline_nodes.py's `intent_thresholds`).
        # This range previously stretched all the way to 1.0, which meant a
        # query where every candidate is genuinely irrelevant (raw scores
        # uniformly near-zero) could still produce a rescaled max_score of
        # 1.0 — a false "high confidence" reading that silently defeated the
        # Quality Gate's retry logic. Confirmed live: the query "laptop
        # sleeve for a 17-inch computer running Linux with RGB lighting and
        # waterproof" (no such product exists in the catalog) rescaled an
        # unrelated gaming laptop to a perfect 1.000 and the Quality Gate
        # passed on the first try instead of retrying. Capping the ceiling
        # at 0.3 keeps citations from being suppressed (still >= the 0.10
        # MIN_CITATION_RELEVANCE floor) while guaranteeing a uniformly-bad
        # batch still reads as low confidence to the Quality Gate.
        RESCALE_CEILING = 0.3
        score_max = float(np.max(sigmoid_scores))
        if score_max < 0.15:
            logger.info(
                "cross_encoder: rescaling scores (max %.3f < 0.15); applying linear scaling",
                score_max,
                extra={"raw_min": float(np.min(raw_scores_array)), "raw_max": score_max},
            )
            # Linear rescale to [0.1, RESCALE_CEILING] to ensure citations work
            # without masquerading as a confident result.
            score_min = float(np.min(sigmoid_scores))
            if score_max > score_min:  # Avoid division by zero
                sigmoid_scores = 0.1 + (sigmoid_scores - score_min) / (score_max - score_min) * (
                    RESCALE_CEILING - 0.1
                )
            else:
                # All scores identical — flat fallback, still below every
                # quality-gate threshold.
                sigmoid_scores = np.full_like(sigmoid_scores, 0.2)

        scores = np.clip(sigmoid_scores, 0.0, 1.0).tolist()

        # Log score statistics for debugging
        raw_min, raw_max, raw_mean = (
            float(np.min(raw_scores_array)),
            float(np.max(raw_scores_array)),
            float(np.mean(raw_scores_array)),
        )
        scores_array = np.array(scores)
        norm_min, norm_max, norm_mean = (
            float(np.min(scores_array)),
            float(np.max(scores_array)),
            float(np.mean(scores_array)),
        )

        logger.debug(
            "cross_encoder_scores",
            extra={
                "num_docs": len(documents),
                "raw_logits": {"min": raw_min, "max": raw_max, "mean": raw_mean},
                "normalized": {"min": norm_min, "max": norm_max, "mean": norm_mean},
                "below_citation_threshold_0.10": int(sum(1 for s in scores if s < 0.10)),
            },
        )

        all_scored: List[Tuple[Document, float]] = []
        for doc, score in zip(documents, scores):
            all_scored.append((doc, float(score)))

        all_scored.sort(key=lambda x: x[1], reverse=True)
        return all_scored

    def rerank(
        self, query: str, documents: List[Document], top_k: int
    ) -> List[Tuple[Document, float]]:
        """
        Rerank documents and return top-k most relevant results.

        Args:
            query: The search query string
            documents: List of LangChain Document objects to rerank
            top_k: Maximum number of documents to return

        Returns:
            List of (Document, score) tuples for top-k results sorted by score descending.
        """
        scored_docs = self.score_documents(query, documents)
        return scored_docs[:top_k]
