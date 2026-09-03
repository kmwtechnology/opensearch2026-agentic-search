"""Unit tests for the Langfuse Experiment runner's evaluator logic (issue #56 Phase B).

Only citation_precision_evaluator and _doc are pure/testable without a real
EcommerceSearchAgent -- make_task()/main() need live pipeline components and
are exercised manually (make langfuse-eval), same as configure_langfuse_playground.py's
main() is the only piece of that script covered by a unit test.
"""

import scripts.run_langfuse_eval as script


def test_doc_wraps_metadata_for_attribute_access():
    doc = script._doc({"metadata": {"product_id": "p1"}})
    assert doc.metadata == {"product_id": "p1"}


def test_doc_defaults_to_empty_metadata():
    doc = script._doc({})
    assert doc.metadata == {}


def _output(product_ids, cited_indices):
    return {
        "citations": [{"label": f"[{','.join(str(i) for i in cited_indices)}] Boots"}],
        "retrieved_documents": [{"metadata": {"product_id": pid}} for pid in product_ids],
    }


def test_citation_precision_evaluator_scores_real_precision():
    output = _output(["p1", "p2"], [1, 2])
    result = script.citation_precision_evaluator(
        input={"query": "boots"},
        output=output,
        expected_output={"judgments": {"p1": 4.0, "p2": 0.0}},
    )
    assert result["name"] == "eval_citation_precision"
    assert result["value"] == 0.5


def test_citation_precision_evaluator_none_without_judgments():
    output = _output(["p1"], [1])
    result = script.citation_precision_evaluator(
        input={"query": "boots"}, output=output, expected_output=None
    )
    assert result is None


def test_citation_precision_evaluator_none_without_citations():
    output = {"citations": [], "retrieved_documents": []}
    result = script.citation_precision_evaluator(
        input={"query": "boots"}, output=output, expected_output={"judgments": {"p1": 4.0}}
    )
    assert result is None
