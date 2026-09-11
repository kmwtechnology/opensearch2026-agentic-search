"""
Information-retrieval relevance metrics.

Pure functions implementing the four standard offline IR metrics used by
the Pipeline Quality Summary card:

  * NDCG@k    — graded relevance, position-discounted
  * MRR       — first-relevant rank, binary relevance
  * Recall@k  — coverage of all relevant items
  * Precision@k — fraction of returned items that are relevant

The metric helpers operate on ranked lists of product IDs joined against
a judgments dict ``{product_id: relevance_score}`` produced from the
ESCI dataset (see ``ingest_esci_judgments.py``). The companion
``confidence_from_scores`` helper produces a self-referential fallback
signal for queries that lack ground truth.

Design rules:
  * No I/O, no logging, no globals — these functions are unit-testable
    in isolation and safely callable inside a hot request path.
  * No NumPy dependency. Everything is plain Python so the module can
    run anywhere the agent runs (Cloud Run, local dev, tests).
  * Inputs are tolerated when imperfect: empty rankings return 0.0,
    missing judgments are treated as relevance 0.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence

# ---------------------------------------------------------------------------
# Core metric primitives
# ---------------------------------------------------------------------------


def dcg(relevances: Sequence[float], k: Optional[int] = None) -> float:
    """Discounted cumulative gain.

    Uses the standard formulation ``sum((2^rel - 1) / log2(i + 2))`` over
    the first ``k`` positions (i is zero-indexed). When ``k`` is None the
    full list is used.
    """
    if k is None:
        k = len(relevances)
    total = 0.0
    for i, rel in enumerate(relevances[:k]):
        if rel <= 0:
            continue
        total += (math.pow(2.0, rel) - 1.0) / math.log2(i + 2)
    return total


def ndcg_at_k(
    ranked_relevances: Sequence[float],
    ideal_relevances: Sequence[float],
    k: int = 10,
) -> float:
    """Normalized discounted cumulative gain at ``k``.

    ``ranked_relevances`` is the relevance grade of each retrieved item
    in retrieved-rank order; ``ideal_relevances`` is the same set sorted
    descending (typically: every judged-relevant item the corpus knows
    about). NDCG = DCG_actual / DCG_ideal.

    Returns 0.0 when the ideal DCG is zero (no relevant items judged).
    """
    if not ranked_relevances or not ideal_relevances:
        return 0.0
    actual = dcg(ranked_relevances, k=k)
    ideal = dcg(sorted(ideal_relevances, reverse=True), k=k)
    if ideal <= 0:
        return 0.0
    return actual / ideal


def mrr(ranked_relevances: Sequence[float], relevance_threshold: float = 1.0) -> float:
    """Mean Reciprocal Rank for a single query.

    Returns 1/rank of the first item meeting ``relevance_threshold``,
    or 0.0 if no item in the ranking does. The 1.0 default treats ESCI
    Substitute (S) and Exact (E) as relevant; pass ``4.0`` to require
    Exact only.
    """
    for i, rel in enumerate(ranked_relevances):
        if rel >= relevance_threshold:
            return 1.0 / (i + 1)
    return 0.0


def recall_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Sequence[str],
    k: int = 20,
) -> float:
    """Recall@k: fraction of all relevant items found in the top ``k``."""
    if not relevant_ids:
        return 0.0
    relevant_set = set(relevant_ids)
    top = set(ranked_ids[:k])
    return len(top & relevant_set) / len(relevant_set)


def precision_at_k(
    ranked_ids: Sequence[str],
    relevant_ids: Sequence[str],
    k: int = 10,
) -> float:
    """Precision@k: fraction of top-``k`` items that are relevant."""
    if k <= 0:
        return 0.0
    top = ranked_ids[:k]
    if not top:
        return 0.0
    relevant_set = set(relevant_ids)
    hits = sum(1 for pid in top if pid in relevant_set)
    return hits / min(k, len(top))


# ---------------------------------------------------------------------------
# High-level convenience: compute everything at once
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageMetrics:
    """Metric bundle for a single retrieval stage (BM25 / hybrid / reranked)."""

    ndcg10: float
    mrr_score: float
    recall20: float
    precision10: float
    judged_count: int  # how many items in the ranking had a judgment

    def to_dict(self) -> Dict[str, float]:
        return {
            "ndcg10": round(self.ndcg10, 4),
            "mrr": round(self.mrr_score, 4),
            "recall20": round(self.recall20, 4),
            "precision10": round(self.precision10, 4),
            "judged_count": self.judged_count,
        }


def compute_stage_metrics(
    ranked_product_ids: Sequence[str],
    judgments: Mapping[str, float],
    *,
    relevance_threshold: float = 1.0,
    k_ndcg: int = 10,
    k_recall: int = 20,
    k_precision: int = 10,
) -> StageMetrics:
    """Compute NDCG@10, MRR, Recall@20, Precision@10 for one ranking stage.

    Args:
        ranked_product_ids: Top retrieval result IDs in rank order.
        judgments: Mapping product_id -> relevance score. Items missing
            from this mapping are treated as relevance 0.
        relevance_threshold: Minimum relevance to count an item as a
            "hit" for MRR / Recall / Precision. ESCI Substitute (1.0)
            is the default; pass 4.0 for Exact-only.
        k_ndcg/k_recall/k_precision: Cutoffs for each metric.
    """
    relevances = [float(judgments.get(pid, 0.0)) for pid in ranked_product_ids]
    relevant_ids = [pid for pid, score in judgments.items() if score >= relevance_threshold]
    judged_count = sum(1 for pid in ranked_product_ids if pid in judgments)

    ndcg = ndcg_at_k(relevances, list(judgments.values()), k=k_ndcg)
    mrr_score = mrr(relevances, relevance_threshold=relevance_threshold)
    recall = recall_at_k(ranked_product_ids, relevant_ids, k=k_recall)
    precision = precision_at_k(ranked_product_ids, relevant_ids, k=k_precision)

    return StageMetrics(
        ndcg10=ndcg,
        mrr_score=mrr_score,
        recall20=recall,
        precision10=precision,
        judged_count=judged_count,
    )


# ---------------------------------------------------------------------------
# Self-referential fallback (Option A)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfidenceProxy:
    """Self-referential confidence signal when no ground truth exists."""

    top1_score: float
    score_gap: float  # top1 - top2
    score_variance: float  # variance of the top-k scores
    rank_changes_count: int  # # docs whose rank changed pre/post rerank
    confidence_label: str  # "high" / "medium" / "low"

    def to_dict(self) -> Dict[str, float]:
        return {
            "top1_score": round(self.top1_score, 4),
            "score_gap": round(self.score_gap, 4),
            "score_variance": round(self.score_variance, 6),
            "rank_changes_count": self.rank_changes_count,
            "confidence_label": self.confidence_label,
        }


def _variance(values: Sequence[float]) -> float:
    """Return population variance; 0.0 when fewer than two values."""
    if len(values) < 2:
        return 0.0
    mean = sum(values) / len(values)
    return sum((v - mean) ** 2 for v in values) / len(values)


def _label_from_signals(top1: float, gap: float, variance: float) -> str:
    """Heuristic: high if top1 is very confident AND well-separated.

    Calibrated for normalized reranker scores (0.0-1.0). Tightened so the
    label only goes "high" when the top result is genuinely strong, not
    just because the field is uniformly weak.
    """
    if top1 >= 0.85 and gap >= 0.15:
        return "high"
    if top1 >= 0.6 and (gap >= 0.08 or variance >= 0.02):
        return "medium"
    return "low"


def confidence_from_scores(
    scores: Sequence[float],
    *,
    rank_changes_count: int = 0,
) -> ConfidenceProxy:
    """Derive a confidence signal from reranker scores alone.

    Used when the query has no ESCI ground truth (the Option A fallback).
    The returned proxy is *not* an apples-to-apples NDCG replacement; the
    UI labels it as such and surfaces the underlying signals so the user
    can judge for themselves.
    """
    if not scores:
        return ConfidenceProxy(
            top1_score=0.0,
            score_gap=0.0,
            score_variance=0.0,
            rank_changes_count=rank_changes_count,
            confidence_label="low",
        )
    sorted_scores = sorted(scores, reverse=True)
    top1 = sorted_scores[0]
    top2 = sorted_scores[1] if len(sorted_scores) >= 2 else 0.0
    gap = top1 - top2
    variance = _variance(sorted_scores)
    label = _label_from_signals(top1, gap, variance)
    return ConfidenceProxy(
        top1_score=top1,
        score_gap=gap,
        score_variance=variance,
        rank_changes_count=rank_changes_count,
        confidence_label=label,
    )


def count_rank_changes(
    pre_rerank_ids: Sequence[str],
    post_rerank_ids: Sequence[str],
    k: int = 10,
) -> int:
    """Count items in top-k whose rank changed between pre and post rerank."""
    pre = list(pre_rerank_ids[:k])
    post = list(post_rerank_ids[:k])
    if not pre or not post:
        return 0
    pre_pos = {pid: i for i, pid in enumerate(pre)}
    changes = 0
    for i, pid in enumerate(post):
        if pre_pos.get(pid, -1) != i:
            changes += 1
    return changes


# ---------------------------------------------------------------------------
# Latency framing
# ---------------------------------------------------------------------------


def latency_cost_benefit(
    stages: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Compute lift-per-100ms over a sequence of pipeline stages.

    Args:
        stages: Ordered list of ``{"stage": str, "latency_ms": float,
            "ndcg": Optional[float]}`` dicts. Order matters — each stage's
            lift is computed against the previous stage with a known NDCG.

    Returns:
        A copy of ``stages`` with an ``ndcg_lift_per_100ms`` value added
        to each row (None when either the current or previous stage is
        missing ground-truth NDCG).

    The lift framing answers "is each stage worth its cost?" — at a
    glance we can see whether the slow stage is also the lift stage.
    """
    rows: List[Dict[str, Any]] = [dict(s) for s in stages]

    prev_ndcg: Optional[float] = None
    prev_latency: float = 0.0
    for row in rows:
        ndcg_now = row.get("ndcg")
        latency_now = row.get("latency_ms", 0.0)
        if ndcg_now is not None and prev_ndcg is not None:
            delta_ndcg = ndcg_now - prev_ndcg
            delta_latency = max(latency_now - prev_latency, 1e-6)
            row["ndcg_lift_per_100ms"] = round((delta_ndcg / delta_latency) * 100.0, 4)
        else:
            row["ndcg_lift_per_100ms"] = None
        if ndcg_now is not None:
            prev_ndcg = ndcg_now
            prev_latency = latency_now
    return rows
