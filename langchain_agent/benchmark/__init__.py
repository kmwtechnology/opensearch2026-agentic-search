"""
Benchmark harness and performance testing utilities for Agentic Hybrid Search.

This package provides:
- BenchmarkRunner: Unified harness for running all performance tests
- Performance comparison against baseline
- HTML report generation
- Regression detection (> 10% slowdown)
- JSON metric storage for trend analysis
"""

from .benchmark_harness import BenchmarkRunner

__all__ = ["BenchmarkRunner"]
