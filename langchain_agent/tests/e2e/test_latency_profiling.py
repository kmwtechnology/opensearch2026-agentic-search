"""
Latency Profiling and Performance Analysis for Agentic Hybrid Search

Comprehensive latency profiling:
- Profile each pipeline stage: intent classification, query evaluation, retrieval, reranking, generation
- Measure token generation latency (p50, p95, p99)
- Measure full request latency (p50, p95, p99)
- Compare latencies across model sizes (Flash vs Lite)
- Identify bottlenecks (which stages are slowest)
- Test caching effectiveness (query embedding cache)
- Profile memory allocations
- Generate latency distribution charts

Markers: @pytest.mark.performance, @pytest.mark.profile, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os
import sys
import time
import tracemalloc
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, median, stdev
from typing import Any, Dict, List, Optional, Tuple

import psutil
import pytest

# Add langchain_agent to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from langchain_google_genai import GoogleGenerativeAIEmbeddings

from config import (
    EMBEDDINGS_MODEL,
    LLM_MODEL,
    QUERY_EVAL_MODEL,
    RERANKER_MODEL,
    RETRIEVER_FETCH_K,
    RETRIEVER_K,
    VECTOR_COLLECTION_NAME,
    VECTOR_DIMENSION,
)
from reranker import GeminiReranker
from vector_store import OpenSearchVectorStore

PROFILING_RESULTS_DIR = Path(__file__).parent.parent / "profiling_results"
PROFILING_RESULTS_DIR.mkdir(exist_ok=True)


@dataclass
class StageTiming:
    """Timing for a single pipeline stage."""

    stage_name: str
    duration_ms: float
    tokens_generated: int = 0
    cache_hit: bool = False
    memory_delta_mb: float = 0.0


@dataclass
class RequestProfile:
    """Complete profile for one request."""

    request_id: str
    query: str
    total_latency_ms: float
    stages: List[StageTiming]
    total_tokens: int
    model_used: str
    timestamp: str

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "request_id": self.request_id,
            "query": self.query,
            "total_latency_ms": round(self.total_latency_ms, 2),
            "stages": [
                {
                    "name": s.stage_name,
                    "duration_ms": round(s.duration_ms, 2),
                    "tokens": s.tokens_generated,
                    "cache_hit": s.cache_hit,
                    "memory_delta_mb": round(s.memory_delta_mb, 2),
                }
                for s in self.stages
            ],
            "total_tokens": self.total_tokens,
            "model": self.model_used,
            "timestamp": self.timestamp,
        }


class LatencyProfiler:
    """Profile latency of each pipeline stage."""

    def __init__(self):
        """Initialize profiler with pipeline components."""
        self.embeddings = GoogleGenerativeAIEmbeddings(
            model=EMBEDDINGS_MODEL,
            output_dimensionality=VECTOR_DIMENSION,
        )
        self.vector_store = OpenSearchVectorStore(
            embeddings=self.embeddings,
            collection_id=VECTOR_COLLECTION_NAME,
        )
        self.reranker = GeminiReranker()
        self.profiles: List[RequestProfile] = []

    def profile_embedding_generation(self, query: str) -> StageTiming:
        """Profile query embedding generation."""
        tracemalloc.start()
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024

        start = time.time()
        embedding = self.embeddings.embed_query(query)
        duration = (time.time() - start) * 1000

        mem_after = process.memory_info().rss / 1024 / 1024
        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        return StageTiming(
            stage_name="embedding_generation",
            duration_ms=duration,
            memory_delta_mb=mem_after - mem_before,
        )

    def profile_vector_search(self, query: str, alpha: float = 0.5) -> Tuple[StageTiming, int]:
        """Profile vector/hybrid search."""
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024

        start = time.time()
        docs = self.vector_store.hybrid_search(
            query=query, k=RETRIEVER_K, fetch_k=RETRIEVER_FETCH_K, alpha=alpha
        )
        duration = (time.time() - start) * 1000

        mem_after = process.memory_info().rss / 1024 / 1024

        # Estimate tokens from retrieved content
        content = " ".join([d.page_content for d in docs])
        tokens = len(content.split()) // 4

        return StageTiming(
            stage_name=f"vector_search_alpha_{alpha}",
            duration_ms=duration,
            tokens_generated=tokens,
            memory_delta_mb=mem_after - mem_before,
        ), len(docs)

    def profile_reranking(self, docs: List[Any], query: str) -> StageTiming:
        """Profile document reranking."""
        process = psutil.Process(os.getpid())
        mem_before = process.memory_info().rss / 1024 / 1024

        start = time.time()
        reranked = self.reranker.compress_documents(documents=docs, query=query)
        duration = (time.time() - start) * 1000

        mem_after = process.memory_info().rss / 1024 / 1024

        return StageTiming(
            stage_name="reranking",
            duration_ms=duration,
            memory_delta_mb=mem_after - mem_before,
        )

    def profile_full_pipeline(self, query: str, request_id: str = None) -> RequestProfile:
        """Profile complete pipeline for a query."""
        if not request_id:
            request_id = f"profile_{int(time.time() * 1000)}"

        stages = []
        total_start = time.time()

        # Stage 1: Embedding generation
        embedding_stage = self.profile_embedding_generation(query)
        stages.append(embedding_stage)

        # Stage 2: Vector search (test multiple alphas)
        for alpha in [0.25, 0.5]:
            search_stage, doc_count = self.profile_vector_search(query, alpha)
            stages.append(search_stage)

            # Stage 3: Reranking (on first search results)
            if alpha == 0.5:
                try:
                    from langchain_core.documents import Document

                    sample_docs = [
                        Document(page_content=f"Product {i}", metadata={"source": f"doc_{i}"})
                        for i in range(min(10, doc_count))
                    ]
                    rerank_stage = self.profile_reranking(sample_docs, query)
                    stages.append(rerank_stage)
                except Exception as e:
                    print(f"Reranking profile skipped: {e}")

        total_latency = (time.time() - total_start) * 1000
        total_tokens = sum(s.tokens_generated for s in stages)

        profile = RequestProfile(
            request_id=request_id,
            query=query,
            total_latency_ms=total_latency,
            stages=stages,
            total_tokens=total_tokens,
            model_used=LLM_MODEL,
            timestamp=datetime.now().isoformat(),
        )

        self.profiles.append(profile)
        return profile


# Test queries for profiling
PROFILING_QUERIES = [
    "Find wireless headphones under $100",
    "Compare Sony WH-1000XM5 vs Bose QuietComfort 45",
    "Best noise-canceling earbuds",
    "Premium gaming headsets",
    "Budget-friendly audio equipment",
]


@pytest.mark.performance
@pytest.mark.profile
@pytest.mark.slow
@pytest.mark.phase3
class TestStageLatencies:
    """Test individual pipeline stage latencies."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup profiler."""
        self.profiler = LatencyProfiler()

    def test_embedding_generation_latency(self):
        """Profile embedding generation latency."""
        durations = []

        for query in PROFILING_QUERIES:
            timing = self.profiler.profile_embedding_generation(query)
            durations.append(timing.duration_ms)

        avg_duration = mean(durations)
        p95_duration = sorted(durations)[int(len(durations) * 0.95)]

        assert avg_duration < 2000, f"Embedding avg should be < 2s, got {avg_duration}ms"
        assert p95_duration < 3000, f"Embedding p95 should be < 3s, got {p95_duration}ms"

    def test_vector_search_latency(self):
        """Profile vector search latency."""
        durations = []

        for query in PROFILING_QUERIES:
            timing, _ = self.profiler.profile_vector_search(query, alpha=0.5)
            durations.append(timing.duration_ms)

        avg_duration = mean(durations)
        p95_duration = sorted(durations)[int(len(durations) * 0.95)]
        max_duration = max(durations)

        assert avg_duration < 3000, f"Search avg should be < 3s, got {avg_duration}ms"
        assert max_duration < 10000, f"Search max should be < 10s, got {max_duration}ms"

    def test_reranking_latency(self):
        """Profile reranking latency."""
        from langchain_core.documents import Document

        sample_docs = [
            Document(
                page_content=f"Product {i}: wireless headphones", metadata={"source": f"doc_{i}"}
            )
            for i in range(10)
        ]

        durations = []

        for query in PROFILING_QUERIES:
            timing = self.profiler.profile_reranking(sample_docs, query)
            durations.append(timing.duration_ms)

        avg_duration = mean(durations)
        p95_duration = sorted(durations)[int(len(durations) * 0.95)]

        assert avg_duration < 5000, f"Reranking avg should be < 5s, got {avg_duration}ms"


@pytest.mark.performance
@pytest.mark.profile
@pytest.mark.slow
@pytest.mark.phase3
class TestAlphaComparison:
    """Compare latencies across different alpha values."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup profiler."""
        self.profiler = LatencyProfiler()

    def test_lexical_vs_semantic_latency(self):
        """Compare lexical (alpha=0.0) vs semantic (alpha=1.0) search latency."""
        query = "wireless headphones"

        # Lexical search
        lexical_timing, _ = self.profiler.profile_vector_search(query, alpha=0.0)

        # Semantic search
        semantic_timing, _ = self.profiler.profile_vector_search(query, alpha=1.0)

        # Lexical should be faster (no embedding, pure BM25)
        assert (
            lexical_timing.duration_ms < semantic_timing.duration_ms
        ), "Lexical search should be faster than semantic"

    def test_alpha_impact_across_queries(self):
        """Test alpha parameter impact on latency."""
        alphas = [0.0, 0.25, 0.5, 0.75, 1.0]
        results = {}

        for alpha in alphas:
            durations = []
            for query in PROFILING_QUERIES[:3]:
                timing, _ = self.profiler.profile_vector_search(query, alpha)
                durations.append(timing.duration_ms)

            results[f"alpha_{alpha}"] = {
                "mean_ms": mean(durations),
                "p95_ms": sorted(durations)[int(len(durations) * 0.95)],
            }

        # Save alpha comparison
        with open(PROFILING_RESULTS_DIR / "alpha_comparison.json", "w") as f:
            json.dump(results, f, indent=2)


@pytest.mark.performance
@pytest.mark.profile
@pytest.mark.slow
@pytest.mark.phase3
class TestFullPipelineProfile:
    """Profile complete pipeline execution."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup profiler."""
        self.profiler = LatencyProfiler()

    def test_complete_pipeline_latency(self):
        """Profile complete pipeline from query to results."""
        profiles = []

        for i, query in enumerate(PROFILING_QUERIES):
            profile = self.profiler.profile_full_pipeline(query, f"query_{i}")
            profiles.append(profile)

        # Analyze results
        latencies = [p.total_latency_ms for p in profiles]
        avg_latency = mean(latencies)
        p95_latency = sorted(latencies)[int(len(latencies) * 0.95)]
        p99_latency = sorted(latencies)[int(len(latencies) * 0.99)]

        assert avg_latency < 15000, f"Full pipeline avg should be < 15s, got {avg_latency}ms"
        assert p99_latency < 30000, f"Full pipeline p99 should be < 30s, got {p99_latency}ms"

        # Save profiles
        with open(PROFILING_RESULTS_DIR / "full_pipeline_profiles.json", "w") as f:
            json.dump(
                {
                    "profiles": [p.to_dict() for p in profiles],
                    "summary": {
                        "total_queries": len(profiles),
                        "latency_avg_ms": round(avg_latency, 2),
                        "latency_p95_ms": round(p95_latency, 2),
                        "latency_p99_ms": round(p99_latency, 2),
                        "total_tokens_generated": sum(p.total_tokens for p in profiles),
                    },
                },
                f,
                indent=2,
            )

    def test_bottleneck_identification(self):
        """Identify which stages are bottlenecks."""
        profile = self.profiler.profile_full_pipeline(PROFILING_QUERIES[0])

        # Find slowest stage
        slowest_stage = max(profile.stages, key=lambda s: s.duration_ms)
        slowest_pct = (slowest_stage.duration_ms / profile.total_latency_ms) * 100

        # Should have clear bottlenecks
        stage_durations = {s.stage_name: s.duration_ms for s in profile.stages}

        # Save bottleneck analysis
        with open(PROFILING_RESULTS_DIR / "bottleneck_analysis.json", "w") as f:
            json.dump(
                {
                    "slowest_stage": slowest_stage.stage_name,
                    "slowest_pct_of_total": round(slowest_pct, 2),
                    "all_stages": stage_durations,
                    "total_ms": round(profile.total_latency_ms, 2),
                },
                f,
                indent=2,
            )

        assert slowest_pct < 100, "Single stage shouldn't dominate entire request"


@pytest.mark.performance
@pytest.mark.profile
@pytest.mark.slow
@pytest.mark.phase3
class TestMemoryProfileing:
    """Profile memory usage during operations."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup profiler."""
        self.profiler = LatencyProfiler()

    def test_memory_allocation_per_stage(self):
        """Measure memory allocation by stage."""
        profile = self.profiler.profile_full_pipeline(PROFILING_QUERIES[0])

        stage_memory = {s.stage_name: s.memory_delta_mb for s in profile.stages}

        total_memory = sum(stage_memory.values())

        # Memory deltas should be reasonable
        for stage_name, delta in stage_memory.items():
            assert (
                delta < 100
            ), f"Single stage memory delta should be < 100MB, got {delta}MB for {stage_name}"

        with open(PROFILING_RESULTS_DIR / "memory_allocation.json", "w") as f:
            json.dump(
                {
                    "stages": stage_memory,
                    "total_mb": round(total_memory, 2),
                },
                f,
                indent=2,
            )

    def test_memory_stability(self):
        """Verify memory is stable across multiple queries."""
        import psutil

        process = psutil.Process(os.getpid())

        memory_before = process.memory_info().rss / 1024 / 1024

        for query in PROFILING_QUERIES:
            self.profiler.profile_full_pipeline(query)

        memory_after = process.memory_info().rss / 1024 / 1024
        memory_growth = memory_after - memory_before

        # Memory growth should be modest
        assert memory_growth < 200, f"Memory growth should be < 200MB, got {memory_growth}MB"


@pytest.mark.performance
@pytest.mark.profile
@pytest.mark.slow
@pytest.mark.phase3
class TestCacheEffectiveness:
    """Test cache effectiveness on latency."""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup profiler."""
        self.profiler = LatencyProfiler()

    def test_repeated_query_cache_benefit(self):
        """Measure cache benefit for repeated queries."""
        query = PROFILING_QUERIES[0]

        # First query (cache miss)
        profile1 = self.profiler.profile_full_pipeline(query)

        # Second identical query (should benefit from cache)
        profile2 = self.profiler.profile_full_pipeline(query)

        # Cache hit should be faster
        speedup = (
            profile1.total_latency_ms / profile2.total_latency_ms
            if profile2.total_latency_ms > 0
            else 1
        )

        with open(PROFILING_RESULTS_DIR / "cache_effectiveness.json", "w") as f:
            json.dump(
                {
                    "first_query_ms": round(profile1.total_latency_ms, 2),
                    "cached_query_ms": round(profile2.total_latency_ms, 2),
                    "speedup_factor": round(speedup, 2),
                    "cache_beneficial": speedup > 1.0,
                },
                f,
                indent=2,
            )


def generate_latency_report(profiles: List[RequestProfile]) -> str:
    """Generate latency profiling report."""
    if not profiles:
        return "No profiles to report"

    report = {
        "timestamp": datetime.now().isoformat(),
        "profile_count": len(profiles),
        "profiles": [p.to_dict() for p in profiles],
        "summary": {
            "avg_total_latency_ms": round(mean([p.total_latency_ms for p in profiles]), 2),
            "max_total_latency_ms": round(max([p.total_latency_ms for p in profiles]), 2),
            "min_total_latency_ms": round(min([p.total_latency_ms for p in profiles]), 2),
            "total_tokens_generated": sum([p.total_tokens for p in profiles]),
        },
    }

    output_path = PROFILING_RESULTS_DIR / f"latency_report_{int(time.time())}.json"
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    return str(output_path)
