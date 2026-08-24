"""Unit tests for ObservableAgentService._build_pipeline_summary."""

import warnings

warnings.filterwarnings("ignore")  # langchain pydantic v1 noise on 3.14

from langchain_core.documents import Document  # noqa: E402

from api.services.observable_agent import ObservableAgentService  # noqa: E402


def _doc(product_id: str, **metadata):
    metadata = {"product_id": product_id, **metadata}
    return Document(page_content="", metadata=metadata)


def _state(**overrides):
    base = {
        "user_query": "wireless headphones",
        "pre_rerank_documents": [],
        "post_rerank_documents": [],
        "bm25_documents": [],
        "stock_bm25_documents": [],
        "judgments": None,
        "bm25_latency_ms": 0.0,
        "stock_bm25_latency_ms": 0.0,
        "retriever_latency_ms": 0.0,
        "reranker_latency_ms": 0.0,
    }
    base.update(overrides)
    return base


class TestPipelineSummary:
    svc = ObservableAgentService()

    def test_returns_none_when_no_retrieval_happened(self):
        # No docs at all (e.g. summary intent) — nothing to summarize.
        assert self.svc._build_pipeline_summary(_state(), {}) is None

    def test_ground_truth_layout_populates_four_stages(self):
        pre = [_doc("A", reranker_score=0.9), _doc("B", reranker_score=0.7)]
        post = [_doc("B", reranker_score=0.95), _doc("A", reranker_score=0.6)]
        bm25 = [_doc("A"), _doc("C")]
        stock = [_doc("A")]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=post,
            bm25_documents=bm25,
            stock_bm25_documents=stock,
            judgments={"A": 4.0, "B": 1.0, "C": 0.1},
            bm25_latency_ms=25.0,
            stock_bm25_latency_ms=20.0,
            retriever_latency_ms=60.0,
            reranker_latency_ms=200.0,
        )
        event = self.svc._build_pipeline_summary(state, {"hybrid": True})
        assert event is not None
        assert event.has_ground_truth is True
        assert event.confidence is None
        assert event.stock_bm25 is not None and event.stock_bm25.judged_count == 1
        assert event.bm25 is not None and event.bm25.judged_count == 2
        assert event.hybrid is not None and event.hybrid.judged_count == 2
        assert event.reranked is not None
        # Four-row latency table; first row has no lift (no prior stage)
        stages = {row.stage: row for row in event.latency}
        assert {"stock_bm25", "bm25", "hybrid", "reranked"} == set(stages.keys())
        assert stages["stock_bm25"].ndcg_lift_per_100ms is None
        assert stages["bm25"].ndcg_lift_per_100ms is not None
        assert stages["hybrid"].ndcg_lift_per_100ms is not None
        assert stages["reranked"].ndcg_lift_per_100ms is not None

    def test_hybrid_off_hides_hybrid_row(self):
        # When optimizations.hybrid is False, the hybrid row would be a
        # duplicate of bm25 (the hybrid call routed to plain BM25 with the
        # user's toggles). Card hides it.
        bm25 = [_doc("A"), _doc("B")]
        stock = [_doc("A")]
        state = _state(
            pre_rerank_documents=bm25,  # hybrid:false ⇒ pre_rerank == bm25
            bm25_documents=bm25,
            stock_bm25_documents=stock,
            judgments={"A": 4.0, "B": 1.0},
            bm25_latency_ms=20.0,
            stock_bm25_latency_ms=18.0,
            retriever_latency_ms=22.0,
        )
        event = self.svc._build_pipeline_summary(state, {"hybrid": False})
        assert event is not None
        assert event.stock_bm25 is not None
        assert event.bm25 is not None
        assert event.hybrid is None  # hidden by toggle
        assert event.reranked is None  # no rerank latency
        stages = {row.stage for row in event.latency}
        assert "hybrid" not in stages

    def test_no_ground_truth_uses_confidence_proxy(self):
        pre = [_doc("A"), _doc("B")]
        post = [_doc("B", reranker_score=0.95), _doc("A", reranker_score=0.6)]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=post,
            bm25_documents=[_doc("X")],
            judgments=None,
            bm25_latency_ms=20.0,
            retriever_latency_ms=50.0,
            reranker_latency_ms=180.0,
        )
        event = self.svc._build_pipeline_summary(state, {"hybrid": True})
        assert event is not None
        assert event.has_ground_truth is False
        assert event.bm25 is None and event.hybrid is None and event.reranked is None
        assert event.confidence is not None
        assert event.confidence.confidence_label in {"high", "medium", "low"}
        assert event.confidence.rank_changes_count == 2
        # Latency rows still present, but no ndcg/lift
        for row in event.latency:
            assert row.ndcg is None
            assert row.ndcg_lift_per_100ms is None

    def test_reranker_skipped_omits_reranked_stage(self):
        # No post-rerank docs → reranked stage not populated even with GT
        pre = [_doc("A"), _doc("B")]
        bm25 = [_doc("A"), _doc("C")]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=pre,  # rerank toggle off → unchanged
            bm25_documents=bm25,
            judgments={"A": 4.0, "B": 1.0},
            bm25_latency_ms=20.0,
            retriever_latency_ms=50.0,
            reranker_latency_ms=0.0,
        )
        event = self.svc._build_pipeline_summary(state, {"reranking": False})
        assert event is not None
        assert event.bm25 is not None
        assert event.hybrid is not None
        assert event.reranked is None  # latency==0 → don't claim a reranked stage

    def test_generation_judgment_populates_card(self):
        # When llm_judge produced a judgment dict in state, the card should
        # surface it as a GenerationJudgment Pydantic model.
        bm25 = [_doc("A"), _doc("B")]
        state = _state(
            pre_rerank_documents=bm25,
            post_rerank_documents=bm25,
            bm25_documents=bm25,
            stock_bm25_documents=[_doc("A")],
            judgments={"A": 4.0, "B": 1.0},
            judgment={
                "verdict": "llm_better",
                "pairwise_justification": "LLM clearly explains the tradeoffs.",
                "faithfulness": 0.95,
                "answer_relevance": 0.90,
                "citation_accuracy": 1.0,
                "context_utilization": 0.7,
                "hallucinations": [
                    {
                        "claim": "designed to aid plaque removal",
                        "category": "inference",
                        "reasoning": "Source says 'chewy texture cleans teeth'.",
                    }
                ],
            },
            bm25_latency_ms=20.0,
            stock_bm25_latency_ms=18.0,
            retriever_latency_ms=50.0,
            reranker_latency_ms=180.0,
        )
        event = self.svc._build_pipeline_summary(state, {"hybrid": True, "llm_judge": True})
        assert event is not None
        assert event.generation is not None
        assert event.generation.verdict == "llm_better"
        assert event.generation.faithfulness == 0.95
        assert len(event.generation.hallucinations) == 1
        flagged = event.generation.hallucinations[0]
        assert flagged.category == "inference"
        assert flagged.claim == "designed to aid plaque removal"

    def test_no_judgment_means_no_generation_row(self):
        bm25 = [_doc("A")]
        state = _state(
            pre_rerank_documents=bm25,
            post_rerank_documents=bm25,
            bm25_documents=bm25,
            stock_bm25_documents=bm25,
            judgments={"A": 4.0},
            judgment=None,  # llm_judge toggled off → no judgment in state
            bm25_latency_ms=20.0,
            stock_bm25_latency_ms=18.0,
            retriever_latency_ms=50.0,
        )
        event = self.svc._build_pipeline_summary(state, {"hybrid": True})
        assert event is not None
        assert event.generation is None

    def test_falls_back_to_retrieval_score_when_no_reranker_score(self):
        # If reranker is toggled off, post_rerank == pre_rerank with retrieval_score
        pre = [
            _doc("A", retrieval_score=0.85),
            _doc("B", retrieval_score=0.4),
        ]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=pre,
            bm25_documents=[_doc("X")],
            judgments=None,
        )
        event = self.svc._build_pipeline_summary(state, {})
        assert event is not None
        assert event.confidence is not None
        # top1 should reflect the retrieval_score (0.85), not 0.0
        assert event.confidence.top1_score == 0.85
