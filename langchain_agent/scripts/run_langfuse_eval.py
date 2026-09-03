"""Run a batch of known ESCI queries through the pipeline for Langfuse eval (issue #56 Phase B).

Local dev only -- requires `make langfuse-up` (LANGFUSE_ENABLED=true) plus the usual
local Postgres/OpenSearch services. Each query already gets its ESCI ground truth
synced as a Langfuse dataset item and its citation precision scored automatically
by `agent_node` (see `integrations/langfuse_eval.py`); this script just drives a
representative sample of judged queries through the real pipeline so those scores
land in Langfuse, instead of requiring a human to type them one at a time in the CLI.

Usage:
    PYTHONPATH=. python scripts/run_langfuse_eval.py [--limit N] [--locale us]
"""

import argparse
import logging
import sys
import uuid

from opensearchpy import OpenSearch

from config import (
    LANGFUSE_ENABLED,
    OPENSEARCH_HOST,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_PORT,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_VERIFY_CERTS,
)
from integrations import get_callbacks, new_trace_id, shutdown_tracing
from main import EcommerceSearchAgent

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


def scroll_judged_queries(os_client: OpenSearch, locale: str, limit: int) -> list:
    """Sample distinct queries from the esci_judgments index.

    No explicit sort: the index's `id` field (this run's document id, not a mapped
    sortable field) isn't a reliable ordering key across ingests, and any consistent
    subset works fine for a sample -- unlike benchmark_esci.py's full-scroll use case,
    which does need deterministic pagination.
    """
    resp = os_client.search(
        index="esci_judgments",
        body={
            "query": {"term": {"locale": locale}},
            "size": limit,
            "_source": ["query"],
        },
    )
    seen = []
    for hit in resp["hits"]["hits"]:
        query = hit["_source"].get("query", "").strip()
        if query and query not in seen:
            seen.append(query)
    return seen


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=20, help="Number of queries to run")
    parser.add_argument("--locale", default="us")
    args = parser.parse_args()

    if not LANGFUSE_ENABLED:
        print("LANGFUSE_ENABLED is not set -- nothing would be recorded. Set it in .env first.")
        return 1

    os_client = OpenSearch(
        hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
        http_auth=(("admin", OPENSEARCH_PASSWORD) if OPENSEARCH_PASSWORD else None),
        use_ssl=OPENSEARCH_USE_SSL,
        verify_certs=OPENSEARCH_VERIFY_CERTS,
        timeout=30,
    )

    try:
        queries = scroll_judged_queries(os_client, args.locale, args.limit)
    except Exception as exc:
        print(f"Could not read esci_judgments index (is it ingested?): {exc}")
        return 1

    if not queries:
        print("No judged queries found -- has the ESCI dataset been ingested?")
        return 1

    print(f"Running {len(queries)} judged queries through the pipeline...")

    agent = EcommerceSearchAgent()
    try:
        # Not agent.verify_prerequisites(): it checks self.vector_store.client, which
        # is None until initialize_components() runs -- a pre-existing ordering issue
        # in cli.py's own run(), not something to route around here.
        agent.initialize_components()
        agent.create_agent_graph()

        for i, query in enumerate(queries, 1):
            agent.thread_id = f"langfuse-eval-{uuid.uuid4().hex[:8]}"
            trace_id = new_trace_id(seed=agent.thread_id)
            try:
                agent.app.invoke(
                    {
                        "messages": [{"role": "user", "content": query}],
                        "langfuse_trace_id": trace_id,
                    },
                    config={
                        "configurable": {"thread_id": agent.thread_id},
                        "callbacks": get_callbacks(trace_id),
                    },
                )
                print(f"  [{i}/{len(queries)}] {query!r} -> scored")
            except Exception as exc:
                print(f"  [{i}/{len(queries)}] {query!r} -> FAILED: {exc}")
    finally:
        agent.cleanup()
        shutdown_tracing()

    print("Done. View results in the Langfuse UI under the 'esci-ground-truth' dataset and Scores.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
