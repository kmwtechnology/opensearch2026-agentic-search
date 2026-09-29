"""Unit tests for confidence_proxy — pure functions, hand-computed expectations."""

import pytest

from observability.confidence_proxy import (
    ConfidenceProxy,
    confidence_from_scores,
    count_rank_changes,
)

# ---------------------------------------------------------------------------
# Confidence proxy
# ---------------------------------------------------------------------------


class TestConfidenceFromScores:
    def test_empty_scores_returns_low(self):
        proxy = confidence_from_scores([])
        assert proxy.confidence_label == "low"
        assert proxy.top1_score == 0.0
        assert proxy.score_gap == 0.0

    def test_high_confidence(self):
        # top1=0.95, gap=0.30 — clearly high
        proxy = confidence_from_scores([0.95, 0.65, 0.50, 0.30])
        assert proxy.confidence_label == "high"
        assert proxy.top1_score == pytest.approx(0.95)
        assert proxy.score_gap == pytest.approx(0.30)

    def test_low_confidence(self):
        # All low and clustered
        proxy = confidence_from_scores([0.3, 0.28, 0.27])
        assert proxy.confidence_label == "low"

    def test_medium_confidence(self):
        proxy = confidence_from_scores([0.7, 0.6, 0.5, 0.4])
        assert proxy.confidence_label == "medium"

    def test_returns_confidence_proxy_instance(self):
        proxy = confidence_from_scores([0.9])
        assert isinstance(proxy, ConfidenceProxy)

    def test_to_dict_round_trip(self):
        proxy = confidence_from_scores([0.9, 0.5], rank_changes_count=3)
        d = proxy.to_dict()
        assert d["rank_changes_count"] == 3
        assert d["top1_score"] == pytest.approx(0.9)
        assert d["confidence_label"] in {"high", "medium", "low"}

    def test_rank_changes_count_propagates(self):
        proxy = confidence_from_scores([0.5, 0.4], rank_changes_count=5)
        assert proxy.rank_changes_count == 5

    def test_variance_zero_for_single_score(self):
        proxy = confidence_from_scores([0.9])
        assert proxy.score_variance == 0.0


# ---------------------------------------------------------------------------
# count_rank_changes
# ---------------------------------------------------------------------------


class TestCountRankChanges:
    def test_no_changes(self):
        ids = ["a", "b", "c"]
        assert count_rank_changes(ids, ids, k=3) == 0

    def test_full_swap(self):
        # Reranker reversed every position
        pre = ["a", "b", "c"]
        post = ["c", "b", "a"]
        # 'a' moved 0->2 (change), 'b' stayed at 1 (no change), 'c' moved 2->0 (change)
        assert count_rank_changes(pre, post, k=3) == 2

    def test_top1_change_only(self):
        pre = ["a", "b", "c"]
        post = ["b", "a", "c"]
        # 'b' moved 1->0 (change), 'a' moved 0->1 (change), 'c' stayed
        assert count_rank_changes(pre, post, k=3) == 2

    def test_post_contains_new_id(self):
        # An item not in pre top-k that appears in post counts as a change
        pre = ["a", "b", "c"]
        post = ["a", "b", "z"]
        assert count_rank_changes(pre, post, k=3) == 1

    def test_empty(self):
        assert count_rank_changes([], ["a"], k=3) == 0
        assert count_rank_changes(["a"], [], k=3) == 0


# ---------------------------------------------------------------------------
# Latency cost-benefit
# ---------------------------------------------------------------------------
