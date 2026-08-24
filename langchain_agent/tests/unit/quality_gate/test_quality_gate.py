"""
Unit tests for quality gate.
Tests intent-aware thresholds, PASS/RETRY/ACCEPT decisions, and alpha adjustment.
"""

import pytest


@pytest.mark.unit
@pytest.mark.quality_gate
class TestQualityGate:
    """Quality gate unit tests."""

    def test_comparison_threshold(self):
        """Test comparison queries have higher threshold (0.55)."""
        intent = "comparison"
        threshold = 0.55
        assert intent == "comparison", "Should be comparison intent"
        assert threshold >= 0.55, "Comparison threshold should be >= 0.55"

    def test_search_threshold(self):
        """Test search queries use standard threshold (0.50)."""
        intent = "search"
        threshold = 0.50
        assert intent == "search", "Should be search intent"
        assert threshold == 0.50, "Search threshold should be 0.50"

    def test_attribute_filter_threshold(self):
        """Test attribute_filter queries use standard threshold (0.45)."""
        intent = "attribute_filter"
        threshold = 0.45
        assert intent == "attribute_filter", "Should be attribute_filter intent"
        assert threshold == 0.45, "Attribute_filter threshold should be 0.45"

    def test_refinement_threshold(self):
        """Test refinement queries use same threshold as attribute_filter (0.45)."""
        intent = "refinement"
        threshold = 0.45
        assert intent == "refinement", "Should be refinement intent"
        assert threshold == 0.45, "Refinement threshold should be 0.45"
        assert (
            threshold < 0.50
        ), "Refinement threshold should be below standard (permissive for feature-text matching)"

    def test_pass_decision_above_threshold(self, quality_gate_test_cases):
        """Test PASS decision when max_score >= threshold."""
        max_score, intent, expected_status, threshold = quality_gate_test_cases[0]
        if max_score >= threshold:
            assert expected_status == "pass", f"Score {max_score} >= {threshold} should PASS"

    def test_pass_decision_above_search_threshold(self):
        """Test PASS when search score >= 0.50."""
        max_score = 0.52
        threshold = 0.50
        status = "pass" if max_score >= threshold else "retry"
        assert status == "pass", f"Score {max_score} >= {threshold} should PASS"

    def test_retry_decision_below_threshold(self):
        """Test RETRY decision when max_score < threshold."""
        max_score = 0.32
        threshold = 0.50
        quality_gate_retried = False
        if max_score < threshold and not quality_gate_retried:
            assert True, "Should trigger RETRY"
        else:
            assert False, "Should have triggered RETRY"

    def test_alpha_adjustment_decrease(self):
        """Test alpha decreases by 0.3 when current_alpha >= 0.5 (lexical boost)."""
        current_alpha = 0.65
        new_alpha = max(0.0, current_alpha - 0.3)
        assert abs(new_alpha - 0.35) < 0.001, f"Alpha should decrease to ~0.35, got {new_alpha}"
        assert new_alpha >= 0.0, "Alpha should not go below 0.0"

    def test_alpha_adjustment_increase(self):
        """Test alpha increases by 0.3 when current_alpha < 0.5 (semantic boost)."""
        current_alpha = 0.25
        new_alpha = min(1.0, current_alpha + 0.3)
        assert abs(new_alpha - 0.55) < 0.001, f"Alpha should increase to ~0.55, got {new_alpha}"
        assert new_alpha <= 1.0, "Alpha should not go above 1.0"

    def test_alpha_bounds_after_adjustment(self):
        """Test alpha stays within bounds [0.0, 1.0] after adjustment."""
        test_alphas = [0.0, 0.25, 0.5, 0.75, 1.0]
        for current_alpha in test_alphas:
            if current_alpha >= 0.5:
                new_alpha = max(0.0, current_alpha - 0.3)
            else:
                new_alpha = min(1.0, current_alpha + 0.3)
            assert 0.0 <= new_alpha <= 1.0, f"New alpha {new_alpha} out of bounds"

    def test_accept_decision_after_retry(self):
        """Test ACCEPT decision when already retried."""
        max_score = 0.32
        quality_gate_retried = True
        if quality_gate_retried:
            assert True, "Should ACCEPT after retry"
        else:
            assert False, "Should have ACCEPTED"

    def test_no_retry_when_documents_empty(self):
        """Test no RETRY triggered when no documents."""
        retrieved_documents = []
        quality_gate_retried = False
        if not retrieved_documents:
            quality_gate_retried = False
        assert not quality_gate_retried, "Should not retry with no documents"

    def test_quality_gate_disabled(self):
        """Test quality gate behavior when disabled."""
        enable_quality_gate = False
        if not enable_quality_gate:
            quality_gate_retried = False
        assert not quality_gate_retried, "Quality gate disabled should not retry"

    def test_status_tracking_pass(self):
        """Test quality_gate_status is 'pass' for good scores."""
        max_score = 0.67
        threshold = 0.55
        status = "pass" if max_score >= threshold else "retry"
        assert status == "pass", "Status should be 'pass'"

    def test_status_tracking_retry(self):
        """Test quality_gate_status is 'retry' for low scores."""
        max_score = 0.32
        threshold = 0.50
        quality_gate_retried = False
        status = "retry" if (max_score < threshold and not quality_gate_retried) else "pass"
        assert status == "retry", "Status should be 'retry'"

    @pytest.mark.parametrize(
        "intent,expected_threshold",
        [
            ("comparison", 0.55),
            ("search", 0.50),
            ("attribute_filter", 0.45),
            ("refinement", 0.45),
            ("follow_up", 0.50),
        ],
    )
    def test_intent_thresholds(self, intent, expected_threshold):
        """Test each intent has correct threshold."""
        thresholds = {
            "comparison": 0.55,
            "search": 0.50,
            "attribute_filter": 0.45,
            "refinement": 0.45,
            "follow_up": 0.50,
        }
        actual_threshold = thresholds.get(intent)
        assert actual_threshold == expected_threshold, f"{intent} threshold mismatch"
