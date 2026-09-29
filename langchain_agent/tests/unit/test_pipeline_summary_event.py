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
        "retriever_latency_ms": 0.0,
        "reranker_latency_ms": 0.0,
    }
    base.update(overrides)
    return base


class TestPipelineSummary:
    svc = ObservableAgentService()

    def test_returns_none_when_no_retrieval_happened(self):
        # No docs at all (e.g. summary intent) — nothing to summarize.
        assert self.svc._build_pipeline_summary(_state()) is None

    def test_confidence_proxy_and_latency_rows(self):
        pre = [_doc("A"), _doc("B")]
        post = [_doc("B", reranker_score=0.95), _doc("A", reranker_score=0.6)]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=post,
            retriever_latency_ms=50.0,
            reranker_latency_ms=180.0,
        )
        event = self.svc._build_pipeline_summary(state)
        assert event is not None
        assert event.confidence.confidence_label in {"high", "medium", "low"}
        assert event.confidence.top1_score == 0.95
        assert event.confidence.rank_changes_count == 2
        assert [(row.stage, row.latency_ms) for row in event.latency] == [
            ("hybrid", 50.0),
            ("reranked", 180.0),
        ]

    def test_reranker_skipped_omits_reranked_row(self):
        pre = [_doc("A"), _doc("B")]
        state = _state(
            pre_rerank_documents=pre,
            post_rerank_documents=pre,
            retriever_latency_ms=50.0,
            reranker_latency_ms=0.0,
        )
        event = self.svc._build_pipeline_summary(state)
        assert event is not None
        assert [row.stage for row in event.latency] == ["hybrid"]

    def test_falls_back_to_retrieval_score_when_no_reranker_score(self):
        pre = [_doc("A", retrieval_score=0.85), _doc("B", retrieval_score=0.4)]
        state = _state(pre_rerank_documents=pre, post_rerank_documents=pre)
        event = self.svc._build_pipeline_summary(state)
        assert event is not None
        # top1 should reflect the retrieval_score (0.85), not 0.0
        assert event.confidence.top1_score == 0.85

    def test_generation_judgment_populates_card(self):
        # When llm_judge produced a judgment dict in state, the card should
        # surface it as a GenerationJudgment Pydantic model.
        docs = [_doc("A"), _doc("B")]
        state = _state(
            pre_rerank_documents=docs,
            post_rerank_documents=docs,
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
            retriever_latency_ms=50.0,
            reranker_latency_ms=180.0,
        )
        event = self.svc._build_pipeline_summary(state)
        assert event is not None
        assert event.generation is not None
        assert event.generation.verdict == "llm_better"
        assert event.generation.faithfulness == 0.95
        assert len(event.generation.hallucinations) == 1
        flagged = event.generation.hallucinations[0]
        assert flagged.category == "inference"
        assert flagged.claim == "designed to aid plaque removal"

    def test_no_judgment_means_no_generation_row(self):
        docs = [_doc("A")]
        state = _state(
            pre_rerank_documents=docs,
            post_rerank_documents=docs,
            judgment=None,
            retriever_latency_ms=50.0,
        )
        event = self.svc._build_pipeline_summary(state)
        assert event is not None
        assert event.generation is None
