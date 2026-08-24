#!/usr/bin/env python3
"""
Benchmark Harness for Agentic Hybrid Search

Unified harness for running all performance tests and generating reports:
- Run all performance, load, stress, and profiling tests
- Compare against baseline metrics
- Detect performance regressions (> 10% slowdown)
- Generate HTML reports with visualizations
- Store baseline metrics for trend analysis
- Integration with CI/CD for automated benchmark tracking

Usage:
    # Run all benchmarks
    python -m benchmark.benchmark_harness --all

    # Run specific test class
    python -m benchmark.benchmark_harness --test TestLoadPerformance

    # Compare against baseline
    python -m benchmark.benchmark_harness --compare-baseline

    # Generate report
    python -m benchmark.benchmark_harness --report
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from statistics import mean
from typing import Any, Dict, List, Optional

# Results directory
RESULTS_DIR = Path(__file__).parent.parent / "tests" / "performance_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

BASELINE_FILE = RESULTS_DIR / "baseline.json"
CURRENT_RUN = RESULTS_DIR / f"run_{int(time.time())}.json"


class BenchmarkRunner:
    """Run benchmark suites and collect results."""

    def __init__(self, results_dir: Path = RESULTS_DIR):
        self.results_dir = results_dir
        self.results: Dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "tests": {},
            "summary": {},
        }

    def run_pytest_suite(self, marker: str, test_class: Optional[str] = None) -> bool:
        """
        Run pytest with specific marker.

        Args:
            marker: pytest marker (e.g., 'performance', 'load', 'stress', 'profile')
            test_class: Optional specific test class to run

        Returns:
            True if all tests passed
        """
        cmd = [
            "python",
            "-m",
            "pytest",
            "-v",
            f"-m {marker}",
            "--tb=short",
            "--json-report",
            f"--json-report-file={self.results_dir}/report_{marker}.json",
        ]

        if test_class:
            cmd.append(f"tests/e2e/{test_class}")
        else:
            cmd.append("tests/e2e/")

        print(f"Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, cwd=Path(__file__).parent.parent, capture_output=True)

        success = result.returncode == 0
        print(f"{'✓' if success else '✗'} {marker} tests {'passed' if success else 'FAILED'}")

        return success

    def run_all_benchmarks(self) -> Dict[str, bool]:
        """Run all benchmark suites."""
        markers = [
            ("performance", "Overall performance"),
            ("load", "Load tests"),
            ("stress", "Stress tests"),
            ("profile", "Profiling tests"),
        ]

        results = {}

        for marker, description in markers:
            print(f"\n{'=' * 60}")
            print(f"Running {description}...")
            print("=" * 60)

            try:
                success = self.run_pytest_suite(marker)
                results[marker] = success
            except Exception as e:
                print(f"Error running {marker}: {e}")
                results[marker] = False

        return results

    def collect_metrics(self) -> Dict[str, Any]:
        """Collect metrics from test result files."""
        metrics = {}

        # Look for JSON result files
        for result_file in self.results_dir.glob("report_*.json"):
            marker = result_file.stem.replace("report_", "")

            try:
                with open(result_file) as f:
                    data = json.load(f)
                    metrics[marker] = {
                        "passed": data.get("summary", {}).get("passed", 0),
                        "failed": data.get("summary", {}).get("failed", 0),
                        "duration": data.get("duration", 0),
                    }
            except Exception as e:
                print(f"Error reading {result_file}: {e}")

        return metrics

    def compare_against_baseline(self) -> Dict[str, Any]:
        """Compare current run against baseline."""
        if not BASELINE_FILE.exists():
            print(f"No baseline found at {BASELINE_FILE}")
            return {"status": "no_baseline"}

        with open(BASELINE_FILE) as f:
            baseline = json.load(f)

        current_metrics = self.collect_metrics()

        comparisons = {}

        for test_name, baseline_value in baseline.items():
            current_value = current_metrics.get(test_name)

            if not current_value:
                comparisons[test_name] = {"status": "missing"}
                continue

            if isinstance(baseline_value, (int, float)) and isinstance(current_value, (int, float)):
                delta = current_value - baseline_value
                pct_change = (delta / baseline_value * 100) if baseline_value != 0 else 0

                status = "pass"
                if pct_change > 10:  # 10% regression threshold
                    status = "regression"
                elif pct_change < -5:  # 5% improvement
                    status = "improvement"

                comparisons[test_name] = {
                    "status": status,
                    "baseline": baseline_value,
                    "current": current_value,
                    "delta": delta,
                    "pct_change": round(pct_change, 2),
                }

        return {
            "status": "compared",
            "results": comparisons,
            "passed": all(r.get("status") != "regression" for r in comparisons.values()),
        }

    def generate_html_report(self) -> str:
        """Generate HTML report with visualizations."""
        metrics = self.collect_metrics()

        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Agentic Hybrid Search - Performance Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; background: #f5f5f5; }}
        .container {{ max-width: 1200px; margin: 0 auto; background: white; padding: 20px; border-radius: 8px; }}
        h1 {{ color: #333; border-bottom: 2px solid #2196F3; padding-bottom: 10px; }}
        h2 {{ color: #666; margin-top: 30px; }}
        .metric {{ margin: 20px 0; padding: 15px; background: #f9f9f9; border-left: 4px solid #2196F3; }}
        .metric-value {{ font-size: 24px; font-weight: bold; color: #2196F3; }}
        .metric-label {{ font-size: 14px; color: #666; margin-top: 5px; }}
        .passed {{ color: #4CAF50; }}
        .failed {{ color: #f44336; }}
        table {{ width: 100%; border-collapse: collapse; margin: 20px 0; }}
        th {{ background: #f0f0f0; padding: 10px; text-align: left; border-bottom: 2px solid #ddd; }}
        td {{ padding: 10px; border-bottom: 1px solid #ddd; }}
        tr:hover {{ background: #f9f9f9; }}
        .summary {{ background: #e3f2fd; padding: 20px; border-radius: 4px; margin: 20px 0; }}
        .timestamp {{ color: #999; font-size: 12px; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Agentic Hybrid Search - Performance Report</h1>
        <p class="timestamp">Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>

        <div class="summary">
            <h2>Summary</h2>
            <p>Benchmark Results for All Performance Test Categories</p>
            <table>
                <tr>
                    <th>Test Category</th>
                    <th>Passed</th>
                    <th>Failed</th>
                    <th>Duration (s)</th>
                </tr>
"""

        total_passed = 0
        total_failed = 0
        total_duration = 0

        for marker, data in metrics.items():
            passed = data.get("passed", 0)
            failed = data.get("failed", 0)
            duration = data.get("duration", 0)

            total_passed += passed
            total_failed += failed
            total_duration += duration

            status_class = "passed" if failed == 0 else "failed"

            html += f"""
                <tr>
                    <td>{marker}</td>
                    <td class="{status_class}">{passed}</td>
                    <td class="{status_class}">{failed}</td>
                    <td>{duration:.2f}</td>
                </tr>
"""

        html += f"""
            </table>
            <div class="metric">
                <div class="metric-value">{total_passed}</div>
                <div class="metric-label">Total Tests Passed</div>
            </div>
            <div class="metric">
                <div class="metric-value">{total_failed}</div>
                <div class="metric-label">Total Tests Failed</div>
            </div>
        </div>

        <h2>Metrics Details</h2>
"""

        for marker, data in metrics.items():
            html += f"""
        <div class="metric">
            <strong>{marker.upper()}</strong>
            <div style="margin-top: 10px;">
                <div>Passed: <strong>{data.get('passed', 0)}</strong></div>
                <div>Failed: <strong>{data.get('failed', 0)}</strong></div>
                <div>Duration: <strong>{data.get('duration', 0):.2f}s</strong></div>
            </div>
        </div>
"""

        html += """
    </div>
</body>
</html>
"""

        output_file = self.results_dir / f"report_{int(time.time())}.html"
        with open(output_file, "w") as f:
            f.write(html)

        return str(output_file)

    def save_baseline(self, metrics: Dict[str, Any]):
        """Save current metrics as new baseline."""
        with open(BASELINE_FILE, "w") as f:
            json.dump(metrics, f, indent=2)
        print(f"Baseline saved to {BASELINE_FILE}")

    def save_results(self):
        """Save benchmark results."""
        with open(CURRENT_RUN, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"Results saved to {CURRENT_RUN}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark harness for Agentic Hybrid Search")
    parser.add_argument("--all", action="store_true", help="Run all benchmark suites")
    parser.add_argument("--performance", action="store_true", help="Run performance tests only")
    parser.add_argument("--load", action="store_true", help="Run load tests only")
    parser.add_argument("--stress", action="store_true", help="Run stress tests only")
    parser.add_argument("--profile", action="store_true", help="Run profiling tests only")
    parser.add_argument("--test", help="Run specific test class")
    parser.add_argument("--compare-baseline", action="store_true", help="Compare against baseline")
    parser.add_argument("--report", action="store_true", help="Generate HTML report")
    parser.add_argument("--save-baseline", action="store_true", help="Save current run as baseline")

    args = parser.parse_args()

    runner = BenchmarkRunner()

    if args.all:
        print("Running all benchmarks...")
        results = runner.run_all_benchmarks()
        runner.save_results()

    elif args.performance:
        runner.run_pytest_suite("performance")
    elif args.load:
        runner.run_pytest_suite("load")
    elif args.stress:
        runner.run_pytest_suite("stress")
    elif args.profile:
        runner.run_pytest_suite("profile")
    elif args.test:
        runner.run_pytest_suite("performance", args.test)

    if args.compare_baseline:
        comparison = runner.compare_against_baseline()
        print("\nBaseline Comparison:")
        print(json.dumps(comparison, indent=2))

        if not comparison.get("passed"):
            print("\n⚠ Performance regression detected!")
            return 1

    if args.report:
        report_file = runner.generate_html_report()
        print(f"\nHTML report generated: {report_file}")

    if args.save_baseline:
        metrics = runner.collect_metrics()
        runner.save_baseline(metrics)

    return 0


if __name__ == "__main__":
    sys.exit(main())
