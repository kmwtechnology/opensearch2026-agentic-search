"""Langfuse eval/annotation workflows — local development only (issue #56 Phase B).

Wires the app's existing ESCI ground-truth judgments (`agent_state.judgments`,
looked up via `VectorStore.lookup_judgments`) into Langfuse's own primitives:

- **Datasets** (`sync_dataset_item`) — each judged query becomes a Dataset item.
- **Experiments** (`scripts/run_langfuse_eval.py`, via `client.run_experiment()`) —
  a real Dataset Run against those items, visible under Datasets > Runs.
- **Live scoring** (`record_citation_eval`) — every traced live request with ground
  truth for its query gets `eval_citation_precision` scored opportunistically,
  independent of a deliberate experiment run.
- **Annotation Queues** (`queue_for_human_review`) — low-precision results get
  pushed for human review/correction, closing the loop the original #56 ask named
  ("Annotation Queues, code evaluators... linking to ESCI ground truth") but that
  the first Phase B pass (PR #58) had dropped.

Same gating and lazy-import discipline as `langfuse_integration.py` — no GCP
footprint, SDK only in requirements-dev.txt.
"""

import logging
import re
from typing import Any, Dict, List, Optional

from config import LANGFUSE_BASE_URL, LANGFUSE_ENABLED, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY
from integrations.langfuse_integration import record_metrics

logger = logging.getLogger(__name__)

DATASET_NAME = "esci-ground-truth"
ANNOTATION_QUEUE_NAME = "low-confidence-citations"
HUMAN_SCORE_CONFIG_NAME = "human_citation_verdict"
LOW_PRECISION_THRESHOLD = 0.5

# Citation labels look like "[1,3] Some Product Title" — the leading bracket
# holds the 1-based indices into retrieved_documents (see pipeline_nodes.py's
# citations_dict construction).
_CITATION_INDEX_RE = re.compile(r"^\[([\d,]+)\]")


def sync_dataset_item(query: str, judgments: Optional[Dict[str, float]]) -> None:
    """Idempotently upsert one ESCI query + its ground-truth judgments as a Langfuse
    dataset item, keyed by the lowercased query so re-runs upsert instead of duplicate.

    No-op when tracing is disabled or there's no ground truth for this query (a novel
    query with no ESCI match) -- nothing useful to add to the eval dataset in that case.
    """
    if not LANGFUSE_ENABLED or not query or not judgments:
        return
    try:
        from langfuse import Langfuse

        client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            base_url=LANGFUSE_BASE_URL,
        )
        client.create_dataset(name=DATASET_NAME)
        client.create_dataset_item(
            dataset_name=DATASET_NAME,
            id=query.strip().lower(),
            input={"query": query},
            expected_output={"judgments": judgments},
        )
    except ImportError:
        logger.warning("Langfuse SDK unavailable; skipping dataset sync")
    except Exception:
        logger.debug("Langfuse dataset sync failed for query=%r", query, exc_info=True)


def citation_precision(
    citations: List[Dict[str, str]],
    retrieved_documents: List[Any],
    judgments: Dict[str, float],
) -> Optional[float]:
    """Fraction of distinct cited products with a positive ESCI relevance judgment.

    Returns None when there's nothing to score: no citations were emitted, or none
    of the cited documents carry a product_id Langfuse ground truth recognizes.
    """
    cited_product_ids = set()
    for citation in citations:
        match = _CITATION_INDEX_RE.match(citation.get("label", ""))
        if not match:
            continue
        for idx_str in match.group(1).split(","):
            doc_idx = int(idx_str) - 1  # citations use 1-based indices
            if 0 <= doc_idx < len(retrieved_documents):
                product_id = retrieved_documents[doc_idx].metadata.get("product_id")
                if product_id:
                    cited_product_ids.add(product_id)

    if not cited_product_ids:
        return None

    relevant = sum(1 for pid in cited_product_ids if judgments.get(pid, 0.0) > 0.0)
    return relevant / len(cited_product_ids)


def record_citation_eval(
    trace_id: Optional[str],
    citations: List[Dict[str, str]],
    retrieved_documents: List[Any],
    judgments: Optional[Dict[str, float]],
) -> None:
    """Score citation precision against ESCI ground truth on `trace_id`, if available,
    and queue it for human review when precision is low.

    Safe to call unconditionally: no-op with no judgments for this query, no citations
    to score, or tracing disabled (record_metrics already handles that gate).
    """
    if not judgments or not citations:
        return
    precision = citation_precision(citations, retrieved_documents, judgments)
    if precision is None:
        return
    record_metrics(trace_id, eval_citation_precision=precision)
    if precision < LOW_PRECISION_THRESHOLD:
        queue_for_human_review(trace_id)


def _get_or_create_score_config(client: Any) -> Optional[str]:
    for cfg in client.api.score_configs.get(limit=100).data:
        if cfg.name == HUMAN_SCORE_CONFIG_NAME:
            return cfg.id

    from langfuse.api.commons.types.config_category import ConfigCategory
    from langfuse.api.commons.types.score_config_data_type import ScoreConfigDataType

    cfg = client.api.score_configs.create(
        name=HUMAN_SCORE_CONFIG_NAME,
        data_type=ScoreConfigDataType.CATEGORICAL,
        categories=[
            ConfigCategory(label="correct", value=1),
            ConfigCategory(label="incorrect", value=0),
            ConfigCategory(label="unsure", value=-1),
        ],
        description="Human review of low-confidence citation-precision results.",
    )
    return cfg.id


def _get_or_create_annotation_queue(client: Any) -> Optional[str]:
    for queue in client.api.annotation_queues.list_queues(limit=100).data:
        if queue.name == ANNOTATION_QUEUE_NAME:
            return queue.id

    score_config_id = _get_or_create_score_config(client)
    if score_config_id is None:
        return None
    queue = client.api.annotation_queues.create_queue(
        name=ANNOTATION_QUEUE_NAME,
        score_config_ids=[score_config_id],
        description="Traces where citation precision against ESCI ground truth was low.",
    )
    return queue.id


def queue_for_human_review(trace_id: Optional[str]) -> None:
    """Push `trace_id` onto the low-confidence-citations Annotation Queue for a
    human to review/correct in the Langfuse UI. Creates the queue and its backing
    score config on first use (idempotent -- looks up by name before creating).

    Safe to call unconditionally: no-op when tracing is disabled, trace_id is None,
    or anything about queue setup fails (e.g. Annotation Queues unavailable on this
    Langfuse deployment) -- annotation is a nice-to-have, never a hard requirement.
    """
    if not LANGFUSE_ENABLED or trace_id is None:
        return
    try:
        from langfuse import Langfuse
        from langfuse.api.annotation_queues.types.annotation_queue_object_type import (
            AnnotationQueueObjectType,
        )

        client = Langfuse(
            public_key=LANGFUSE_PUBLIC_KEY,
            secret_key=LANGFUSE_SECRET_KEY,
            base_url=LANGFUSE_BASE_URL,
        )
        queue_id = _get_or_create_annotation_queue(client)
        if queue_id is None:
            return
        client.api.annotation_queues.create_queue_item(
            queue_id,
            object_id=trace_id,
            object_type=AnnotationQueueObjectType.TRACE,
        )
    except ImportError:
        logger.warning("Langfuse SDK unavailable; skipping annotation queue push")
    except Exception:
        logger.debug(
            "Langfuse annotation queue push failed for trace_id=%r", trace_id, exc_info=True
        )
