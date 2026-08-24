#!/usr/bin/env python3
"""
ESCI Relevancy Benchmark for Agentic Hybrid Search.

Measures NDCG@10, MRR, and Recall@20 on three retrieval configurations:
  1. Lexical floor (α=0.0, BM25 only)
  2. Standard hybrid (α=0.25, fixed)
  3. Adaptive (intent-driven α + cross-encoder reranker + quality gate)

Focuses on hard queries (bottom-quartile by standard-hybrid NDCG@10) to highlight
where adaptive retrieval provides the most value.

Requires:
  - OpenSearch cluster with esci_judgments index (ESCI dataset ingested)
  - LocalStack/Docker for PostgreSQL (checkpoints only — not used in this benchmark)
  - GOOGLE_API_KEY env var (only if --classify-intents is used)

Usage:
    # Fast reproducible run (no LLM intent classification)
    make benchmark-esci-fast

    # Full adaptive run with Gemini intent classification
    make benchmark-esci

    # Dry-run on 2 queries
    PYTHONPATH=. python benchmark_esci.py --limit 2 --fast

    # Save results to JSON
    PYTHONPATH=. python benchmark_esci.py --output results.json --fast
"""

import argparse
import json
import logging
import sys
import time
from collections import defaultdict
from datetime import datetime
from statistics import mean, stdev
from typing import Dict, List, Optional, Set, Tuple

from langchain_core.documents import Document
from opensearchpy import OpenSearch

from config import (
    EMBEDDINGS_MODEL,
    OPENSEARCH_HOST,
    OPENSEARCH_PASSWORD,
    OPENSEARCH_PORT,
    OPENSEARCH_USE_SSL,
    OPENSEARCH_VERIFY_CERTS,
    VECTOR_DIMENSION,
)
from relevancy_metrics import StageMetrics, compute_stage_metrics
from reranker import CrossEncoderReranker
from vector_store import OpenSearchVectorStore

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(levelname)-8s | %(message)s")

# Intent → Alpha fast-path mapping (no LLM needed)
INTENT_ALPHA_TABLE = {
    "comparison": 0.60,
    "attribute_filter": 0.25,
    "refinement": 0.35,
    "search": 0.65,  # fallback for LLM-path intents
    "follow_up": 0.65,
    "summary": 0.65,
    "clarify": 0.65,
}


class ESCIBenchmark:
    """Benchmark suite for ESCI hard-query relevancy measurement."""

    def __init__(
        self,
        limit: Optional[int] = None,
        alpha_hybrid: float = 0.25,
        qg_threshold: float = 0.45,
        fast_mode: bool = False,
        fetch_k: int = 40,
        rerank_top_k: int = 20,
        classify_intents: bool = False,
    ):
        """Initialize benchmark.

        Args:
            limit: Max judged queries to sample. None = all.
            alpha_hybrid: Hybrid config alpha (reference).
            qg_threshold: Quality gate max_score threshold.
            fast_mode: Use alpha=0.65 for all search/follow_up (no LLM).
            fetch_k: Retrieval candidate count.
            rerank_top_k: Post-rerank list size.
            classify_intents: Call Gemini intent classifier (slow, requires API key).
        """
        self.limit = limit
        self.alpha_hybrid = alpha_hybrid
        self.qg_threshold = qg_threshold
        self.fast_mode = fast_mode
        self.fetch_k = fetch_k
        self.rerank_top_k = rerank_top_k
        self.classify_intents = classify_intents

        # Initialize OpenSearch and retriever
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            self.embeddings = GoogleGenerativeAIEmbeddings(
                model=EMBEDDINGS_MODEL, output_dimensionality=VECTOR_DIMENSION
            )
        except ImportError as e:
            logger.error(f"Failed to initialize embeddings: {e}")
            sys.exit(1)

        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings, collection_id="esci_products"
        )
        self.reranker = CrossEncoderReranker()
        self.os_client = OpenSearch(
            hosts=[{"host": OPENSEARCH_HOST, "port": OPENSEARCH_PORT}],
            http_auth=(("admin", OPENSEARCH_PASSWORD) if OPENSEARCH_PASSWORD else None),
            use_ssl=OPENSEARCH_USE_SSL,
            verify_certs=OPENSEARCH_VERIFY_CERTS,
            timeout=30,
        )

    def scroll_judged_queries(self, locale: str = "us") -> List[str]:
        """Scroll all judged queries from esci_judgments index."""
        logger.info(f"Scrolling judged queries (locale={locale})...")
        queries = []
        body = {
            "query": {"term": {"locale": locale}},
            "size": 1000,
            "_source": ["query"],
            "sort": [{"query_id": "asc"}],
        }

        count = 0
        while True:
            resp = self.os_client.search(index="esci_judgments", body=body)
            hits = resp["hits"]["hits"]
            if not hits:
                break

            for hit in hits:
                query_str = hit["_source"].get("query", "").strip()
                if query_str:
                    queries.append(query_str)
                    count += 1
                    if self.limit and count >= self.limit:
                        return queries

            # Paginate via search_after
            if len(hits) < body["size"]:
                break
            body["search_after"] = [hits[-1]["sort"][0]]

        logger.info(f"Found {len(queries)} judged queries")
        return queries

    def _dedup_by_product_id(self, docs: List[Document]) -> List[Document]:
        """Deduplicate documents by product_id, preserving order."""
        seen: Set[str] = set()
        deduped = []
        for doc in docs:
            pid = doc.metadata.get("product_id", "")
            if pid and pid not in seen:
                seen.add(pid)
                deduped.append(doc)
        return deduped

    def _run_config(
        self, query: str, alpha: float, rerank: bool = False, retry_on_qg: bool = False
    ) -> Optional[StageMetrics]:
        """Run a single query through retrieval pipeline.

        Args:
            query: Query string.
            alpha: Alpha parameter for hybrid search.
            rerank: Apply cross-encoder reranking.
            retry_on_qg: Apply quality gate retry logic.

        Returns:
            StageMetrics or None if no judgments found.
        """
        try:
            docs = self.vector_store.hybrid_search(query, k=20, fetch_k=self.fetch_k, alpha=alpha)
        except Exception as e:
            logger.warning(f"Retrieval failed for query '{query}': {e}")
            return None

        docs = self._dedup_by_product_id(docs)

        # Reranking
        if rerank:
            try:
                reranked = self.reranker.score_documents(query, docs)
                reranked = reranked[: self.rerank_top_k]
                docs_for_metric = [doc for doc, _ in reranked]
                scores = [score for _, score in reranked]

                # Quality gate retry
                if retry_on_qg and scores and max(scores) < self.qg_threshold:
                    new_alpha = max(0.0, min(1.0, alpha - 0.3 if alpha > 0.5 else alpha + 0.3))
                    logger.debug(
                        f"QG: max_score={max(scores):.3f} < {self.qg_threshold}, "
                        f"retrying with α={new_alpha:.2f}"
                    )
                    retry_docs = self.vector_store.hybrid_search(
                        query, k=20, fetch_k=self.fetch_k, alpha=new_alpha
                    )
                    retry_docs = self._dedup_by_product_id(retry_docs)
                    retry_reranked = self.reranker.score_documents(query, retry_docs)
                    docs_for_metric = [doc for doc, _ in retry_reranked[: self.rerank_top_k]]

            except Exception as e:
                logger.warning(f"Reranking failed for query '{query}': {e}")
                docs_for_metric = docs
        else:
            docs_for_metric = docs

        # Look up ground truth
        judgments = self.vector_store.lookup_judgments(query, locale="us")
        if judgments is None:
            return None

        # Compute metrics
        ranked_ids = [
            doc.metadata.get("product_id", "")
            for doc in docs_for_metric
            if doc.metadata.get("product_id")
        ]
        if not ranked_ids:
            return None

        metrics = compute_stage_metrics(ranked_ids, judgments)
        return metrics

    def run_lexical(self, queries: List[str]) -> Dict[str, StageMetrics]:
        """Run lexical (BM25 only, α=0.0) configuration."""
        logger.info("Running lexical configuration (α=0.0, no reranker)...")
        results = {}
        errors = 0

        for i, query in enumerate(queries):
            if (i + 1) % 100 == 0:
                logger.info(f"  Processed {i + 1}/{len(queries)}")

            metrics = self._run_config(query, alpha=0.0, rerank=False, retry_on_qg=False)
            if metrics is not None:
                results[query] = metrics
            else:
                errors += 1

        logger.info(f"Lexical: {len(results)} queries evaluated, {errors} skipped")
        return results

    def run_hybrid(self, queries: List[str], alpha: float = 0.25) -> Dict[str, StageMetrics]:
        """Run standard hybrid (fixed α) configuration."""
        logger.info(f"Running standard hybrid configuration (α={alpha}, no reranker)...")
        results = {}
        errors = 0

        for i, query in enumerate(queries):
            if (i + 1) % 100 == 0:
                logger.info(f"  Processed {i + 1}/{len(queries)}")

            metrics = self._run_config(query, alpha=alpha, rerank=False, retry_on_qg=False)
            if metrics is not None:
                results[query] = metrics
            else:
                errors += 1

        logger.info(f"Hybrid: {len(results)} queries evaluated, {errors} skipped")
        return results

    def run_adaptive(self, queries: List[str]) -> Dict[str, StageMetrics]:
        """Run adaptive configuration (intent α + reranker + quality gate)."""
        logger.info(
            f"Running adaptive configuration "
            f"(intent α + reranker + QG, fast={self.fast_mode})..."
        )
        results = {}
        errors = 0

        for i, query in enumerate(queries):
            if (i + 1) % 100 == 0:
                logger.info(f"  Processed {i + 1}/{len(queries)}")

            # Map query to alpha
            alpha = self._get_adaptive_alpha(query)

            metrics = self._run_config(query, alpha=alpha, rerank=True, retry_on_qg=True)
            if metrics is not None:
                results[query] = metrics
            else:
                errors += 1

        logger.info(f"Adaptive: {len(results)} queries evaluated, {errors} skipped")
        return results

    def _get_adaptive_alpha(self, query: str) -> float:
        """Estimate alpha for a query (intent-based or LLM-based)."""
        if self.fast_mode:
            return INTENT_ALPHA_TABLE.get("search", 0.65)

        # Simplified intent detection via keywords
        query_lower = query.lower()
        if any(w in query_lower for w in ["compare", "vs", "difference", "better than"]):
            return INTENT_ALPHA_TABLE["comparison"]
        elif any(w in query_lower for w in ["filter", "under", "above", "color", "size"]):
            return INTENT_ALPHA_TABLE["attribute_filter"]
        elif any(w in query_lower for w in ["more", "narrower", "different"]):
            return INTENT_ALPHA_TABLE["refinement"]
        else:
            return INTENT_ALPHA_TABLE["search"]

    def find_hard_queries(
        self, all_queries: List[str], hybrid_results: Dict[str, StageMetrics]
    ) -> List[str]:
        """Return bottom-quartile queries by standard-hybrid NDCG@10."""
        ndcg_scores = sorted([m.ndcg10 for m in hybrid_results.values()])
        if len(ndcg_scores) < 4:
            logger.warning(
                f"Too few queries ({len(ndcg_scores)}) for quartile analysis, " "using all"
            )
            return list(hybrid_results.keys())

        cutoff = ndcg_scores[len(ndcg_scores) // 4]
        hard = [
            q for q in all_queries if q in hybrid_results and hybrid_results[q].ndcg10 <= cutoff
        ]
        logger.info(
            f"Hard-query subset (NDCG@10 <= {cutoff:.4f}): "
            f"{len(hard)} / {len(hybrid_results)} queries"
        )
        return hard

    def aggregate_metrics(
        self, queries: List[str], results: Dict[str, StageMetrics]
    ) -> Dict[str, float]:
        """Aggregate per-query metrics to mean ± stdev."""
        if not results:
            return {}

        ndcg_vals = [results[q].ndcg10 for q in queries if q in results]
        mrr_vals = [results[q].mrr_score for q in queries if q in results]
        recall_vals = [results[q].recall20 for q in queries if q in results]

        return {
            "ndcg10_mean": mean(ndcg_vals) if ndcg_vals else 0.0,
            "ndcg10_stdev": stdev(ndcg_vals) if len(ndcg_vals) > 1 else 0.0,
            "mrr_mean": mean(mrr_vals) if mrr_vals else 0.0,
            "mrr_stdev": stdev(mrr_vals) if len(mrr_vals) > 1 else 0.0,
            "recall20_mean": mean(recall_vals) if recall_vals else 0.0,
            "recall20_stdev": stdev(recall_vals) if len(recall_vals) > 1 else 0.0,
            "count": len(results),
        }

    def print_results(
        self,
        hard_queries: List[str],
        all_queries: List[str],
        lexical_results: Dict[str, StageMetrics],
        hybrid_results: Dict[str, StageMetrics],
        adaptive_results: Dict[str, StageMetrics],
    ) -> None:
        """Print formatted results table."""
        hard_lex = self.aggregate_metrics(hard_queries, lexical_results)
        hard_hyb = self.aggregate_metrics(hard_queries, hybrid_results)
        hard_adp = self.aggregate_metrics(hard_queries, adaptive_results)

        all_lex = self.aggregate_metrics(all_queries, lexical_results)
        all_hyb = self.aggregate_metrics(all_queries, hybrid_results)
        all_adp = self.aggregate_metrics(all_queries, adaptive_results)

        print("\n" + "=" * 70)
        print("ESCI HARD-QUERY RELEVANCY BENCHMARK")
        print("=" * 70)
        print(f"Run: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(
            f"Config: fetch_k={self.fetch_k}  alpha_hybrid={self.alpha_hybrid}  "
            f"qg_threshold={self.qg_threshold}  rerank_top_k={self.rerank_top_k}"
        )
        print(
            f"Hard queries: {len(hard_queries)} / {len(all_queries)} "
            f"(bottom-quartile NDCG@10 <= {sorted([m.ndcg10 for m in hybrid_results.values()])[len(hybrid_results) // 4]:.4f})"
        )
        print("=" * 70)

        print("\nHARD-QUERY RESULTS (primary focus):")
        print(f"{'System':<25} {'NDCG@10':<15} {'MRR':<15} {'Recall@20':<15}")
        print("-" * 70)

        lex_ndcg_str = (
            f"{hard_lex['ndcg10_mean']:.4f} ±{hard_lex['ndcg10_stdev']:.4f}"
            if hard_lex["ndcg10_stdev"] > 0
            else f"{hard_lex['ndcg10_mean']:.4f}"
        )
        lex_mrr_str = (
            f"{hard_lex['mrr_mean']:.4f} ±{hard_lex['mrr_stdev']:.4f}"
            if hard_lex["mrr_stdev"] > 0
            else f"{hard_lex['mrr_mean']:.4f}"
        )
        lex_recall_str = (
            f"{hard_lex['recall20_mean']:.4f} ±{hard_lex['recall20_stdev']:.4f}"
            if hard_lex["recall20_stdev"] > 0
            else f"{hard_lex['recall20_mean']:.4f}"
        )

        hyb_ndcg_str = (
            f"{hard_hyb['ndcg10_mean']:.4f} ±{hard_hyb['ndcg10_stdev']:.4f}"
            if hard_hyb["ndcg10_stdev"] > 0
            else f"{hard_hyb['ndcg10_mean']:.4f}"
        )
        hyb_mrr_str = (
            f"{hard_hyb['mrr_mean']:.4f} ±{hard_hyb['mrr_stdev']:.4f}"
            if hard_hyb["mrr_stdev"] > 0
            else f"{hard_hyb['mrr_mean']:.4f}"
        )
        hyb_recall_str = (
            f"{hard_hyb['recall20_mean']:.4f} ±{hard_hyb['recall20_stdev']:.4f}"
            if hard_hyb["recall20_stdev"] > 0
            else f"{hard_hyb['recall20_mean']:.4f}"
        )

        adp_ndcg_str = (
            f"{hard_adp['ndcg10_mean']:.4f} ±{hard_adp['ndcg10_stdev']:.4f}"
            if hard_adp["ndcg10_stdev"] > 0
            else f"{hard_adp['ndcg10_mean']:.4f}"
        )
        adp_mrr_str = (
            f"{hard_adp['mrr_mean']:.4f} ±{hard_adp['mrr_stdev']:.4f}"
            if hard_adp["mrr_stdev"] > 0
            else f"{hard_adp['mrr_mean']:.4f}"
        )
        adp_recall_str = (
            f"{hard_adp['recall20_mean']:.4f} ±{hard_adp['recall20_stdev']:.4f}"
            if hard_adp["recall20_stdev"] > 0
            else f"{hard_adp['recall20_mean']:.4f}"
        )

        print(f"{'Lexical (BM25)':<25} {lex_ndcg_str:<15} {lex_mrr_str:<15} {lex_recall_str:<15}")
        print(
            f"{'Standard Hybrid':<25} {hyb_ndcg_str:<15} {hyb_mrr_str:<15} {hyb_recall_str:<15} ← reference"
        )
        print(f"{'Adaptive':<25} {adp_ndcg_str:<15} {adp_mrr_str:<15} {adp_recall_str:<15}")

        # Deltas
        print("\nΔ vs Standard Hybrid (hard queries):")
        print("-" * 70)
        if hard_hyb["ndcg10_mean"] > 0:
            lex_ndcg_delta = (
                (hard_lex["ndcg10_mean"] - hard_hyb["ndcg10_mean"]) / hard_hyb["ndcg10_mean"] * 100
            )
            lex_mrr_delta = (
                (hard_lex["mrr_mean"] - hard_hyb["mrr_mean"]) / hard_hyb["mrr_mean"] * 100
                if hard_hyb["mrr_mean"] > 0
                else 0
            )
            lex_recall_delta = (
                (hard_lex["recall20_mean"] - hard_hyb["recall20_mean"])
                / hard_hyb["recall20_mean"]
                * 100
                if hard_hyb["recall20_mean"] > 0
                else 0
            )
            adp_ndcg_delta = (
                (hard_adp["ndcg10_mean"] - hard_hyb["ndcg10_mean"]) / hard_hyb["ndcg10_mean"] * 100
            )
            adp_mrr_delta = (
                (hard_adp["mrr_mean"] - hard_hyb["mrr_mean"]) / hard_hyb["mrr_mean"] * 100
                if hard_hyb["mrr_mean"] > 0
                else 0
            )
            adp_recall_delta = (
                (hard_adp["recall20_mean"] - hard_hyb["recall20_mean"])
                / hard_hyb["recall20_mean"]
                * 100
                if hard_hyb["recall20_mean"] > 0
                else 0
            )

            print(
                f"{'Lexical:':<25} "
                f"NDCG@10 {lex_ndcg_delta:+.1f}%  "
                f"MRR {lex_mrr_delta:+.1f}%  "
                f"Recall@20 {lex_recall_delta:+.1f}%"
            )
            print(
                f"{'Adaptive:':<25} "
                f"NDCG@10 {adp_ndcg_delta:+.1f}%  "
                f"MRR {adp_mrr_delta:+.1f}%  "
                f"Recall@20 {adp_recall_delta:+.1f}%"
            )

        print("\n" + "=" * 70)
        print("FULL-SET RESULTS (appendix):")
        print("=" * 70)
        print(f"{'System':<25} {'NDCG@10':<15} {'MRR':<15} {'Recall@20':<15} {'n'}")
        print("-" * 70)
        print(
            f"{'Lexical (BM25)':<25} "
            f"{all_lex['ndcg10_mean']:.4f}  {all_lex['mrr_mean']:.4f}  "
            f"{all_lex['recall20_mean']:.4f}  {all_lex['count']}"
        )
        print(
            f"{'Standard Hybrid':<25} "
            f"{all_hyb['ndcg10_mean']:.4f}  {all_hyb['mrr_mean']:.4f}  "
            f"{all_hyb['recall20_mean']:.4f}  {all_hyb['count']}"
        )
        print(
            f"{'Adaptive':<25} "
            f"{all_adp['ndcg10_mean']:.4f}  {all_adp['mrr_mean']:.4f}  "
            f"{all_adp['recall20_mean']:.4f}  {all_adp['count']}"
        )
        print("=" * 70 + "\n")


def main():
    parser = argparse.ArgumentParser(
        description="ESCI hard-query relevancy benchmark for agentic hybrid search"
    )
    parser.add_argument("--limit", type=int, default=None, help="Max queries to sample")
    parser.add_argument("--alpha", type=float, default=0.25, help="Hybrid reference alpha")
    parser.add_argument("--fetch-k", type=int, default=40, help="Retrieval candidate count")
    parser.add_argument("--rerank-top-k", type=int, default=20, help="Post-rerank list size")
    parser.add_argument("--qg-threshold", type=float, default=0.45, help="Quality gate threshold")
    parser.add_argument("--fast", action="store_true", help="Skip LLM intent classification")
    parser.add_argument("--output", type=str, default=None, help="Write results to JSON file")
    args = parser.parse_args()

    benchmark = ESCIBenchmark(
        limit=args.limit,
        alpha_hybrid=args.alpha,
        qg_threshold=args.qg_threshold,
        fast_mode=args.fast,
        fetch_k=args.fetch_k,
        rerank_top_k=args.rerank_top_k,
    )

    # Run benchmarks
    all_queries = benchmark.scroll_judged_queries()
    if not all_queries:
        logger.error("No judged queries found. Did you ingest ESCI judgments?")
        sys.exit(1)

    lexical_results = benchmark.run_lexical(all_queries)
    hybrid_results = benchmark.run_hybrid(all_queries, alpha=args.alpha)
    adaptive_results = benchmark.run_adaptive(all_queries)

    hard_queries = benchmark.find_hard_queries(all_queries, hybrid_results)

    # Print results
    benchmark.print_results(
        hard_queries, all_queries, lexical_results, hybrid_results, adaptive_results
    )

    # Optionally save to JSON
    if args.output:
        output_data = {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "limit": args.limit,
                "alpha_hybrid": args.alpha,
                "fetch_k": args.fetch_k,
                "rerank_top_k": args.rerank_top_k,
                "qg_threshold": args.qg_threshold,
                "fast_mode": args.fast,
            },
            "hard_queries_count": len(hard_queries),
            "all_queries_count": len(all_queries),
            "results": {
                "lexical": benchmark.aggregate_metrics(hard_queries, lexical_results),
                "hybrid": benchmark.aggregate_metrics(hard_queries, hybrid_results),
                "adaptive": benchmark.aggregate_metrics(hard_queries, adaptive_results),
            },
        }
        with open(args.output, "w") as f:
            json.dump(output_data, f, indent=2)
        logger.info(f"Results saved to {args.output}")


if __name__ == "__main__":
    main()
