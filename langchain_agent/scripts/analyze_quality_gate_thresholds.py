"""Analyze whether per-intent QUALITY_GATE_THRESHOLD values in pipeline_nodes.py's
quality_gate_node are well-calibrated against real eval outcomes (issue #56 Phase C).

Local dev only. Pulls `reranker_max_score` (the gate's own input), `intent`, and
`eval_citation_precision` (from Phase B's citation-precision evaluator) scores from
Langfuse, joins them by trace_id, and reports the correlation between the gate's
pass/fail signal and actual citation-precision outcome per intent.

This is a read-only analysis tool: it prints a recommendation, it does not touch
QUALITY_GATE_THRESHOLD or the intent_thresholds dict itself. Retuning production
thresholds from a handful of local dev traces would be tuning on noise -- do that
by hand, with real traffic volume, citing this script's output as evidence.

Usage:
    PYTHONPATH=. python scripts/analyze_quality_gate_thresholds.py [--limit N]
"""

import argparse
import sys
from collections import defaultdict
from statistics import mean, pstdev
from typing import Dict, Optional

from core.config import (
    LANGFUSE_BASE_URL,
    LANGFUSE_ENABLED,
    LANGFUSE_PUBLIC_KEY,
    LANGFUSE_SECRET_KEY,
)

# Mirrors pipeline_nodes.py's quality_gate_node intent_thresholds -- kept here only
# for display/comparison, not imported (that dict is a local, not a module constant).
CURRENT_THRESHOLDS = {
    "comparison": 0.55,
    "attribute_filter": 0.45,
    "refinement": 0.45,
    "search": 0.50,
    "follow_up": 0.50,
}


def _scores_by_trace(client, name: str, limit: int) -> Dict[str, float]:
    result: Dict[str, float] = {}
    response = client.api.scores.get_many(name=name, limit=limit)
    for item in response.data:
        if item.trace_id is not None and item.value is not None:
            result[item.trace_id] = item.value
    return result


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=200, help="Max scores to fetch per name")
    args = parser.parse_args(argv)

    if not LANGFUSE_ENABLED:
        print("LANGFUSE_ENABLED is not set -- nothing to analyze.")
        return 1

    try:
        from langfuse import Langfuse
    except ImportError:
        print("langfuse SDK not installed -- run `pip install -r requirements-dev.txt` first.")
        return 1

    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL
    )

    reranker_max_scores = _scores_by_trace(client, "reranker_max_score", args.limit)
    precisions = _scores_by_trace(client, "eval_citation_precision", args.limit)
    intents: Dict[str, Optional[str]] = {}
    intent_response = client.api.scores.get_many(name="intent", limit=args.limit)
    for item in intent_response.data:
        if item.trace_id is not None:
            intents[item.trace_id] = item.string_value or item.value

    joined = [
        (intents.get(trace_id, "unknown"), reranker_max_scores[trace_id], precision)
        for trace_id, precision in precisions.items()
        if trace_id in reranker_max_scores
    ]

    if not joined:
        print(
            "No traces have both reranker_max_score and eval_citation_precision yet. "
            "Run `make langfuse-eval` (or some real traffic) first."
        )
        return 0

    print(
        f"Joined {len(joined)} traces with both a reranker score and a citation-precision eval.\n"
    )

    by_intent: Dict[str, list] = defaultdict(list)
    for intent, max_score, precision in joined:
        by_intent[intent].append((max_score, precision))

    for intent, rows in sorted(by_intent.items()):
        threshold = CURRENT_THRESHOLDS.get(intent)
        max_scores = [r[0] for r in rows]
        precisions_list = [r[1] for r in rows]
        passed = [r for r in rows if threshold is not None and r[0] >= threshold]
        failed_would_gate = [r for r in rows if threshold is not None and r[0] < threshold]

        print(f"intent={intent} (n={len(rows)}, current_threshold={threshold})")
        print(f"  reranker_max_score: mean={mean(max_scores):.3f} stdev={pstdev(max_scores):.3f}")
        print(
            f"  eval_citation_precision: mean={mean(precisions_list):.3f} "
            f"stdev={pstdev(precisions_list):.3f}"
        )
        if passed:
            print(
                f"  passed-gate precision: mean={mean(r[1] for r in passed):.3f} (n={len(passed)})"
            )
        if failed_would_gate:
            print(
                f"  would-have-failed-gate precision: mean={mean(r[1] for r in failed_would_gate):.3f} "
                f"(n={len(failed_would_gate)})"
            )
        if passed and failed_would_gate:
            gap = mean(r[1] for r in passed) - mean(r[1] for r in failed_would_gate)
            if gap < 0.05:
                print(
                    "  -> threshold shows little separation in citation precision; "
                    "consider lowering it or investigating whether reranker_max_score "
                    "is a good proxy for this intent"
                )
            else:
                print("  -> threshold appears well-calibrated (clear precision gap)")
        print()

    print(
        "This is informational only -- no threshold was changed. Adjust "
        "intent_thresholds in pipeline_nodes.py's quality_gate_node by hand if the "
        "evidence above (with enough sample size) supports it."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
