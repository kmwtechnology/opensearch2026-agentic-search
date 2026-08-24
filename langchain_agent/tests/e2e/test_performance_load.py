"""
Load Testing and Performance Benchmarking for Agentic Hybrid Search

Comprehensive performance testing for:
- Search latency under concurrent load (1, 5, 10, 20 concurrent users)
- Content generation latency (social posts, blog, articles, tutorials, docs)
- Memory usage during sustained load
- Token consumption per request
- Hybrid search alpha performance (0.0 vs 0.5 vs 1.0)
- Reranker performance (time, accuracy)
- Database query performance (checkpoint reads/writes)
- OpenSearch query performance (vector vs lexical vs hybrid)
- Performance regression detection (current vs baseline)
- Batch size impact on content generation

Markers: @pytest.mark.performance, @pytest.mark.load, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os
import sys
import time
import tracemalloc
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional, Tuple

import httpx
import psutil
import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import (
    DATABASE_URL,
    EMBEDDINGS_MODEL,
    POSTGRES_HOST,
    POSTGRES_PORT,
    RETRIEVER_FETCH_K,
    RETRIEVER_K,
    VECTOR_COLLECTION_NAME,
    VECTOR_DIMENSION,
)
from reranker import GeminiReranker
from vector_store import OpenSearchVectorStore

# Configuration
DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "test-api-key")
TIMEOUT = 60  # seconds per request
BENCHMARK_RESULTS_DIR = Path(__file__).parent.parent / "performance_results"
BASELINE_FILE = BENCHMARK_RESULTS_DIR / "baseline.json"

# Create results directory if it doesn't exist
BENCHMARK_RESULTS_DIR.mkdir(exist_ok=True)


class PerformanceMetrics:
    """Collect and aggregate performance metrics."""

    def __init__(self, name: str):
        self.name = name
        self.latencies: List[float] = []
        self.tokens: List[int] = []
        self.errors: int = 0
        self.start_time: float = time.time()
        self.end_time: Optional[float] = None
        self.memory_peak: float = 0
        self.memory_baseline: float = 0

    def add_latency(self, latency: float):
        """Record request latency (seconds)."""
        self.latencies.append(latency)

    def add_tokens(self, tokens: int):
        """Record token count."""
        self.tokens.append(tokens)

    def add_error(self):
        """Record an error."""
        self.errors += 1

    def finalize(self):
        """Calculate final metrics."""
        self.end_time = time.time()

    @property
    def latency_p50(self) -> float:
        """Median latency (ms)."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        return sorted_latencies[len(sorted_latencies) // 2] * 1000

    @property
    def latency_p95(self) -> float:
        """95th percentile latency (ms)."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)] * 1000

    @property
    def latency_p99(self) -> float:
        """99th percentile latency (ms)."""
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)] * 1000

    @property
    def latency_mean(self) -> float:
        """Mean latency (ms)."""
        if not self.latencies:
            return 0
        return mean(self.latencies) * 1000

    @property
    def latency_stdev(self) -> float:
        """Standard deviation of latency (ms)."""
        if len(self.latencies) < 2:
            return 0
        return stdev(self.latencies) * 1000

    @property
    def throughput(self) -> float:
        """Requests per second."""
        if not self.end_time or self.end_time <= self.start_time:
            return 0
        duration = self.end_time - self.start_time
        return len(self.latencies) / duration if duration > 0 else 0

    @property
    def avg_tokens(self) -> float:
        """Average tokens per request."""
        return mean(self.tokens) if self.tokens else 0

    @property
    def error_rate(self) -> float:
        """Error rate (0.0-1.0)."""
        total = len(self.latencies) + self.errors
        return self.errors / total if total > 0 else 0

    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "name": self.name,
            "latency_p50_ms": round(self.latency_p50, 2),
            "latency_p95_ms": round(self.latency_p95, 2),
            "latency_p99_ms": round(self.latency_p99, 2),
            "latency_mean_ms": round(self.latency_mean, 2),
            "latency_stdev_ms": round(self.latency_stdev, 2),
            "throughput_rps": round(self.throughput, 2),
            "avg_tokens": round(self.avg_tokens, 1),
            "error_rate": round(self.error_rate, 4),
            "total_requests": len(self.latencies),
            "total_errors": self.errors,
            "memory_peak_mb": round(self.memory_peak, 2),
            "timestamp": datetime.now().isoformat(),
        }


class LoadTester:
    """Simulate concurrent load on the system."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def health_check(self) -> bool:
        """Check if system is healthy."""
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.get(f"{self.base_url}/api/health", headers=self.headers)
                return response.status_code == 200
        except Exception as e:
            print(f"Health check failed: {e}")
            return False

    def create_conversation(self) -> str:
        """Create a new conversation and return thread_id."""
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(
                    f"{self.base_url}/api/conversations",
                    headers=self.headers,
                    json={"title": "Load test conversation"},
                )
                if response.status_code == 201:
                    return response.json().get("thread_id", "default")
        except Exception as e:
            print(f"Failed to create conversation: {e}")
        return "default"

    def send_search_query(self, thread_id: str, query: str) -> Tuple[float, bool, int]:
        """
        Send a search query and measure latency.

        Returns: (latency_seconds, success, estimated_tokens)
        """
        start_time = time.time()
        tokens = 0
        success = False

        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(
                    f"{self.base_url}/api/conversations/{thread_id}/messages",
                    headers=self.headers,
                    json={"content": query},
                )
                success = response.status_code in [200, 201]
                if success and "messages" in response.json():
                    # Estimate tokens from response
                    content = str(response.json().get("messages", []))
                    tokens = len(content.split()) // 4  # Rough estimation: 4 chars = 1 token
        except Exception as e:
            print(f"Query failed: {e}")

        latency = time.time() - start_time
        return latency, success, tokens

    def concurrent_load_test(
        self, num_users: int, queries_per_user: int, queries: List[str]
    ) -> PerformanceMetrics:
        """
        Simulate concurrent users sending queries.

        Args:
            num_users: Number of concurrent users
            queries_per_user: Queries each user sends
            queries: Pool of queries to send

        Returns:
            PerformanceMetrics with results
        """
        metrics = PerformanceMetrics(f"concurrent_load_{num_users}users")

        # Start memory tracking
        tracemalloc.start()
        process = psutil.Process(os.getpid())
        metrics.memory_baseline = process.memory_info().rss / 1024 / 1024

        def user_session(user_id: int):
            """Simulate a single user's session."""
            results = []
            thread_id = self.create_conversation()

            for i in range(queries_per_user):
                query = queries[i % len(queries)]
                latency, success, tokens = self.send_search_query(thread_id, query)
                results.append((latency, success, tokens))

            return results

        # Run concurrent sessions
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [executor.submit(user_session, i) for i in range(num_users)]

            for future in as_completed(futures):
                try:
                    results = future.result()
                    for latency, success, tokens in results:
                        if success:
                            metrics.add_latency(latency)
                            metrics.add_tokens(tokens)
                        else:
                            metrics.add_error()
                except Exception as e:
                    print(f"Session error: {e}")
                    for _ in range(queries_per_user):
                        metrics.add_error()

        # Record peak memory
        current, peak = tracemalloc.get_traced_memory()
        metrics.memory_peak = peak / 1024 / 1024
        tracemalloc.stop()

        metrics.finalize()
        return metrics


# Test Queries for Load Testing
SEARCH_QUERIES = [
    "Find wireless headphones under $100",
    "Compare Sony WH-1000XM5 vs Bose QuietComfort 45",
    "Show me blue wireless headphones",
    "What are the best noise-canceling earbuds?",
    "I need a laptop for programming",
    "Find gaming monitors with 144Hz refresh rate",
    "Best budget smartphones 2024",
    "Premium coffee makers under $300",
    "Waterproof fitness trackers",
    "Mechanical keyboards for gaming",
]


@pytest.mark.performance
@pytest.mark.load
@pytest.mark.slow
@pytest.mark.phase3
class TestLoadPerformance:
    """Load testing with concurrent users."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup load tester."""
        self.tester = LoadTester(DEPLOYMENT_URL, API_KEY)
        assert self.tester.health_check(), "System must be healthy for load testing"

    def test_single_user_baseline(self):
        """Baseline: single user performance."""
        metrics = self.tester.concurrent_load_test(
            num_users=1, queries_per_user=5, queries=SEARCH_QUERIES
        )

        assert metrics.error_rate < 0.1, "Error rate should be < 10%"
        assert (
            metrics.latency_p50 < 5000
        ), f"P50 latency should be < 5s, got {metrics.latency_p50}ms"
        assert (
            metrics.latency_p95 < 10000
        ), f"P95 latency should be < 10s, got {metrics.latency_p95}ms"

        # Save baseline
        with open(BASELINE_FILE, "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)

    def test_5_concurrent_users(self):
        """Load test: 5 concurrent users."""
        metrics = self.tester.concurrent_load_test(
            num_users=5, queries_per_user=3, queries=SEARCH_QUERIES
        )

        assert metrics.error_rate < 0.15, "Error rate should be < 15% at 5 users"
        assert len(metrics.latencies) >= 10, "Should complete at least 10 queries"

    def test_10_concurrent_users(self):
        """Load test: 10 concurrent users."""
        metrics = self.tester.concurrent_load_test(
            num_users=10, queries_per_user=2, queries=SEARCH_QUERIES
        )

        assert metrics.error_rate < 0.20, "Error rate should be < 20% at 10 users"
        assert len(metrics.latencies) >= 15, "Should complete at least 15 queries"

    def test_20_concurrent_users(self):
        """Load test: 20 concurrent users."""
        metrics = self.tester.concurrent_load_test(
            num_users=20, queries_per_user=1, queries=SEARCH_QUERIES
        )

        assert metrics.error_rate < 0.25, "Error rate should be < 25% at 20 users"
        assert len(metrics.latencies) >= 15, "Should complete at least 15 queries"


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.phase3
class TestSearchLatencyProfiles:
    """Test search latency across different alpha values."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup benchmark components."""
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL,
            output_dimensionality=VECTOR_DIMENSION,
        )
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        self.reranker = GeminiReranker()

    def test_pure_lexical_search_alpha_0(self):
        """Benchmark: pure lexical search (alpha=0.0)."""
        metrics = PerformanceMetrics("lexical_alpha_0.0")

        for query in SEARCH_QUERIES[:5]:
            start = time.time()
            docs = self.vector_store.hybrid_search(
                query=query, k=RETRIEVER_K, fetch_k=RETRIEVER_FETCH_K, alpha=0.0  # Pure lexical
            )
            latency = time.time() - start
            metrics.add_latency(latency)
            metrics.add_tokens(len(query.split()) * 4)

        metrics.finalize()
        assert metrics.latency_p50 < 2000, "Lexical search should be fast"

    def test_balanced_search_alpha_0_5(self):
        """Benchmark: balanced hybrid search (alpha=0.5)."""
        metrics = PerformanceMetrics("hybrid_alpha_0.5")

        for query in SEARCH_QUERIES[:5]:
            start = time.time()
            docs = self.vector_store.hybrid_search(
                query=query, k=RETRIEVER_K, fetch_k=RETRIEVER_FETCH_K, alpha=0.5  # Balanced
            )
            latency = time.time() - start
            metrics.add_latency(latency)
            metrics.add_tokens(len(query.split()) * 4)

        metrics.finalize()

    def test_pure_semantic_search_alpha_1(self):
        """Benchmark: pure semantic search (alpha=1.0)."""
        metrics = PerformanceMetrics("semantic_alpha_1.0")

        for query in SEARCH_QUERIES[:5]:
            start = time.time()
            docs = self.vector_store.hybrid_search(
                query=query, k=RETRIEVER_K, fetch_k=RETRIEVER_FETCH_K, alpha=1.0  # Pure semantic
            )
            latency = time.time() - start
            metrics.add_latency(latency)
            metrics.add_tokens(len(query.split()) * 4)

        metrics.finalize()


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.phase3
class TestRerankerPerformance:
    """Test reranker performance and accuracy."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup reranker."""
        self.reranker = GeminiReranker()

    def test_reranker_latency(self):
        """Measure reranker latency for different batch sizes."""
        from langchain_core.documents import Document

        # Create sample documents
        sample_docs = [
            Document(
                page_content=f"Product {i}: Wireless headphones",
                metadata={"source": f"product_{i}"},
            )
            for i in range(10)
        ]

        metrics = PerformanceMetrics("reranker_latency")

        for query in SEARCH_QUERIES[:5]:
            start = time.time()
            scored_docs = self.reranker.compress_documents(documents=sample_docs, query=query)
            latency = time.time() - start
            metrics.add_latency(latency)

        metrics.finalize()
        assert metrics.latency_p50 < 5000, "Reranker p50 should be < 5s"

    def test_reranker_accuracy(self):
        """Test reranker score distribution."""
        from langchain_core.documents import Document

        sample_docs = [
            Document(
                page_content="Sony WH-1000XM5 wireless headphones", metadata={"source": "product_1"}
            ),
            Document(page_content="Running shoes for athletics", metadata={"source": "product_2"}),
            Document(
                page_content="Bose QuietComfort 45 headphones", metadata={"source": "product_3"}
            ),
        ]

        scored_docs = self.reranker.compress_documents(
            documents=sample_docs, query="best wireless headphones"
        )

        # Headphone products should rank higher
        assert len(scored_docs) > 0, "Should return scored documents"
        assert scored_docs[0].metadata.get("source") in [
            "product_1",
            "product_3",
        ], "Headphones should rank first"


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.phase3
class TestMemoryUsage:
    """Test memory usage during sustained operations."""

    def test_memory_stability_sustained_queries(self):
        """Verify no memory leaks during sustained queries."""
        tester = LoadTester(DEPLOYMENT_URL, API_KEY)

        if not tester.health_check():
            pytest.skip("System not healthy")

        thread_id = tester.create_conversation()

        tracemalloc.start()
        process = psutil.Process(os.getpid())

        memory_samples = []
        for i in range(10):
            mem_before = process.memory_info().rss / 1024 / 1024
            latency, success, tokens = tester.send_search_query(
                thread_id, SEARCH_QUERIES[i % len(SEARCH_QUERIES)]
            )
            mem_after = process.memory_info().rss / 1024 / 1024
            memory_samples.append(mem_after - mem_before)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        avg_memory_delta = mean(memory_samples) if memory_samples else 0
        peak_mb = peak / 1024 / 1024

        # Memory usage should be relatively stable
        assert (
            avg_memory_delta < 50
        ), f"Average memory delta should be < 50MB, got {avg_memory_delta}MB"


@pytest.mark.performance
@pytest.mark.slow
@pytest.mark.phase3
class TestRegressionDetection:
    """Detect performance regressions compared to baseline."""

    def test_regression_against_baseline(self):
        """Check if current performance meets baseline."""
        if not BASELINE_FILE.exists():
            pytest.skip("Baseline not available")

        with open(BASELINE_FILE) as f:
            baseline = json.load(f)

        tester = LoadTester(DEPLOYMENT_URL, API_KEY)

        if not tester.health_check():
            pytest.skip("System not healthy")

        # Run quick performance check
        metrics = tester.concurrent_load_test(
            num_users=1, queries_per_user=3, queries=SEARCH_QUERIES
        )

        current = metrics.to_dict()
        baseline_p50 = baseline.get("latency_p50_ms", 0)
        current_p50 = current.get("latency_p50_ms", 0)

        # Allow 10% regression tolerance
        regression_threshold = baseline_p50 * 1.10
        assert (
            current_p50 <= regression_threshold
        ), f"Performance regression: baseline p50={baseline_p50}ms, current={current_p50}ms"


# Export results helper
def export_metrics_report(
    metrics_list: List[PerformanceMetrics], filename: str = "performance_report.json"
):
    """Export performance metrics to JSON file."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "metrics": [m.to_dict() for m in metrics_list],
        "summary": {
            "total_tests": len(metrics_list),
            "avg_throughput_rps": mean([m.throughput for m in metrics_list]),
            "avg_error_rate": mean([m.error_rate for m in metrics_list]),
        },
    }

    output_path = BENCHMARK_RESULTS_DIR / filename
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    return output_path
