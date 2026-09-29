"""
Retrieval-confidence proxy for the Pipeline Summary card.

Pure functions, no I/O: ``confidence_from_scores`` turns the reranker score
distribution into a high/medium/low label plus the signals behind it, and
``count_rank_changes`` measures how much the reranker reordered the top-k.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Sequence


@dataclass(frozen=True)
class ConfidenceProxy:
    """Self-referential confidence signal derived from reranker scores."""

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

    The proxy is not an offline-truth relevance metric; the UI labels it as
    such and surfaces the underlying signals so the user can judge for
    themselves.
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
