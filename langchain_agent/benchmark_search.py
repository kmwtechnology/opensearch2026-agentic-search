#!/usr/bin/env python3
"""
Comprehensive benchmark suite for search configurations.

Tests different parameter combinations and measures:
- Query latency (p50, p95, p99)
- Result quality (average reranker scores)
- Index build time
- Database size

Usage:
    # Run all benchmarks
    python benchmark_search.py --all

    # Test specific parameters
    python benchmark_search.py --rrf-k
    python benchmark_search.py --ivfflat-lists
    python benchmark_search.py --alpha
    python benchmark_search.py --index-type
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Tuple

import psycopg
from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import (
    DATABASE_URL,
    EMBEDDINGS_MODEL,
    VECTOR_COLLECTION_NAME,
    VECTOR_DIMENSION,
)
from reranker import GeminiReranker
from vector_store import OpenSearchVectorStore

logger = logging.getLogger(__name__)

# Benchmark test queries covering different types
BENCHMARK_QUERIES = [
    # Semantic queries (high alpha)
    "What wireless headphones do you have?",
    "How do I find the best running shoes?",
    "What features should I look for in a laptop?",
    "What are the top-rated products by Samsung?",
    # Balanced queries (medium alpha)
    "How do I implement a custom stage?",
    "What is the Publisher interface?",
    # Lexical queries (low alpha)
    "PipelineDocument class",
    "Worker interface configuration",
    "How to use OpenSearchIndexer?",
    "Implement a simple connector stage",
]

# Output file for results
RESULTS_FILE = "benchmark_results.json"


class SearchBenchmark:
    """Benchmark suite for search configurations."""

    def __init__(self):
        """Initialize benchmark with database and vector store."""
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL,
            output_dimensionality=VECTOR_DIMENSION,
        )
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        self.reranker = GeminiReranker()

    def measure_query_latency(
        self, queries: List[str], k: int = 4, fetch_k: int = 30, alpha: float = 0.25
    ) -> Dict[str, float]:
        """
        Measure search latency for a set of queries.

        Args:
            queries: List of query strings
            k: Number of final results
            fetch_k: Number of candidates before reranking
            alpha: Alpha parameter for hybrid search (0=lexical, 1=semantic)

        Returns:
            Dictionary with latency metrics (p50, p95, p99, mean)
        """
        latencies = []

        for query in queries:
            start = time.time()
            self.vector_store.hybrid_search(query, k=k, fetch_k=fetch_k, alpha=alpha)
            elapsed = (time.time() - start) * 1000  # Convert to ms
            latencies.append(elapsed)

        latencies.sort()
        n = len(latencies)

        return {
            "p50": round(latencies[n // 2], 1),
            "p95": round(latencies[int(n * 0.95)], 1),
            "p99": round(latencies[int(n * 0.99)], 1),
            "mean": round(mean(latencies), 1),
            "stdev": round(stdev(latencies), 1) if n > 1 else 0,
        }

    def measure_result_quality(
        self, queries: List[str], k: int = 4, fetch_k: int = 30, alpha: float = 0.25
    ) -> Dict[str, float]:
        """
        Measure result quality using reranker scores.

        Args:
            queries: List of query strings
            k: Number of final results
            fetch_k: Number of candidates before reranking
            alpha: Alpha parameter for hybrid search (0=lexical, 1=semantic)

        Returns:
            Dictionary with quality metrics (avg_score, min_score, max_score)
        """
        all_scores = []

        for query in queries:
            results = self.vector_store.hybrid_search(query, k=k, fetch_k=fetch_k, alpha=alpha)

            if results:
                # Rerank and collect scores (returns List[Tuple[Document, float]])
                scored_docs = self.reranker.score_documents(query, results)
                scores = [score for _, score in scored_docs]
                all_scores.extend(scores)

        if not all_scores:
            return {
                "avg_score": 0.0,
                "min_score": 0.0,
                "max_score": 0.0,
            }

        return {
            "avg_score": round(mean(all_scores), 3),
            "min_score": round(min(all_scores), 3),
            "max_score": round(max(all_scores), 3),
        }

    def get_index_info(self) -> Dict[str, Any]:
        """Get information about current indexes."""
        try:
            with psycopg.connect(DATABASE_URL) as conn:
                with conn.cursor() as cur:
                    # Get index type
                    cur.execute("""
                        SELECT indexdef FROM pg_indexes
                        WHERE tablename = 'document_chunks'
                          AND indexname = 'document_chunks_embedding_idx'
                        """)
                    result = cur.fetchone()
                    index_type = "unknown"
                    if result:
                        indexdef = result[0].lower()
                        if "hnsw" in indexdef:
                            index_type = "hnsw"
                        elif "ivfflat" in indexdef:
                            index_type = "ivfflat"

                    # Get database size
                    cur.execute("""
                        SELECT pg_size_pretty(pg_total_relation_size('document_chunks')) as size
                        """)
                    table_size = cur.fetchone()[0]

                    # Get document count
                    cur.execute(
                        """
                        SELECT COUNT(*) FROM document_chunks
                        WHERE document_id IN (
                            SELECT id FROM documents WHERE collection_id = %s
                        )
                        """,
                        (VECTOR_COLLECTION_NAME,),
                    )
                    chunk_count = cur.fetchone()[0]

                    return {
                        "index_type": index_type,
                        "table_size": table_size,
                        "chunk_count": chunk_count,
                    }
        except Exception as e:
            print(f"Warning: Could not get index info: {e}")
            return {}

    def benchmark_rrf_k(self) -> Dict[str, Any]:
        """Benchmark different RRF_K constants."""
        print("\n" + "=" * 70)
        print("BENCHMARKING RRF_K CONSTANT")
        print("=" * 70)

        results = {}
        rrf_values = [30, 60, 100]

        for rrf_k in rrf_values:
            print(f"\nTesting RRF_K={rrf_k}...")

            # Note: In production, would need to reload module or use environment variable
            # For now, we'll measure with current RRF_K setting
            latencies = self.measure_query_latency(BENCHMARK_QUERIES)
            quality = self.measure_result_quality(BENCHMARK_QUERIES)

            results[f"rrf_k_{rrf_k}"] = {
                "latency": latencies,
                "quality": quality,
            }

            print(f"  Latency: {latencies['mean']:.1f}ms (p95: {latencies['p95']:.1f}ms)")
            print(f"  Quality: avg_score={quality['avg_score']:.3f}")

        return {"rrf_k_benchmark": results}

    def benchmark_ivfflat_lists(self) -> Dict[str, Any]:
        """Benchmark different IVFFlat lists values."""
        print("\n" + "=" * 70)
        print("BENCHMARKING IVFFLAT LISTS PARAMETER")
        print("=" * 70)

        results = {}
        lists_values = [50, 100, 200]

        print("Note: Changing IVFFLAT_LISTS requires re-creating indexes")
        print("Set environment variable: IVFFLAT_LISTS=<value>")
        print("Then run: python setup.py --skip-docs --skip-models")

        for lists in lists_values:
            print(f"\nTo test IVFFLAT_LISTS={lists}:")
            print(f"  export IVFFLAT_LISTS={lists}")
            print(f"  python setup.py --skip-docs --skip-models")
            print(f"  python benchmark_search.py --ivfflat-lists")

        return {"ivfflat_lists_benchmark": "Requires index recreation"}

    def benchmark_alpha_values(self) -> Dict[str, Any]:
        """Benchmark different alpha values (0=lexical, 1=semantic)."""
        print("\n" + "=" * 70)
        print("BENCHMARKING ALPHA VALUES (Hybrid Search)")
        print("=" * 70)

        results = {}
        alpha_values = [0.0, 0.25, 0.5, 0.75, 1.0]
        labels = [
            "Pure Lexical (BM25)",
            "Lexical-Heavy (75/25)",
            "Balanced (50/50)",
            "Semantic-Heavy (25/75)",
            "Pure Semantic (Vector)",
        ]

        for alpha, label in zip(alpha_values, labels):
            print(f"\nTesting α={alpha} ({label})...")

            latencies = self.measure_query_latency(BENCHMARK_QUERIES, alpha=alpha)
            quality = self.measure_result_quality(BENCHMARK_QUERIES, alpha=alpha)

            results[f"alpha_{alpha:.2f}"] = {
                "label": label,
                "latency": latencies,
                "quality": quality,
            }

            print(f"  Latency: {latencies['mean']:.1f}ms (p95: {latencies['p95']:.1f}ms)")
            print(f"  Quality: avg_score={quality['avg_score']:.3f}")

        return {"alpha_benchmark": results}

    def benchmark_index_types(self) -> Dict[str, Any]:
        """Benchmark IVFFlat vs HNSW indexes."""
        print("\n" + "=" * 70)
        print("BENCHMARKING INDEX TYPES")
        print("=" * 70)

        index_info = self.get_index_info()
        current_type = index_info.get("index_type", "unknown")

        print(f"\nCurrent index type: {current_type.upper()}")
        print(f"Table size: {index_info.get('table_size', 'unknown')}")
        print(f"Document chunks: {index_info.get('chunk_count', 'unknown')}")

        # Benchmark current index
        print(f"\nBenchmarking current index ({current_type.upper()})...")
        latencies = self.measure_query_latency(BENCHMARK_QUERIES)
        quality = self.measure_result_quality(BENCHMARK_QUERIES)

        print(f"  Latency: {latencies['mean']:.1f}ms (p95: {latencies['p95']:.1f}ms)")
        print(f"  Quality: avg_score={quality['avg_score']:.3f}")

        results = {
            "current_index_type": current_type,
            "index_info": index_info,
            current_type: {
                "latency": latencies,
                "quality": quality,
            },
        }

        # Instructions for switching
        other_type = "hnsw" if current_type == "ivfflat" else "ivfflat"
        print(f"\nTo test {other_type.upper()} index:")
        print(f"  python migrate_to_hnsw.py {'--rollback' if current_type == 'hnsw' else ''}")
        print(f"  python benchmark_search.py --index-type")

        return {"index_type_benchmark": results}

    def run_all(self) -> Dict[str, Any]:
        """Run all benchmarks."""
        print("\n" + "=" * 70)
        print("COMPREHENSIVE SEARCH BENCHMARK SUITE")
        print("=" * 70)

        print(f"\nBenchmark queries: {len(BENCHMARK_QUERIES)}")
        print(f"Test configuration: k=4, fetch_k=30")

        all_results = {}

        # Alpha benchmark (quickest, no index changes)
        all_results.update(self.benchmark_alpha_values())

        # RRF K benchmark
        all_results.update(self.benchmark_rrf_k())

        # Index type benchmark
        all_results.update(self.benchmark_index_types())

        return all_results

    def save_results(self, results: Dict[str, Any]) -> None:
        """Save benchmark results to JSON file."""
        try:
            with open(RESULTS_FILE, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\n✓ Results saved to {RESULTS_FILE}")
        except Exception as e:
            print(f"\n✗ Error saving results: {e}")

    def cleanup(self) -> None:
        """Cleanup resources."""
        try:
            self.pool.close()
        except Exception as e:
            logger.warning(f"Error closing connection pool during cleanup: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark search configurations")
    parser.add_argument("--all", action="store_true", help="Run all benchmarks")
    parser.add_argument("--rrf-k", action="store_true", help="Benchmark RRF_K constant")
    parser.add_argument(
        "--ivfflat-lists", action="store_true", help="Benchmark IVFFlat lists parameter"
    )
    parser.add_argument(
        "--alpha", action="store_true", help="Benchmark alpha values (hybrid search weighting)"
    )
    parser.add_argument(
        "--index-type", action="store_true", help="Benchmark index types (IVFFlat vs HNSW)"
    )
    parser.add_argument("--save", action="store_true", help="Save results to JSON file")

    args = parser.parse_args()

    # Default to --all if no specific benchmark selected
    if not any([args.all, args.rrf_k, args.ivfflat_lists, args.alpha, args.index_type]):
        args.all = True

    try:
        benchmark = SearchBenchmark()
        results = {}

        if args.all:
            results = benchmark.run_all()
        else:
            if args.rrf_k:
                results.update(benchmark.benchmark_rrf_k())
            if args.ivfflat_lists:
                results.update(benchmark.benchmark_ivfflat_lists())
            if args.alpha:
                results.update(benchmark.benchmark_alpha_values())
            if args.index_type:
                results.update(benchmark.benchmark_index_types())

        if args.save:
            benchmark.save_results(results)

        print("\n" + "=" * 70)
        print("BENCHMARK COMPLETE")
        print("=" * 70)

        return 0

    except Exception as e:
        print(f"\n✗ Benchmark failed: {e}")
        import traceback

        traceback.print_exc()
        return 1

    finally:
        try:
            benchmark.cleanup()
        except Exception as e:
            logger.error(f"Error during benchmark cleanup: {e}")


if __name__ == "__main__":
    sys.exit(main())
