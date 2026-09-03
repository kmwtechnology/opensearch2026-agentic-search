"""Unit tests for the Langfuse eval/annotation workflow (issue #56 Phase B).

Covers: dataset sync gating/idempotency, citation-precision scoring math, and the
record_citation_eval wiring into record_metrics. Follows the sys.modules injection
pattern from test_langfuse_integration.py -- CI never installs the real langfuse
package (requirements.txt only), so `patch("langfuse.X", ...)` would break there.
"""

import sys
from contextlib import ExitStack
from types import ModuleType
from types import SimpleNamespace
from types import SimpleNamespace as NS
from unittest.mock import MagicMock, patch

import integrations.langfuse_eval as lfe


def _fake_sdk(client_cls=None):
    root = ModuleType("langfuse")
    root.Langfuse = client_cls or MagicMock(name="Langfuse")
    return {"langfuse": root}


def _enabled(*, modules):
    stack = ExitStack()
    stack.enter_context(patch.object(lfe, "LANGFUSE_ENABLED", True))
    stack.enter_context(patch.object(lfe, "LANGFUSE_PUBLIC_KEY", "pk_test"))
    stack.enter_context(patch.object(lfe, "LANGFUSE_SECRET_KEY", "sk_test"))
    stack.enter_context(patch.object(lfe, "LANGFUSE_BASE_URL", "http://localhost:3000"))
    stack.enter_context(patch.dict(sys.modules, modules))
    return stack


def _doc(product_id):
    return NS(metadata={"product_id": product_id})


# --- sync_dataset_item ---


def test_sync_dataset_item_noop_when_disabled():
    with patch.object(lfe, "LANGFUSE_ENABLED", False):
        lfe.sync_dataset_item("boots", {"p1": 4.0})  # must not raise, no import


def test_sync_dataset_item_noop_without_judgments():
    client_cls = MagicMock(name="Langfuse")
    with _enabled(modules=_fake_sdk(client_cls)):
        lfe.sync_dataset_item("boots", None)
        lfe.sync_dataset_item("boots", {})
    client_cls.assert_not_called()


def test_sync_dataset_item_upserts_by_lowercased_query():
    client_instance = MagicMock(name="client")
    client_cls = MagicMock(name="Langfuse", return_value=client_instance)
    with _enabled(modules=_fake_sdk(client_cls)):
        lfe.sync_dataset_item("Leather Boots", {"p1": 4.0, "p2": 0.0})

    client_instance.create_dataset.assert_called_once_with(name="esci-ground-truth")
    client_instance.create_dataset_item.assert_called_once_with(
        dataset_name="esci-ground-truth",
        id="leather boots",
        input={"query": "Leather Boots"},
        expected_output={"judgments": {"p1": 4.0, "p2": 0.0}},
    )


def test_sync_dataset_item_swallows_errors():
    broken = MagicMock(name="Langfuse", side_effect=RuntimeError("connection error"))
    with _enabled(modules=_fake_sdk(broken)):
        lfe.sync_dataset_item("boots", {"p1": 4.0})  # must not raise


def test_sync_dataset_item_swallows_missing_sdk():
    with _enabled(modules={"langfuse": None}):
        lfe.sync_dataset_item("boots", {"p1": 4.0})  # must not raise


# --- citation_precision ---


def test_citation_precision_none_without_cited_product_ids():
    assert lfe.citation_precision([], [], {"p1": 4.0}) is None
    assert lfe.citation_precision([{"label": "no bracket"}], [], {"p1": 4.0}) is None


def test_citation_precision_all_relevant():
    citations = [{"label": "[1] Boots"}]
    docs = [_doc("p1")]
    assert lfe.citation_precision(citations, docs, {"p1": 4.0}) == 1.0


def test_citation_precision_mixed_relevance():
    citations = [{"label": "[1,2] Boots"}]
    docs = [_doc("p1"), _doc("p2")]
    # p1 relevant (E=4.0), p2 irrelevant (I=0.0) -> 1 of 2 cited products relevant
    assert lfe.citation_precision(citations, docs, {"p1": 4.0, "p2": 0.0}) == 0.5


def test_citation_precision_unjudged_product_counts_as_irrelevant():
    citations = [{"label": "[1] Boots"}]
    docs = [_doc("p_unjudged")]
    assert lfe.citation_precision(citations, docs, {"p1": 4.0}) == 0.0


def test_citation_precision_ignores_out_of_range_index():
    citations = [{"label": "[1,5] Boots"}]
    docs = [_doc("p1")]
    assert lfe.citation_precision(citations, docs, {"p1": 4.0}) == 1.0


# --- record_citation_eval ---


def test_record_citation_eval_noop_without_judgments():
    with patch.object(lfe, "record_metrics") as record_metrics:
        lfe.record_citation_eval("trace1", [{"label": "[1] Boots"}], [_doc("p1")], None)
    record_metrics.assert_not_called()


def test_record_citation_eval_noop_without_citations():
    with patch.object(lfe, "record_metrics") as record_metrics:
        lfe.record_citation_eval("trace1", [], [_doc("p1")], {"p1": 4.0})
    record_metrics.assert_not_called()


def test_record_citation_eval_records_precision_score():
    with patch("integrations.langfuse_eval.record_metrics") as record_metrics:
        lfe.record_citation_eval("trace1", [{"label": "[1] Boots"}], [_doc("p1")], {"p1": 4.0})
    record_metrics.assert_called_once_with("trace1", eval_citation_precision=1.0)


def test_record_citation_eval_queues_low_precision_for_review():
    with (
        patch.object(lfe, "record_metrics"),
        patch.object(lfe, "queue_for_human_review") as queue_for_review,
    ):
        citations = [{"label": "[1,2] Boots"}]
        docs = [_doc("p1"), _doc("p_unjudged")]  # 1 of 2 relevant -> precision 0.5, not < 0.5
        lfe.record_citation_eval("trace1", citations, docs, {"p1": 4.0})
    queue_for_review.assert_not_called()

    with (
        patch.object(lfe, "record_metrics"),
        patch.object(lfe, "queue_for_human_review") as queue_for_review,
    ):
        citations = [{"label": "[1]"}]
        docs = [_doc("p_unjudged")]  # precision 0.0, < 0.5
        lfe.record_citation_eval("trace1", citations, docs, {"p1": 4.0})
    queue_for_review.assert_called_once_with("trace1")


# --- annotation queue ---


def _fake_annotation_sdk(*, score_configs=None, queues=None):
    root = ModuleType("langfuse")
    api_mod = ModuleType("langfuse.api")

    aq_mod = ModuleType("langfuse.api.annotation_queues")
    aq_types_mod = ModuleType("langfuse.api.annotation_queues.types")
    aq_object_type_mod = ModuleType(
        "langfuse.api.annotation_queues.types.annotation_queue_object_type"
    )
    aq_object_type_mod.AnnotationQueueObjectType = SimpleNamespace(TRACE="TRACE")

    commons_mod = ModuleType("langfuse.api.commons")
    commons_types_mod = ModuleType("langfuse.api.commons.types")
    config_category_mod = ModuleType("langfuse.api.commons.types.config_category")
    config_category_mod.ConfigCategory = lambda label, value: NS(label=label, value=value)
    score_config_type_mod = ModuleType("langfuse.api.commons.types.score_config_data_type")
    score_config_type_mod.ScoreConfigDataType = SimpleNamespace(CATEGORICAL="CATEGORICAL")

    modules = {
        "langfuse": root,
        "langfuse.api": api_mod,
        "langfuse.api.annotation_queues": aq_mod,
        "langfuse.api.annotation_queues.types": aq_types_mod,
        "langfuse.api.annotation_queues.types.annotation_queue_object_type": aq_object_type_mod,
        "langfuse.api.commons": commons_mod,
        "langfuse.api.commons.types": commons_types_mod,
        "langfuse.api.commons.types.config_category": config_category_mod,
        "langfuse.api.commons.types.score_config_data_type": score_config_type_mod,
    }

    client_instance = MagicMock(name="client")
    client_instance.api.score_configs.get.return_value = NS(data=score_configs or [])
    client_instance.api.score_configs.create.return_value = NS(id="new-config-id")
    client_instance.api.annotation_queues.list_queues.return_value = NS(data=queues or [])
    client_instance.api.annotation_queues.create_queue.return_value = NS(id="new-queue-id")
    root.Langfuse = MagicMock(name="Langfuse", return_value=client_instance)
    return modules, client_instance


def test_queue_for_human_review_noop_when_disabled():
    with patch.object(lfe, "LANGFUSE_ENABLED", False):
        lfe.queue_for_human_review("trace1")  # must not raise, no import


def test_queue_for_human_review_noop_without_trace_id():
    modules, client_instance = _fake_annotation_sdk()
    with _enabled(modules=modules):
        lfe.queue_for_human_review(None)
    client_instance.api.annotation_queues.create_queue_item.assert_not_called()


def test_queue_for_human_review_creates_queue_and_config_on_first_use():
    modules, client_instance = _fake_annotation_sdk()
    with _enabled(modules=modules):
        lfe.queue_for_human_review("trace1")

    client_instance.api.score_configs.create.assert_called_once()
    client_instance.api.annotation_queues.create_queue.assert_called_once_with(
        name="low-confidence-citations",
        score_config_ids=["new-config-id"],
        description="Traces where citation precision against ESCI ground truth was low.",
    )
    client_instance.api.annotation_queues.create_queue_item.assert_called_once_with(
        "new-queue-id", object_id="trace1", object_type="TRACE"
    )


def test_queue_for_human_review_reuses_existing_queue():
    modules, client_instance = _fake_annotation_sdk(
        score_configs=[NS(id="cfg1", name="human_citation_verdict")],
        queues=[NS(id="queue1", name="low-confidence-citations")],
    )
    with _enabled(modules=modules):
        lfe.queue_for_human_review("trace1")

    client_instance.api.score_configs.create.assert_not_called()
    client_instance.api.annotation_queues.create_queue.assert_not_called()
    client_instance.api.annotation_queues.create_queue_item.assert_called_once_with(
        "queue1", object_id="trace1", object_type="TRACE"
    )


def test_queue_for_human_review_swallows_errors():
    modules, client_instance = _fake_annotation_sdk()
    client_instance.api.annotation_queues.list_queues.side_effect = RuntimeError("boom")
    with _enabled(modules=modules):
        lfe.queue_for_human_review("trace1")  # must not raise
