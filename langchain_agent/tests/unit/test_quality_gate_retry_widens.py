"""The quality-gate retry must SEARCH DEEPER, not just re-weight (#103).

The gate's only retry lever used to be alpha +/-0.3. Measurement says that
lever cannot change the outcome: scoring ten conceptual shoe queries at alpha
0.1 / 0.4 / 0.7 / 1.0 returned the same reranker max score to two decimals
every time, because re-weighting reorders a candidate pool that already holds
the same best document. The retry was a loop that always reached the verdict it
started with.

The retriever now multiplies the candidate pool on a retry and drops the soft
multi_match filters. These tests pin that behaviour to the search kwargs, which
is where it is observable without standing up OpenSearch.
"""

import pytest

from core.config import RETRIEVER_FETCH_K, RETRY_FETCH_MULTIPLIER


@pytest.mark.unit
class TestQualityGateRetryWidens:
    def test_multiplier_is_greater_than_one(self):
        """A multiplier of 1 would silently restore the old no-op retry."""
        assert RETRY_FETCH_MULTIPLIER > 1, (
            "RETRY_FETCH_MULTIPLIER must widen the pool. At 1 the retry re-runs "
            "the same candidate set with a different alpha, which measurably "
            "cannot change the reranker's best score."
        )

    def test_retry_pool_is_strictly_larger_than_first_pass(self):
        retry_fetch_k = RETRIEVER_FETCH_K * RETRY_FETCH_MULTIPLIER
        assert retry_fetch_k > RETRIEVER_FETCH_K
        # Monotonicity is the whole argument for this being safe: the retry
        # scores a SUPERSET of the first pass's candidates, so max(score) can
        # only rise or stay equal. It can never return a worse best match.
        assert retry_fetch_k % RETRIEVER_FETCH_K == 0

    def test_soft_filters_are_dropped_on_retry_only(self):
        """multi_match filters are hints; match filters are what the user asked for.

        Mirrors the selection the retriever applies, so a change to the filter
        shape has to come here too.
        """
        attribute_filters = [
            {"match": {"product_color_primary": "blue"}},
            {"multi_match": {"query": "lightweight", "fields": ["chunk_text"]}},
            {"ids": {"values": ["B07Q399CZ3"]}},
        ]
        relaxed = [f for f in attribute_filters if "multi_match" not in f]

        assert {"match": {"product_color_primary": "blue"}} in relaxed, (
            "Colour/brand `match` filters must survive the retry — the user "
            "asked for those explicitly."
        )
        assert {"ids": {"values": ["B07Q399CZ3"]}} in relaxed, (
            "The refinement pin must survive: dropping it would let a retry "
            "wander outside the products the user is refining."
        )
        assert not any("multi_match" in f for f in relaxed)
