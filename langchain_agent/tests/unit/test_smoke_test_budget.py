"""Pre-flight guard: the workflow's per-test pytest --timeout for smoke
tests must be greater than the worst-case wall-clock cost of any single
test, computed from the test source.

Catches the 2026-04-29 smoke failure where the refinement test sent two
sequential chat messages (~16-22 s each on Cloud Run) under
`pytest --timeout=30`, guaranteeing a timeout on every deploy.

Heuristic budget per test:
  budget = SETUP_OVERHEAD
         + (chat_message_sends * PER_CHAT_MESSAGE_BUDGET)
         + (other_websocket_recv_calls * PER_RECV_BUDGET_CAP)

We over-estimate so the assertion has slack; if the workflow's
--timeout is below this, the test will time out under realistic Cloud
Run latency (16-25 s per chat message + reranker silence).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "build-deploy.yml"
SMOKE_TEST_FILE = REPO_ROOT / "langchain_agent" / "tests" / "e2e" / "test_deployment_smoke.py"
CLOUD_RUN_TEST_FILE = (
    REPO_ROOT / "langchain_agent" / "tests" / "e2e" / "test_cloud_run_deployment.py"
)
DATA_TEST_FILE = REPO_ROOT / "langchain_agent" / "tests" / "e2e" / "test_deployment_data.py"

# Realistic Cloud Run cost multipliers, derived from 2026-04-29 production
# logs (Gemini 3 Flash + reranker scoring 40 docs + network).
# Setup includes: POST /api/auth/login round-trip (cookie acquisition for the
# login gate) + ws_connect + connection_established.
SETUP_OVERHEAD_S = 7  # login round-trip + ws_connect + connection_established
PER_CHAT_MESSAGE_BUDGET_S = 40  # cross-encoder on 40 docs: 30-37s observed
PER_RECV_BUDGET_CAP_S = 15  # cap on inner asyncio.wait_for timeouts


def _count_chat_message_sends(source: str) -> int:
    """Count `websocket.send(json.dumps({...'type': 'chat_message'...}))`
    calls. Each one represents a full pipeline round-trip on Cloud Run."""
    tree = ast.parse(source)
    sends = 0
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "dumps"
            and node.args
            and isinstance(node.args[0], ast.Dict)
        ):
            for k, v in zip(node.args[0].keys, node.args[0].values):
                if (
                    isinstance(k, ast.Constant)
                    and k.value == "type"
                    and isinstance(v, ast.Constant)
                    and v.value == "chat_message"
                ):
                    sends += 1
    return sends


def _count_chat_message_sends_per_test(source: str) -> dict[str, int]:
    """Per-async-test-method counts of chat_message sends."""
    tree = ast.parse(source)
    out: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            if not node.name.startswith("test_"):
                continue
            # Count chat_message json.dumps under this function
            count = 0
            for sub in ast.walk(node):
                if (
                    isinstance(sub, ast.Call)
                    and isinstance(sub.func, ast.Attribute)
                    and sub.func.attr == "dumps"
                    and sub.args
                    and isinstance(sub.args[0], ast.Dict)
                ):
                    for k, v in zip(sub.args[0].keys, sub.args[0].values):
                        if (
                            isinstance(k, ast.Constant)
                            and k.value == "type"
                            and isinstance(v, ast.Constant)
                            and v.value == "chat_message"
                        ):
                            count += 1
            if count > 0:
                out[node.name] = count
    return out


def _extract_workflow_timeout(workflow_src: str, test_filename: str) -> int | None:
    """Find the --timeout=N flag on the pytest invocation that runs
    `tests/e2e/<test_filename>`.

    Returns None if the test is not invoked from the workflow.
    """
    # Find the run block that mentions the test file, then read its --timeout flag.
    pattern = (
        rf"pytest\s+tests/e2e/{re.escape(test_filename)}\s*\\?\s*"
        r"(?:[^\n]*\n)*?\s*--timeout=(\d+)"
    )
    match = re.search(pattern, workflow_src)
    if match:
        return int(match.group(1))
    return None


@pytest.mark.unit
@pytest.mark.parametrize(
    "test_file",
    [
        SMOKE_TEST_FILE,
        CLOUD_RUN_TEST_FILE,
        DATA_TEST_FILE,
    ],
    ids=lambda p: p.name,
)
def test_workflow_timeout_covers_worst_case_test_budget(test_file: Path) -> None:
    """For every smoke-test file referenced by build-deploy.yml, the
    pytest --timeout on its invocation must cover the worst-case
    chat_message-send budget computed from the test source."""
    if not test_file.exists():
        pytest.skip(f"{test_file.name} not present")

    workflow_src = WORKFLOW.read_text()
    timeout = _extract_workflow_timeout(workflow_src, test_file.name)

    if timeout is None:
        pytest.skip(f"{test_file.name} is not invoked from build-deploy.yml")

    per_test = _count_chat_message_sends_per_test(test_file.read_text())
    if not per_test:
        pytest.skip(f"{test_file.name} has no chat_message sends")

    worst_test, worst_count = max(per_test.items(), key=lambda kv: kv[1])
    worst_budget = SETUP_OVERHEAD_S + worst_count * PER_CHAT_MESSAGE_BUDGET_S

    assert timeout >= worst_budget, (
        f"{test_file.name}: pytest --timeout={timeout}s in build-deploy.yml is "
        f"too tight for worst-case test {worst_test!r} (sends {worst_count} "
        f"chat_message payloads → estimated {worst_budget}s on Cloud Run "
        f"@ {PER_CHAT_MESSAGE_BUDGET_S}s/message + {SETUP_OVERHEAD_S}s setup). "
        "Bump --timeout in .github/workflows/build-deploy.yml or split the test."
    )


@pytest.mark.unit
def test_inner_recv_timeout_consistent_with_pytest_timeout() -> None:
    """Inner `asyncio.wait_for(websocket.recv(), timeout=N)` must be <= the
    workflow's pytest --timeout for the smoke test file. If a single recv
    can wait longer than the whole test budget, the test will hit
    pytest-timeout before any meaningful failure mode surfaces.
    """
    workflow_src = WORKFLOW.read_text()
    timeout = _extract_workflow_timeout(workflow_src, SMOKE_TEST_FILE.name)
    if timeout is None:
        pytest.skip("smoke test not invoked from build-deploy.yml")

    src = SMOKE_TEST_FILE.read_text()
    # Match `asyncio.wait_for(<anything>, timeout=N)` allowing the first
    # argument to contain its own parentheses (e.g. `websocket.recv()`).
    inner_timeouts = [
        int(m) for m in re.findall(r"asyncio\.wait_for\(.+?,\s*timeout=(\d+)\s*\)", src, re.DOTALL)
    ]
    assert inner_timeouts, "expected at least one asyncio.wait_for(..., timeout=N)"

    worst_recv = max(inner_timeouts)
    assert worst_recv <= timeout, (
        f"asyncio.wait_for has timeout={worst_recv}s but pytest "
        f"--timeout={timeout}s — inner recv could outlive the test budget."
    )


@pytest.mark.unit
def test_websocket_timeout_constant_is_realistic() -> None:
    """The module-level WEBSOCKET_TIMEOUT in the smoke test file must be
    long enough for a single Cloud Run pipeline round-trip
    (>= PER_CHAT_MESSAGE_BUDGET_S) so the outer event-collection while-loop
    can actually catch agent_complete on the slow path.
    """
    src = SMOKE_TEST_FILE.read_text()
    match = re.search(r"^WEBSOCKET_TIMEOUT\s*=\s*(\d+)", src, re.MULTILINE)
    assert match, "WEBSOCKET_TIMEOUT not found in smoke test file"
    value = int(match.group(1))
    assert value >= PER_CHAT_MESSAGE_BUDGET_S, (
        f"WEBSOCKET_TIMEOUT={value}s is below the realistic per-message "
        f"budget of {PER_CHAT_MESSAGE_BUDGET_S}s — outer loop will exit "
        "before agent_complete arrives on slow Cloud Run runs."
    )
