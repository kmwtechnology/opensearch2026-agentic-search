"""Run a Langfuse Experiment against the esci-ground-truth dataset (issue #56 Phase B).

Local dev only -- requires `make langfuse-up` (LANGFUSE_ENABLED=true) plus the usual
local Postgres/OpenSearch services, and a non-empty `esci-ground-truth` dataset
(populated by integrations.langfuse_eval.sync_dataset_item -- run some queries through
the app first, or use `make langfuse-eval-sync`).

Uses Langfuse's own `Dataset.run_experiment()` SDK method (task + evaluators against
dataset items, auto-traced, auto-linked to a Dataset Run) rather than hand-rolled
score/trace plumbing -- this is Langfuse's documented, first-class way to run a
dataset-based eval, and it's what actually populates the Experiments UI
(http://localhost:3000/project/<project>/datasets/<id>/runs/<run_id>).

Usage:
    PYTHONPATH=. python scripts/run_langfuse_eval.py [--run-name NAME] [--limit N]
"""

import argparse
import logging
import sys
import uuid
from types import SimpleNamespace

from core.config import LANGFUSE_ENABLED
from integrations import get_callbacks, shutdown_tracing
from integrations.langfuse_eval import DATASET_NAME, citation_precision
from main import EcommerceSearchAgent

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def _doc(entry: dict) -> SimpleNamespace:
    """citation_precision() expects Document-like objects (attribute access on
    .metadata) -- run_experiment's task output is a plain, JSON-serializable dict,
    so wrap it back into the minimal shape citation_precision() needs."""
    return SimpleNamespace(metadata=entry.get("metadata", {}))


def make_task(agent: EcommerceSearchAgent):
    def task(*, item, **kwargs):
        agent.thread_id = f"langfuse-experiment-{uuid.uuid4().hex[:8]}"
        result = agent.app.invoke(
            {"messages": [{"role": "user", "content": item.input["query"]}]},
            config={
                "configurable": {"thread_id": agent.thread_id},
                # No explicit trace_id: run_experiment() sets up ambient OTel
                # context around each item's task call, and agent.app.invoke()
                # (unlike astream_events -- see Phase 2's ambient-context gotcha)
                # nests correctly under it. Confirmed via ClickHouse: LangGraph
                # lands as a proper child span of experiment-item-task.
                "callbacks": get_callbacks(),
            },
        )
        citations = result.get("citations") or []
        retrieved_documents = result.get("retrieved_documents") or []
        return {
            "citations": citations,
            "retrieved_documents": [
                {"metadata": {"product_id": d.metadata.get("product_id")}}
                for d in retrieved_documents
            ],
        }

    return task


def citation_precision_evaluator(*, input, output, expected_output=None, metadata=None, **kwargs):
    judgments = (expected_output or {}).get("judgments") or {}
    citations = output.get("citations") or []
    if not judgments or not citations:
        return None
    docs = [_doc(d) for d in output.get("retrieved_documents") or []]

    precision = citation_precision(citations, docs, judgments)
    if precision is None:
        return None

    cited_count = len({d.metadata.get("product_id") for d in docs if d.metadata.get("product_id")})
    return {
        "name": "eval_citation_precision",
        "value": precision,
        "comment": f"citation precision against ESCI ground truth ({cited_count} candidate documents)",
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-name", default=None, help="Exact Dataset Run name (default: auto)")
    parser.add_argument(
        "--limit", type=int, default=None, help="Only run the first N dataset items"
    )
    args = parser.parse_args(argv)

    if not LANGFUSE_ENABLED:
        print("LANGFUSE_ENABLED is not set -- nothing would be recorded. Set it in .env first.")
        return 1

    from langfuse import Langfuse

    from core.config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY, secret_key=LANGFUSE_SECRET_KEY, base_url=LANGFUSE_BASE_URL
    )
    dataset = client.get_dataset(DATASET_NAME)
    if not dataset.items:
        print(
            f"Dataset '{DATASET_NAME}' is empty -- run some queries through the app first "
            "(sync_dataset_item populates it automatically when ESCI ground truth exists)."
        )
        return 1

    items = dataset.items[: args.limit] if args.limit else dataset.items
    print(f"Running experiment against {len(items)} dataset items...")

    agent = EcommerceSearchAgent()
    try:
        agent.initialize_components()
        agent.create_agent_graph()

        # client.run_experiment() (not dataset.run_experiment(), which always uses
        # every item) accepts an explicit `data` list -- passing actual DatasetItem
        # objects still links the run to this dataset, same as the convenience method.
        result = client.run_experiment(
            name="citation-precision",
            run_name=args.run_name,
            description="Citation precision against ESCI ground truth via the real search pipeline.",
            data=items,
            task=make_task(agent),
            evaluators=[citation_precision_evaluator],
            max_concurrency=1,
        )
    finally:
        agent.cleanup()
        shutdown_tracing()

    print(f"Done. Dataset run: {result.dataset_run_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
