"""
Unit tests for reindex_trigger — both mechanisms and the config factory.
No network: the GitHub trigger runs against httpx.MockTransport, the local
trigger against a patched subprocess.run.
"""

import json
import subprocess
from unittest.mock import MagicMock, patch

import httpx
import pytest

from reindex_trigger import (
    GitHubActionsReindexTrigger,
    LocalReindexTrigger,
    ReindexConfigurationError,
    build_reindex_trigger,
)

REPO = "kmwtechnology/opensearch2026-agentic-search"
WORKFLOW_PAGE = f"https://github.com/{REPO}/actions/workflows/reindex.yml"
RUN_URL = f"https://github.com/{REPO}/actions/runs/123"


def _github(handler):
    return GitHubActionsReindexTrigger(
        repo=REPO,
        token="t0k",
        ref="main",
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        run_lookup_delay_seconds=0,
    )


def _runs_response(created_at):
    return httpx.Response(
        200, json={"workflow_runs": [{"html_url": RUN_URL, "created_at": created_at}]}
    )


class TestGitHubActionsReindexTrigger:
    def test_dispatch_success_returns_fresh_run_url(self):
        seen = {}

        def handler(request):
            if request.method == "POST" and request.url.path.endswith("/dispatches"):
                seen["body"] = json.loads(request.content)
                seen["headers"] = dict(request.headers)
                return httpx.Response(204)
            if request.method == "GET" and request.url.path.endswith("/runs"):
                seen["params"] = dict(request.url.params)
                return _runs_response("2999-01-01T00:00:00Z")
            return httpx.Response(404)

        outcome = _github(handler).trigger()

        assert outcome.triggered is True
        assert outcome.success is True
        assert outcome.mode == "github"
        assert outcome.run_url == RUN_URL
        assert outcome.error is None
        assert seen["body"] == {
            "ref": "main",
            "inputs": {"reset_index": "false", "reindex_judgments": "false"},
        }
        assert seen["headers"]["authorization"] == "Bearer t0k"
        assert seen["headers"]["accept"] == "application/vnd.github+json"
        assert seen["headers"]["x-github-api-version"] == "2022-11-28"
        assert seen["params"] == {"event": "workflow_dispatch", "branch": "main", "per_page": "1"}

    def test_stale_run_falls_back_to_workflow_page(self):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(204)
            return _runs_response("2000-01-01T00:00:00Z")

        outcome = _github(handler).trigger()

        assert outcome.success is True
        assert outcome.run_url == WORKFLOW_PAGE

    def test_run_lookup_failure_never_breaks_a_successful_dispatch(self):
        def handler(request):
            if request.method == "POST":
                return httpx.Response(204)
            raise httpx.ConnectError("boom", request=request)

        outcome = _github(handler).trigger()

        assert outcome.success is True
        assert outcome.run_url == WORKFLOW_PAGE

    def test_non_204_reports_failure_with_github_message(self):
        def handler(request):
            return httpx.Response(404, json={"message": "Not Found"})

        outcome = _github(handler).trigger()

        assert outcome.triggered is True
        assert outcome.success is False
        assert "404" in outcome.error
        assert "Not Found" in outcome.error
        assert outcome.run_url == WORKFLOW_PAGE

    def test_request_error_reports_failure_without_raising(self):
        def handler(request):
            raise httpx.ConnectError("boom", request=request)

        outcome = _github(handler).trigger()

        assert outcome.success is False
        assert "ConnectError" in outcome.error


class TestLocalReindexTrigger:
    @patch("subprocess.run")
    def test_parses_docs_succeeded(self, mock_run):
        result = MagicMock(returncode=0, stderr="")
        result.stdout = "esciProductsConnector: complete. 9618 docs succeeded. 0 docs failed."
        mock_run.return_value = result

        outcome = LocalReindexTrigger(timeout_seconds=1).trigger()

        assert outcome.success is True
        assert outcome.mode == "local"
        assert outcome.docs_processed == 9618
        args, kwargs = mock_run.call_args
        assert args[0] == ["bash", "scripts/lucille_ingest.sh", "--skip-judgments"]
        assert kwargs["timeout"] == 1

    @patch("subprocess.run")
    def test_nonzero_exit_reports_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="lucille error")

        outcome = LocalReindexTrigger().trigger()

        assert outcome.success is False
        assert outcome.docs_processed == 0
        assert "exited 1" in outcome.error

    @patch("subprocess.run")
    def test_timeout_reports_failure(self, mock_run):
        mock_run.side_effect = subprocess.TimeoutExpired(cmd="lucille_ingest.sh", timeout=1)

        outcome = LocalReindexTrigger(timeout_seconds=1).trigger()

        assert outcome.success is False
        assert "timed out" in outcome.error


class TestBuildReindexTrigger:
    @patch("reindex_trigger.REINDEX_TRIGGER", "local")
    def test_default_is_local(self):
        assert isinstance(build_reindex_trigger(), LocalReindexTrigger)

    @patch("reindex_trigger.GITHUB_REINDEX_TOKEN", None)
    def test_github_without_token_raises(self):
        with pytest.raises(ReindexConfigurationError, match="GITHUB_REINDEX_TOKEN"):
            build_reindex_trigger("github")

    @patch("reindex_trigger.GITHUB_REINDEX_REF", "release")
    @patch("reindex_trigger.GITHUB_REPO", "org/repo")
    @patch("reindex_trigger.GITHUB_REINDEX_TOKEN", "t0k")
    def test_github_with_token_uses_config(self):
        trigger = build_reindex_trigger("github")

        assert isinstance(trigger, GitHubActionsReindexTrigger)
        assert trigger.repo == "org/repo"
        assert trigger.ref == "release"

    def test_unknown_mode_raises(self):
        with pytest.raises(ReindexConfigurationError, match="Unknown REINDEX_TRIGGER"):
            build_reindex_trigger("carrier-pigeon")
