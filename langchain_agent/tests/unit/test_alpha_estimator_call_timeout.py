"""Regression: the pipeline's hidden alpha_estimator_llm / structured
alpha-estimation calls must not block indefinitely.

Retriever._extract_attributes and Retriever._expand_vague_query both make
a synchronous self.alpha_estimator_llm.invoke(prompt) call with no timeout
of their own -- one was measured hanging ~18.7s vs. a normal <1s in a
reindex-adjacent trial, invisible to the user (no node event, no bound on
how long it can run). See issue #117/#120.

query_evaluator_node's structured_llm.invoke(evaluation_prompt) call had
the same shape of bug, plus a documentation trap: it looked protected by
an `except SearchTimeoutError` clause backed by QUERY_EVAL_TIMEOUT_MS, but
that constant was never wired to anything and SearchTimeoutError is only
ever raised by OpenSearch search calls, never an LLM invoke() -- the
except-clause was dead code. See issue #122.

These tests pin the fix: _invoke_with_timeout enforces
ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS (now the single shared budget for all
three call sites) and each falls back gracefully (empty filter list /
original query / collection-default alpha) rather than hanging.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from main import EcommerceSearchAgent


class _SlowLLM:
    """Stand-in for alpha_estimator_llm whose invoke() blocks past the
    configured timeout -- simulates the measured ~18.7s hang."""

    def __init__(self, delay_seconds: float) -> None:
        self.delay_seconds = delay_seconds

    def invoke(self, prompt: str):
        time.sleep(self.delay_seconds)
        raise AssertionError("invoke() should have been abandoned by the caller's timeout")


def _agent_with_slow_llm(delay_seconds: float) -> EcommerceSearchAgent:
    agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
    agent.alpha_estimator_llm = _SlowLLM(delay_seconds)
    return agent


@pytest.mark.unit
@pytest.mark.phase1
class TestAlphaEstimatorCallTimeout:
    def test_invoke_with_timeout_raises_on_hang(self) -> None:
        agent = _agent_with_slow_llm(delay_seconds=5)
        from concurrent.futures import TimeoutError as FutureTimeoutError

        start = time.monotonic()
        with pytest.raises(FutureTimeoutError):
            agent._invoke_with_timeout(agent.alpha_estimator_llm, "prompt", timeout_seconds=0.05)
        elapsed = time.monotonic() - start

        assert elapsed < 1.0, f"timeout should abandon the call quickly, took {elapsed:.2f}s"

    def test_invoke_with_timeout_returns_result_when_fast(self) -> None:
        agent = EcommerceSearchAgent.__new__(EcommerceSearchAgent)
        fast_llm = MagicMock()
        fast_llm.invoke.return_value = "ok"

        result = agent._invoke_with_timeout(fast_llm, "prompt", timeout_seconds=5)

        assert result == "ok"

    def test_extract_attributes_falls_back_to_no_filters_on_timeout(self) -> None:
        agent = _agent_with_slow_llm(delay_seconds=5)

        with patch("pipeline.pipeline_nodes.ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS", 0.05):
            start = time.monotonic()
            filters = agent._extract_attributes("show me tan boots")
            elapsed = time.monotonic() - start

        assert filters == []
        assert elapsed < 1.0, f"should not block for the full hang duration, took {elapsed:.2f}s"

    def test_expand_vague_query_falls_back_to_original_query_on_timeout(self) -> None:
        agent = _agent_with_slow_llm(delay_seconds=5)
        messages = [
            HumanMessage(content="show me headphones"),
            HumanMessage(content="those but blue"),
        ]

        with patch("pipeline.pipeline_nodes.ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS", 0.05):
            start = time.monotonic()
            expanded = agent._expand_vague_query("those but blue", messages)
            elapsed = time.monotonic() - start

        assert expanded == "those but blue"
        assert elapsed < 1.0, f"should not block for the full hang duration, took {elapsed:.2f}s"

    def test_query_evaluator_falls_back_to_default_alpha_on_timeout(self) -> None:
        agent = _agent_with_slow_llm(delay_seconds=5)
        agent.alpha_estimator_llm = None  # not used by this path
        agent.alpha_structured = _SlowLLM(delay_seconds=5)
        state = {
            "messages": [HumanMessage(content="best headphones for long flights")],
            "intent": "search",  # LLM path, not a fast-path intent
        }

        with patch("pipeline.pipeline_nodes.ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS", 0.05):
            start = time.monotonic()
            result = agent.query_evaluator_node(state)
            elapsed = time.monotonic() - start

        assert result["intent_description"] == "Unknown (timeout)"
        assert result["alpha"] == 0.65  # esci_products collection default
        assert elapsed < 1.0, f"should not block for the full hang duration, took {elapsed:.2f}s"
