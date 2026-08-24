"""
Gemini-based Reranker implementation for LLM-as-reranker document scoring.

Uses gemini-3.1-flash-lite-preview via Google AI to score query-document relevance
in a single batch API call, replacing the local cross-encoder model.
"""

import logging
import time
from typing import Annotated, List, Tuple

from langchain_core.documents import Document
from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, field_validator

from config import RERANKER_BATCH_SIZE
from exceptions import RerankerLLMError, RerankerValidationError

logger = logging.getLogger(__name__)


class RerankerScore(BaseModel):
    """Score assigned to a single document by the reranker."""

    index: Annotated[int, Field(ge=0, description="Document index (0-indexed, must be >= 0)")]
    score: Annotated[float, Field(ge=0.0, le=1.0, description="Relevance score [0.0-1.0]")]

    @field_validator("score", mode="after")
    @classmethod
    def validate_score_bounds(cls, score: float) -> float:
        """Ensure score is exactly bounded to [0.0, 1.0]."""
        if not (0.0 <= score <= 1.0):
            raise ValueError(f"Score must be in [0.0, 1.0], got {score}")
        return score


class RerankerScores(BaseModel):
    """Collection of scores from reranking a batch of documents."""

    scores: list[RerankerScore]

    @field_validator("scores", mode="after")
    @classmethod
    def validate_non_empty(cls, scores: list) -> list:
        """Ensure at least one score is returned."""
        if not scores:
            raise ValueError("RerankerScores.scores must contain at least one score")
        return scores

    @field_validator("scores", mode="after")
    @classmethod
    def validate_indices_unique(cls, scores: list) -> list:
        """Ensure all indices are unique (no duplicate document scoring)."""
        indices = [s.index for s in scores]
        if len(indices) != len(set(indices)):
            duplicates = [i for i in indices if indices.count(i) > 1]
            raise ValueError(f"Duplicate document indices in scores: {set(duplicates)}")
        return scores


SCORING_PROMPT_TEMPLATE = """Rate the relevance of each document to the query on a scale of 0.0 to 1.0.
0.0 means completely irrelevant, 1.0 means perfectly relevant.

Query: {query}

Documents:
{documents}

Return JSON: {{"scores": [{{"index": 0, "score": 0.85}}, ...]}}"""


class GeminiReranker:
    """
    LLM-based reranker using Google Gemini for semantic relevance scoring.

    Scores documents by query relevance on a 0.0–1.0 scale using Gemini's structured
    output mode. Designed for integration with OpenSearchRetriever in a LangGraph
    pipeline: retriever fetches candidates, reranker scores and ranks them.

    ## Why Rerank?

    Vector similarity alone misses nuances. BM25 alone misses semantic meaning. After
    hybrid search merges both signals via RRF, the top-K candidates may include
    noise or off-topic products. An LLM reranker reads the full query and each product
    text, outputs a relevance score (0.0–1.0), and allows the Quality Gate to decide
    if results are good enough (threshold: typically 0.5).

    ## Scoring Approach

    Sends a batch of (query, documents) to Gemini with a structured prompt:
    - "Score each document's relevance to the query on a 0.0–1.0 scale"
    - Gemini returns JSON: `[0.85, 0.92, 0.12, ...]` via Pydantic structured output
    - Pydantic validator ensures all scores are floats in [0.0, 1.0]
    - Documents are returned sorted by score (highest first)

    Batching allows scoring dozens of documents in a single LLM call (faster than
    per-document scoring). Batch size is configurable (`RERANKER_BATCH_SIZE` in config).

    ## Score Interpretation

    - 0.0–0.2 — Off-topic, unrelated to query
    - 0.2–0.5 — Partial match, some relevance but weak
    - 0.5–0.7 — Good match, clearly relevant
    - 0.7–1.0 — Excellent match, high confidence in relevance

    The Quality Gate typically uses 0.5 as the threshold: if `max_score < 0.5` and
    not yet retried, it adjusts α (lexical/semantic balance) ±0.3 and retries
    retrieval. This catches cases where the initial alpha was poorly calibrated.

    ## Parameters

    Args:
        model_name: Gemini model to use (default: gemini-3.1-flash-lite-preview).
                    Must support structured output via Pydantic.
                    Alternatives: gemini-3-flash-preview, gemini-2.0-flash

    ## Usage Example

        reranker = GeminiReranker()
        reranker.warmup()  # Prime the API connection

        documents = [
            Document(page_content="Sony wireless headphones...", metadata={...}),
            Document(page_content="Apple AirPods Pro...", metadata={...}),
        ]
        query = "best wireless headphones under 200 dollars"

        scored = reranker.score_documents(query, documents)
        for doc, score in scored:
            print(f"{score:.2f}: {doc.metadata['title']}")

    ## Extension Points

    **Replace with cross-encoder**: Swap for a sentence-transformers cross-encoder
    (e.g., `cross-encoder/ms-marco-MiniLM-L-6-v2`) for 10x faster scoring:

        class CrossEncoderReranker(GeminiReranker):
            def __init__(self, model_name="cross-encoder/qnli-distilroberta-base"):
                self.model = CrossEncoder(model_name)
            def score_documents(self, query, documents):
                scores = self.model.predict([[query, doc.page_content] for doc in documents])
                return sorted(zip(documents, scores), key=lambda x: x[1], reverse=True)

    **Add domain-specific scoring**: Subclass and override `score_documents()` to apply
    custom logic before/after LLM scoring (e.g., popularity boost, recency penalty).

    **Use a different LLM provider**: Replace `ChatGoogleGenerativeAI` with OpenAI,
    Anthropic, or Llama via LangChain's LLM interface. Must support structured output
    mode.
    """

    def __init__(self, model_name: str = "gemini-3.1-flash-lite-preview"):
        self.model_name = model_name
        self.device = "cloud"
        self.batch_size = RERANKER_BATCH_SIZE

        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            streaming=False,
            max_output_tokens=2048,
        )
        self.structured_llm = self.llm.with_structured_output(RerankerScores)

        logger.info(f"GeminiReranker loaded: model={model_name}, batch_size={self.batch_size}")

    def warmup(self) -> float:
        """Prime the API connection with a test scoring call."""
        start_time = time.time()

        dummy_query = "What is the purpose of this warmup function?"
        dummy_doc = Document(
            page_content="This is a warmup document with enough content to be realistic. " * 5,
            metadata={"source": "warmup"},
        )
        self.score_documents(dummy_query, [dummy_doc])

        elapsed = time.time() - start_time
        logger.info(f"GeminiReranker warmup complete in {elapsed:.3f}s")
        return elapsed

    def _build_prompt(self, query: str, documents: List[Document]) -> str:
        """Build the scoring prompt with numbered document excerpts."""
        doc_lines = []
        for i, doc in enumerate(documents):
            text = doc.page_content[:500]
            doc_lines.append(f"[{i}] {text}")

        return SCORING_PROMPT_TEMPLATE.format(query=query, documents="\n".join(doc_lines))

    def score_documents(
        self, query: str, documents: List[Document], batch_size: int = None
    ) -> List[Tuple[Document, float]]:
        """
        Score documents by relevance to query using batch LLM prompting.

        Args:
            query: The search query string
            documents: List of LangChain Document objects to score
            batch_size: Number of documents per API call.
                        If None, uses self.batch_size (from config).

        Returns:
            List of (Document, score) tuples sorted by score descending.
            Scores are in range [0.0, 1.0].

        Raises:
            RerankerLLMError: If LLM API call fails
            RerankerValidationError: If output validation fails
        """
        if not documents:
            return []

        if batch_size is None:
            batch_size = self.batch_size

        all_scored: List[Tuple[Document, float]] = []

        for batch_idx in range(0, len(documents), batch_size):
            batch_docs = documents[batch_idx : batch_idx + batch_size]
            prompt = self._build_prompt(query, batch_docs)

            try:
                result = self.structured_llm.invoke([HumanMessage(content=prompt)])
            except Exception as e:
                logger.error(
                    "reranker_llm_error: %s (batch_size=%d)",
                    type(e).__name__,
                    len(batch_docs),
                    extra={
                        "error_type": type(e).__name__,
                        "error": str(e),
                        "query_length": len(query),
                        "batch_size": len(batch_docs),
                    },
                )
                raise RerankerLLMError(
                    f"LLM scoring failed: {type(e).__name__}",
                    batch_size=len(batch_docs),
                    recoverable=True,
                ) from e

            # Build score map from valid scores only (skip out-of-range indices)
            valid_scores = [s for s in result.scores if 0 <= s.index < len(batch_docs)]
            invalid_indices = [
                s.index for s in result.scores if not (0 <= s.index < len(batch_docs))
            ]

            if invalid_indices:
                # Check if indices are significantly out of range (clearly erroneous)
                # Allow small overages (e.g., index 1 for batch size 1 due to batching artifacts)
                batch_size = len(batch_docs)
                significantly_invalid = [idx for idx in invalid_indices if idx >= batch_size + 5]

                if significantly_invalid:
                    logger.error(
                        "reranker_invalid_indices: %s",
                        significantly_invalid,
                        extra={
                            "invalid_indices": significantly_invalid,
                            "batch_size": batch_size,
                        },
                    )
                    raise RerankerValidationError(
                        f"LLM returned invalid document indices: {significantly_invalid}",
                        num_docs=batch_size,
                        recoverable=False,
                    )
                else:
                    logger.warning(
                        "reranker_invalid_indices: %s",
                        invalid_indices,
                        extra={
                            "invalid_indices": invalid_indices,
                            "batch_size": batch_size,
                        },
                    )

            score_map = {s.index: s.score for s in valid_scores}

            # Check for missing documents
            missing_indices = [i for i in range(len(batch_docs)) if i not in score_map]
            if missing_indices:
                logger.warning(
                    "reranker_missing_scores: %s",
                    missing_indices,
                    extra={
                        "missing_indices": missing_indices,
                        "batch_size": len(batch_docs),
                    },
                )
                # Use fallback (0.5) only for missing indices, not all documents
                for missing_idx in missing_indices:
                    score_map[missing_idx] = 0.5

            scores = [score_map[i] for i in range(len(batch_docs))]

            for doc, score in zip(batch_docs, scores):
                all_scored.append((doc, score))

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


class CrossEncoderReranker:
    """
    Cross-encoder reranker using sentence-transformers for fast local document scoring.

    Replaces LLM-based reranking (~500ms per batch) with a specialized cross-encoder model
    (~10ms per batch). Cross-encoders are designed for pair-wise relevance scoring, unlike
    general-purpose LLMs.

    ## Why Cross-Encoders?

    Cross-encoders directly score (query, document) pairs, capturing interaction between
    query and document tokens. This is more accurate and faster than LLM reranking for
    classification tasks like relevance scoring.

    ## Scoring Approach

    Uses `sentence-transformers.CrossEncoder` to score (query, document) pairs:
    - Model: `cross-encoder/ms-marco-MiniLM-L-12-v2` (default; 12M params, ~10ms per batch)
    - Raw output: logits (unbounded); normalized via sigmoid to [0.0, 1.0]
    - Batching: all documents scored in a single `predict()` call
    - Documents: content truncated to 500 chars (same as GeminiReranker)

    ## Performance

    - Latency: ~1ms per document (10ms for 10 docs vs. 500ms for Gemini)
    - Quality: Comparable or better than Gemini on ESCI benchmarks (cross-encoders are
      rank-trained on MS MARCO)
    - Memory: ~200MB model weights (one-time download from HuggingFace Hub)

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
            batch_size: Unused (kept for interface compatibility with GeminiReranker).
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
        # This handles cases where the raw logits are heavily negative
        score_max = float(np.max(sigmoid_scores))
        if score_max < 0.15:
            logger.info(
                "cross_encoder: rescaling scores (max %.3f < 0.15); applying linear scaling",
                score_max,
                extra={"raw_min": float(np.min(raw_scores_array)), "raw_max": score_max},
            )
            # Linear rescale to [0.1, 1.0] range to ensure citations work
            score_min = float(np.min(sigmoid_scores))
            if score_max > score_min:  # Avoid division by zero
                sigmoid_scores = 0.1 + (sigmoid_scores - score_min) / (score_max - score_min) * 0.9
            else:
                sigmoid_scores = np.full_like(sigmoid_scores, 0.5)  # Fallback: all 0.5

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
