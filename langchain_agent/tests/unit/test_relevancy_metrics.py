"""Unit tests for relevancy_metrics — pure functions, hand-computed expectations."""

import pytest

from relevancy_metrics import (
    ConfidenceProxy,
    StageMetrics,
    compute_stage_metrics,
    confidence_from_scores,
    count_rank_changes,
    dcg,
    latency_cost_benefit,
    mrr,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
)

# ---------------------------------------------------------------------------
# DCG / NDCG
# ---------------------------------------------------------------------------


class TestDCG:
    def test_empty(self):
        assert dcg([]) == 0.0

    def test_single_relevant_at_position_1(self):
        # rel=4 at i=0 -> (2^4 - 1) / log2(2) = 15 / 1.0 = 15.0
        assert dcg([4.0]) == pytest.approx(15.0)

    def test_irrelevant_only_returns_zero(self):
        assert dcg([0.0, 0.0, 0.0]) == 0.0

    def test_ordering_matters(self):
        # Same items, different order — earlier high relevance scores higher
        good_first = dcg([4.0, 1.0, 0.0])
        good_last = dcg([0.0, 1.0, 4.0])
        assert good_first > good_last

    def test_k_truncation(self):
        # Only the first item counts at k=1
        full = dcg([4.0, 4.0, 4.0])
        first_only = dcg([4.0, 4.0, 4.0], k=1)
        assert first_only < full
        assert first_only == pytest.approx(15.0)


class TestNDCGAtK:
    def test_perfect_ranking_returns_1(self):
        # Ranking matches ideal order exactly
        relevances = [4.0, 1.0, 0.1]
        assert ndcg_at_k(relevances, relevances, k=10) == pytest.approx(1.0)

    def test_completely_inverted_is_below_perfect(self):
        # Reversed ranking: [0, 1, 4] vs ideal [4, 1, 0]
        # DCG_actual = 0 + 1/log2(3) + 15/log2(4) ≈ 8.131
        # DCG_ideal  = 15 + 1/log2(3) + 0           ≈ 15.631
        # NDCG ≈ 0.520 — below perfect but not pinned to a sub-0.5 threshold
        ranking = [0.0, 1.0, 4.0]
        ideal = [4.0, 1.0, 0.0]
        ndcg_inverted = ndcg_at_k(ranking, ideal, k=10)
        ndcg_perfect = ndcg_at_k(ideal, ideal, k=10)
        assert ndcg_inverted < ndcg_perfect
        assert ndcg_inverted == pytest.approx(0.520, abs=0.01)

    def test_no_relevant_items_returns_zero(self):
        assert ndcg_at_k([0.0, 0.0], [0.0, 0.0], k=10) == 0.0

    def test_empty_inputs(self):
        assert ndcg_at_k([], [4.0], k=10) == 0.0
        assert ndcg_at_k([4.0], [], k=10) == 0.0

    def test_k_caps_evaluation(self):
        # If the relevant item is past k, NDCG is 0
        ranking = [0.0, 0.0, 0.0, 4.0]
        ideal = [4.0]
        assert ndcg_at_k(ranking, ideal, k=3) == 0.0
        assert ndcg_at_k(ranking, ideal, k=4) > 0


# ---------------------------------------------------------------------------
# MRR
# ---------------------------------------------------------------------------


class TestMRR:
    def test_first_position(self):
        assert mrr([4.0, 0.0, 0.0]) == pytest.approx(1.0)

    def test_third_position(self):
        assert mrr([0.0, 0.0, 1.0]) == pytest.approx(1 / 3)

    def test_no_relevant_returns_zero(self):
        assert mrr([0.0, 0.0, 0.0]) == 0.0

    def test_threshold_excludes_substitute(self):
        # Threshold 4.0 means only Exact counts
        relevances = [1.0, 4.0, 0.0]  # Substitute at #1, Exact at #2
        assert mrr(relevances, relevance_threshold=1.0) == pytest.approx(1.0)
        assert mrr(relevances, relevance_threshold=4.0) == pytest.approx(0.5)

    def test_complement_below_threshold(self):
        # ESCI Complement (0.1) shouldn't count as relevant by default
        assert mrr([0.1, 0.1, 0.1], relevance_threshold=1.0) == 0.0


# ---------------------------------------------------------------------------
# Recall@k / Precision@k
# ---------------------------------------------------------------------------


class TestRecallAtK:
    def test_all_recovered(self):
        ranked = ["a", "b", "c", "d"]
        relevant = ["a", "b"]
        assert recall_at_k(ranked, relevant, k=4) == pytest.approx(1.0)

    def test_partial_recovery(self):
        ranked = ["a", "x", "y"]
        relevant = ["a", "b"]
        assert recall_at_k(ranked, relevant, k=3) == pytest.approx(0.5)

    def test_outside_k(self):
        ranked = ["x", "y", "a"]
        relevant = ["a"]
        assert recall_at_k(ranked, relevant, k=2) == 0.0
        assert recall_at_k(ranked, relevant, k=3) == pytest.approx(1.0)

    def test_no_relevant_returns_zero(self):
        assert recall_at_k(["a"], [], k=10) == 0.0


class TestPrecisionAtK:
    def test_all_relevant(self):
        ranked = ["a", "b", "c"]
        relevant = ["a", "b", "c"]
        assert precision_at_k(ranked, relevant, k=3) == pytest.approx(1.0)

    def test_no_relevant(self):
        assert precision_at_k(["a", "b"], ["x"], k=2) == 0.0

    def test_half_relevant(self):
        ranked = ["a", "x", "b", "y"]
        relevant = ["a", "b"]
        assert precision_at_k(ranked, relevant, k=4) == pytest.approx(0.5)

    def test_k_zero_returns_zero(self):
        assert precision_at_k(["a"], ["a"], k=0) == 0.0


# ---------------------------------------------------------------------------
# compute_stage_metrics — bundle integration
# ---------------------------------------------------------------------------


class TestComputeStageMetrics:
    def test_perfect_ranking(self):
        # Ranking matches judgments perfectly
        ranked = ["p1", "p2", "p3"]
        judgments = {"p1": 4.0, "p2": 1.0, "p3": 0.1, "p4": 4.0}
        metrics = compute_stage_metrics(ranked, judgments)
        assert metrics.precision10 == pytest.approx(2 / 3)  # 2 relevant in top-3
        assert metrics.mrr_score == pytest.approx(1.0)
        assert metrics.judged_count == 3

    def test_no_judgments_for_returned_items(self):
        ranked = ["unknown1", "unknown2"]
        judgments = {"p1": 4.0}
        metrics = compute_stage_metrics(ranked, judgments)
        assert metrics.ndcg10 == 0.0
        assert metrics.mrr_score == 0.0
        assert metrics.recall20 == 0.0
        assert metrics.precision10 == 0.0
        assert metrics.judged_count == 0

    def test_to_dict_rounds(self):
        ranked = ["p1"]
        judgments = {"p1": 4.0}
        metrics = compute_stage_metrics(ranked, judgments)
        d = metrics.to_dict()
        assert "ndcg10" in d
        assert "mrr" in d
        assert "recall20" in d
        assert "precision10" in d
        assert "judged_count" in d

    def test_returns_stage_metrics_instance(self):
        out = compute_stage_metrics(["p1"], {"p1": 4.0})
        assert isinstance(out, StageMetrics)


# ---------------------------------------------------------------------------
# Confidence proxy (Option A fallback)
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


class TestLatencyCostBenefit:
    @staticmethod
    def _stages(*triples):
        return [{"stage": n, "latency_ms": lat, "ndcg": ndcg} for n, lat, ndcg in triples]

    def test_no_ground_truth(self):
        rows = latency_cost_benefit(
            self._stages(("bm25", 20, None), ("hybrid", 50, None), ("reranked", 200, None))
        )
        assert len(rows) == 3
        assert rows[0]["stage"] == "bm25"
        assert rows[2]["stage"] == "reranked"
        for row in rows:
            assert row["ndcg_lift_per_100ms"] is None

    def test_ground_truth_lift_per_100ms(self):
        # BM25=20ms 0.6, Hybrid=50ms 0.7, Reranked=200ms 0.8
        rows = latency_cost_benefit(
            self._stages(("bm25", 20, 0.6), ("hybrid", 50, 0.7), ("reranked", 200, 0.8))
        )
        assert rows[0]["ndcg_lift_per_100ms"] is None
        assert rows[1]["ndcg_lift_per_100ms"] == pytest.approx(0.3333, abs=0.001)
        assert rows[2]["ndcg_lift_per_100ms"] == pytest.approx(0.0667, abs=0.001)

    def test_partial_ground_truth(self):
        # Only BM25 has ndcg → later rows have no comparison baseline
        rows = latency_cost_benefit(
            self._stages(("bm25", 20, 0.6), ("hybrid", 50, None), ("reranked", 200, None))
        )
        assert all(r["ndcg_lift_per_100ms"] is None for r in rows)

    def test_four_stages_with_stock_bm25(self):
        # Stock=15ms 0.4, your-BM25=25ms 0.5, Hybrid=60ms 0.65, Reranked=200ms 0.7
        rows = latency_cost_benefit(
            self._stages(
                ("stock_bm25", 15, 0.4),
                ("bm25", 25, 0.5),
                ("hybrid", 60, 0.65),
                ("reranked", 200, 0.7),
            )
        )
        assert len(rows) == 4
        assert rows[0]["ndcg_lift_per_100ms"] is None
        assert rows[1]["ndcg_lift_per_100ms"] == pytest.approx(1.0, abs=0.001)
        assert rows[2]["ndcg_lift_per_100ms"] == pytest.approx(0.4286, abs=0.001)
        assert rows[3]["ndcg_lift_per_100ms"] == pytest.approx(0.0357, abs=0.001)
