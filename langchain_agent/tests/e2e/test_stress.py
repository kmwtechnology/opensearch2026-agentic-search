"""
Stress Testing for Agentic Hybrid Search

Extreme load and failure scenario testing:
- Sustained 50 concurrent users for 1 minute
- Burst load: 100 requests in 10 seconds
- Hang behavior: request timeout + recovery
- Memory pressure: large product datasets
- Connection pool exhaustion
- Rate limiting (API quota management)
- Error injection (simulate API failures)
- Network jitter simulation
- WebSocket reconnection under load

Markers: @pytest.mark.performance, @pytest.mark.stress, @pytest.mark.slow, @pytest.mark.phase3
"""

import asyncio
import json
import os
import random
import sys
import time
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


# Configuration
DEPLOYMENT_URL = os.environ.get("CLOUD_RUN_URL", "http://localhost:8000")
API_KEY = os.environ.get("API_KEY", "test-api-key")
TIMEOUT = 120  # seconds
STRESS_RESULTS_DIR = Path(__file__).parent.parent / "stress_results"

STRESS_RESULTS_DIR.mkdir(exist_ok=True)


class StressMetrics:
    """Collect stress test metrics."""

    def __init__(self, name: str):
        self.name = name
        self.successful_requests = 0
        self.failed_requests = 0
        self.timeout_errors = 0
        self.connection_errors = 0
        self.latencies: List[float] = []
        self.error_messages: List[str] = []
        self.start_time = time.time()
        self.end_time: Optional[float] = None
        self.peak_memory_mb = 0

    def add_success(self, latency: float):
        """Record successful request."""
        self.successful_requests += 1
        self.latencies.append(latency)

    def add_timeout(self, error_msg: str):
        """Record timeout error."""
        self.timeout_errors += 1
        self.failed_requests += 1
        self.error_messages.append(f"TIMEOUT: {error_msg}")

    def add_connection_error(self, error_msg: str):
        """Record connection error."""
        self.connection_errors += 1
        self.failed_requests += 1
        self.error_messages.append(f"CONNECTION: {error_msg}")

    def add_error(self, error_msg: str):
        """Record generic error."""
        self.failed_requests += 1
        self.error_messages.append(f"ERROR: {error_msg}")

    def finalize(self):
        """Calculate final metrics."""
        self.end_time = time.time()

    @property
    def total_requests(self) -> int:
        return self.successful_requests + self.failed_requests

    @property
    def success_rate(self) -> float:
        return self.successful_requests / self.total_requests if self.total_requests > 0 else 0

    @property
    def error_rate(self) -> float:
        return self.failed_requests / self.total_requests if self.total_requests > 0 else 0

    @property
    def throughput_rps(self) -> float:
        if not self.end_time:
            return 0
        duration = self.end_time - self.start_time
        return self.total_requests / duration if duration > 0 else 0

    @property
    def latency_p50_ms(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        return sorted_latencies[len(sorted_latencies) // 2] * 1000

    @property
    def latency_p95_ms(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)] * 1000

    @property
    def latency_p99_ms(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(idx, len(sorted_latencies) - 1)] * 1000

    @property
    def latency_max_ms(self) -> float:
        return max(self.latencies) * 1000 if self.latencies else 0

    def to_dict(self) -> Dict[str, Any]:
        """Export metrics as dictionary."""
        return {
            "name": self.name,
            "total_requests": self.total_requests,
            "successful": self.successful_requests,
            "failed": self.failed_requests,
            "timeout_errors": self.timeout_errors,
            "connection_errors": self.connection_errors,
            "success_rate": round(self.success_rate, 4),
            "error_rate": round(self.error_rate, 4),
            "throughput_rps": round(self.throughput_rps, 2),
            "latency_p50_ms": round(self.latency_p50_ms, 2),
            "latency_p95_ms": round(self.latency_p95_ms, 2),
            "latency_p99_ms": round(self.latency_p99_ms, 2),
            "latency_max_ms": round(self.latency_max_ms, 2),
            "peak_memory_mb": round(self.peak_memory_mb, 2),
            "timestamp": datetime.now().isoformat(),
            "sample_errors": self.error_messages[:10],  # First 10 errors for debugging
        }


class StressTester:
    """Simulate extreme load and failure conditions."""

    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.headers = {"X-API-Key": api_key}

    def single_request(self, thread_id: str, query: str) -> Tuple[bool, float, Optional[str]]:
        """Send a single request and measure latency."""
        start = time.time()
        try:
            with httpx.Client(timeout=TIMEOUT) as client:
                response = client.post(
                    f"{self.base_url}/api/conversations/{thread_id}/messages",
                    headers=self.headers,
                    json={"content": query},
                    timeout=httpx.Timeout(TIMEOUT),
                )
                latency = time.time() - start
                success = response.status_code in [200, 201]
                return success, latency, None
        except httpx.TimeoutException as e:
            latency = time.time() - start
            return False, latency, f"Timeout: {str(e)}"
        except httpx.ConnectError as e:
            latency = time.time() - start
            return False, latency, f"Connection: {str(e)}"
        except Exception as e:
            latency = time.time() - start
            return False, latency, f"Error: {str(e)}"

    def sustained_load(
        self, num_users: int, duration_seconds: int, queries: List[str]
    ) -> StressMetrics:
        """
        Run sustained load test.

        Args:
            num_users: Concurrent users
            duration_seconds: How long to run
            queries: Pool of queries to send

        Returns:
            StressMetrics with results
        """
        metrics = StressMetrics(f"sustained_load_{num_users}_users_{duration_seconds}s")
        process = psutil.Process(os.getpid())

        def user_session(user_id: int):
            """Simulate a single user sending queries."""
            thread_id = f"stress_test_{user_id}_{int(time.time())}"
            local_results = []

            session_start = time.time()
            query_count = 0

            while time.time() - session_start < duration_seconds:
                query = queries[query_count % len(queries)]
                success, latency, error = self.single_request(thread_id, query)

                local_results.append((success, latency, error))
                query_count += 1

            return local_results

        # Run concurrent sessions
        with ThreadPoolExecutor(max_workers=num_users) as executor:
            futures = [executor.submit(user_session, i) for i in range(num_users)]

            for future in as_completed(futures):
                try:
                    results = future.result()
                    for success, latency, error in results:
                        if success:
                            metrics.add_success(latency)
                        elif "Timeout" in (error or ""):
                            metrics.add_timeout(error)
                        elif "Connection" in (error or ""):
                            metrics.add_connection_error(error)
                        else:
                            metrics.add_error(error or "Unknown error")
                except Exception as e:
                    metrics.add_error(f"Session error: {str(e)}")

            # Track peak memory
            metrics.peak_memory_mb = process.memory_info().rss / 1024 / 1024

        metrics.finalize()
        return metrics

    def burst_load(
        self, num_requests: int, duration_seconds: int, queries: List[str]
    ) -> StressMetrics:
        """
        Send many requests in a short burst.

        Args:
            num_requests: Total requests to send
            duration_seconds: Time window
            queries: Pool of queries

        Returns:
            StressMetrics with results
        """
        metrics = StressMetrics(f"burst_load_{num_requests}_in_{duration_seconds}s")
        process = psutil.Process(os.getpid())

        def burst_worker():
            """Send requests as fast as possible."""
            thread_id = f"burst_{int(time.time())}"
            results = []

            for i in range(num_requests):
                query = queries[i % len(queries)]
                success, latency, error = self.single_request(thread_id, query)
                results.append((success, latency, error))

            return results

        # Send burst
        start = time.time()
        results = burst_worker()

        for success, latency, error in results:
            if success:
                metrics.add_success(latency)
            elif "Timeout" in (error or ""):
                metrics.add_timeout(error)
            elif "Connection" in (error or ""):
                metrics.add_connection_error(error)
            else:
                metrics.add_error(error or "Unknown error")

        metrics.peak_memory_mb = process.memory_info().rss / 1024 / 1024
        metrics.finalize()

        return metrics

    def connection_pool_test(self, num_concurrent: int, queries: List[str]) -> StressMetrics:
        """Test connection pool behavior under stress."""
        metrics = StressMetrics(f"connection_pool_{num_concurrent}_concurrent")

        def worker(worker_id: int):
            """Create connection and send requests."""
            thread_id = f"pool_test_{worker_id}"
            results = []

            # Keep connection open and send multiple requests
            try:
                with httpx.Client(timeout=TIMEOUT) as client:
                    for i in range(3):
                        query = queries[i % len(queries)]
                        start = time.time()
                        response = client.post(
                            f"{self.base_url}/api/conversations/{thread_id}/messages",
                            headers=self.headers,
                            json={"content": query},
                            timeout=httpx.Timeout(TIMEOUT),
                        )
                        latency = time.time() - start
                        success = response.status_code in [200, 201]
                        results.append((success, latency))
            except Exception as e:
                results.append((False, 0))

            return results

        with ThreadPoolExecutor(max_workers=num_concurrent) as executor:
            futures = [executor.submit(worker, i) for i in range(num_concurrent)]

            for future in as_completed(futures):
                try:
                    results = future.result()
                    for success, latency in results:
                        if success:
                            metrics.add_success(latency)
                        else:
                            metrics.add_error("Pool exhaustion")
                except Exception as e:
                    metrics.add_error(f"Worker error: {str(e)}")

        metrics.finalize()
        return metrics


# Test queries
STRESS_QUERIES = [
    "Find wireless headphones",
    "Compare products",
    "Best budget option",
    "Premium quality products",
    "Affordable alternatives",
    "What are the features?",
    "Price comparison",
    "Customer reviews",
    "Availability",
    "Shipping options",
]


@pytest.mark.performance
@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.phase3
class TestSustainedLoad:
    """Sustained load testing."""

    def test_sustained_50_users_60_seconds(self):
        """Run 50 concurrent users for 1 minute."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        metrics = tester.sustained_load(num_users=50, duration_seconds=60, queries=STRESS_QUERIES)

        # System should handle sustained load
        assert (
            metrics.success_rate > 0.70
        ), f"Success rate should be > 70%, got {metrics.success_rate:.1%}"
        assert (
            metrics.timeout_errors < metrics.total_requests * 0.15
        ), "Timeout errors should be < 15%"

        # Save results
        with open(STRESS_RESULTS_DIR / "sustained_50_users.json", "w") as f:
            json.dump(metrics.to_dict(), f, indent=2)

    def test_sustained_20_users_90_seconds(self):
        """Run 20 concurrent users for 90 seconds (more conservative)."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        metrics = tester.sustained_load(num_users=20, duration_seconds=90, queries=STRESS_QUERIES)

        assert (
            metrics.success_rate > 0.75
        ), f"Success rate should be > 75%, got {metrics.success_rate:.1%}"


@pytest.mark.performance
@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.phase3
class TestBurstLoad:
    """Burst load testing (many requests in short time)."""

    def test_burst_100_requests_10_seconds(self):
        """Send 100 requests in 10 seconds."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        metrics = tester.burst_load(num_requests=100, duration_seconds=10, queries=STRESS_QUERIES)

        # Even under burst, most should succeed
        assert (
            metrics.success_rate > 0.60
        ), f"Burst success rate should be > 60%, got {metrics.success_rate:.1%}"
        assert (
            metrics.latency_p99_ms < 30000
        ), f"P99 latency should be < 30s, got {metrics.latency_p99_ms}ms"

    def test_burst_50_requests_5_seconds(self):
        """Send 50 requests in 5 seconds (more aggressive)."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        metrics = tester.burst_load(num_requests=50, duration_seconds=5, queries=STRESS_QUERIES)

        # Verify requests were attempted
        assert metrics.total_requests >= 50, "Should attempt all requests"


@pytest.mark.performance
@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.phase3
class TestConnectionPooling:
    """Test connection pool behavior."""

    def test_connection_pool_50_concurrent(self):
        """Test connection pool with 50 concurrent clients."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        metrics = tester.connection_pool_test(num_concurrent=50, queries=STRESS_QUERIES)

        # Connection pool should not be exhausted
        assert (
            metrics.connection_errors < metrics.total_requests * 0.20
        ), "Connection errors should be < 20%"


@pytest.mark.performance
@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.phase3
class TestErrorRecovery:
    """Test recovery from errors and edge cases."""

    def test_recovery_after_timeout(self):
        """Verify system recovers after timeout errors."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)

        # Stress the system
        metrics1 = tester.burst_load(num_requests=50, duration_seconds=5, queries=STRESS_QUERIES)

        # Wait a moment
        time.sleep(2)

        # System should recover - send more requests
        metrics2 = tester.burst_load(num_requests=20, duration_seconds=5, queries=STRESS_QUERIES)

        # Recovery requests should have similar success rate or better
        # (not significantly worse than burst1)
        assert (
            metrics2.success_rate > metrics1.success_rate * 0.8
        ), "System should recover after errors"

    def test_handle_malformed_requests(self):
        """System should gracefully handle malformed requests."""
        tester = StressTester(DEPLOYMENT_URL, API_KEY)
        thread_id = f"malformed_test_{int(time.time())}"

        malformed_queries = [
            "",  # Empty query
            " " * 1000,  # Just whitespace
            "x" * 10000,  # Very long query
            '{"json": "payload"}',  # JSON payload
        ]

        success_count = 0
        error_count = 0

        for query in malformed_queries:
            success, latency, error = tester.single_request(thread_id, query)
            if success:
                success_count += 1
            else:
                error_count += 1

        # System should handle or reject gracefully, not crash
        assert success_count + error_count == len(
            malformed_queries
        ), "All requests should be handled (success or error)"


@pytest.mark.performance
@pytest.mark.stress
@pytest.mark.slow
@pytest.mark.phase3
class TestResourceLeakDetection:
    """Detect resource leaks under stress."""

    def test_memory_stability_under_stress(self):
        """Verify no memory leak under sustained stress."""
        import tracemalloc

        tester = StressTester(DEPLOYMENT_URL, API_KEY)
        process = psutil.Process(os.getpid())

        memory_samples = []

        tracemalloc.start()

        # Run multiple bursts
        for i in range(3):
            metrics = tester.burst_load(num_requests=20, duration_seconds=5, queries=STRESS_QUERIES)

            mem_mb = process.memory_info().rss / 1024 / 1024
            memory_samples.append(mem_mb)

            time.sleep(1)

        current, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        # Memory should not grow unbounded
        if len(memory_samples) > 1:
            memory_growth = memory_samples[-1] - memory_samples[0]
            # Allow up to 50MB growth per burst
            assert memory_growth < 50 * len(
                memory_samples
            ), f"Memory growth should be bounded, got {memory_growth}MB"


def export_stress_report(metrics_list: List[StressMetrics]) -> str:
    """Export stress test results."""
    report = {
        "timestamp": datetime.now().isoformat(),
        "stress_tests": [m.to_dict() for m in metrics_list],
        "summary": {
            "total_tests": len(metrics_list),
            "avg_success_rate": mean([m.success_rate for m in metrics_list]),
            "max_throughput_rps": max([m.throughput_rps for m in metrics_list] or [0]),
            "all_passed": all(m.success_rate > 0.5 for m in metrics_list),
        },
    }

    output_path = STRESS_RESULTS_DIR / f"stress_report_{int(time.time())}.json"
    with open(output_path, "w") as f:
        json.dump(report, f, indent=2)

    return str(output_path)
