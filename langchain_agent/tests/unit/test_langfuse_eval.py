"""Unit tests for the Langfuse eval/annotation workflow (issue #56 Phase B).

Covers: dataset sync gating/idempotency, citation-precision scoring math, and the
record_citation_eval wiring into record_metrics. Follows the sys.modules injection
pattern from test_langfuse_integration.py -- CI never installs the real langfuse
package (requirements.txt only), so `patch("langfuse.X", ...)` would break there.
"""

import sys
from contextlib import ExitStack
from types import ModuleType
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
