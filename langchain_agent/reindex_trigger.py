"""
Reindex trigger — how the enrichment flywheel gets the catalog re-indexed
after writing a new attribute mapping. Same result, two mechanisms, chosen by
config.REINDEX_TRIGGER:

  local  -- run scripts/lucille_ingest.sh as a subprocess and wait for it
            (dev: Docker on this host, ~20s, synchronous, reports doc count).
  github -- dispatch the reindex.yml GitHub Actions workflow through the
            GitHub API and return immediately (Cloud Run: the image has no
            Docker/Lucille; the runner regenerates products.generated.conf
            from the hosted mapping store, which now contains the new
            mapping). Fire-and-forget, ~8 min; reports the run URL.
"""

import logging
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

import httpx

from config import (
    GITHUB_REINDEX_REF,
    GITHUB_REINDEX_TOKEN,
    GITHUB_REPO,
    REINDEX_LOCAL_TIMEOUT_SECONDS,
    REINDEX_TRIGGER,
)
from exceptions import ConfigurationError

logger = logging.getLogger(__name__)

LANGCHAIN_AGENT_DIR = Path(__file__).parent
GITHUB_API = "https://api.github.com"
GITHUB_API_VERSION = "2022-11-28"


class ReindexConfigurationError(ConfigurationError):
    """REINDEX_TRIGGER is misconfigured (unknown mode, or github mode without a token)."""


@dataclass
class ReindexOutcome:
    triggered: bool
    success: bool
    mode: str  # "local" | "github"
    docs_processed: int = 0
    duration_seconds: float = 0.0
    run_url: Optional[str] = None  # github mode: the dispatched run (or the workflow page)
    error: Optional[str] = None  # short, user-safe detail when success is False


class ReindexTrigger(Protocol):
    mode: str

    def trigger(self) -> ReindexOutcome: ...


class LocalReindexTrigger:
    """Run the products ingest here via scripts/lucille_ingest.sh and wait for it."""

    mode = "local"

    def __init__(
        self,
        timeout_seconds: float = REINDEX_LOCAL_TIMEOUT_SECONDS,
        cwd: Path = LANGCHAIN_AGENT_DIR,
    ):
        self.timeout_seconds = timeout_seconds
        self.cwd = cwd

    def trigger(self) -> ReindexOutcome:
        start = time.monotonic()
        try:
            result = subprocess.run(
                ["bash", "scripts/lucille_ingest.sh", "--skip-judgments"],
                cwd=self.cwd,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            logger.error("Reindex (local): timed out after %.1fs", duration)
            return ReindexOutcome(
                triggered=True,
                success=False,
                mode=self.mode,
                duration_seconds=duration,
                error=f"timed out after {duration:.0f}s",
            )

        duration = time.monotonic() - start
        if result.returncode != 0:
            logger.error(
                "Reindex (local): failed (exit %d): %s", result.returncode, result.stderr[-2000:]
            )
            return ReindexOutcome(
                triggered=True,
                success=False,
                mode=self.mode,
                duration_seconds=duration,
                error=f"lucille_ingest.sh exited {result.returncode}",
            )

        docs_processed = _parse_docs_succeeded(result.stdout)
        logger.info(
            "Reindex (local): complete, %d docs processed in %.1fs", docs_processed, duration
        )
        return ReindexOutcome(
            triggered=True,
            success=True,
            mode=self.mode,
            docs_processed=docs_processed,
            duration_seconds=duration,
        )


def _parse_docs_succeeded(lucille_output: str) -> int:
    """Extract the doc count from Lucille's 'N docs succeeded' summary line."""
    match = re.search(r"(\d+)\s+docs succeeded", lucille_output)
    return int(match.group(1)) if match else 0


class GitHubActionsReindexTrigger:
    """Dispatch reindex.yml via the GitHub API and return without waiting."""

    mode = "github"

    def __init__(
        self,
        repo: str,
        token: str,
        ref: str = "main",
        workflow: str = "reindex.yml",
        client: Optional[httpx.Client] = None,
        run_lookup_attempts: int = 3,
        run_lookup_delay_seconds: float = 2.0,
    ):
        self.repo = repo
        self.ref = ref
        self.workflow = workflow
        self.run_lookup_attempts = run_lookup_attempts
        self.run_lookup_delay_seconds = run_lookup_delay_seconds
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": GITHUB_API_VERSION,
        }
        self._client = client or httpx.Client(timeout=10.0)

    @property
    def workflow_url(self) -> str:
        return f"https://github.com/{self.repo}/actions/workflows/{self.workflow}"

    def trigger(self) -> ReindexOutcome:
        start = time.monotonic()
        dispatched_at = datetime.now(timezone.utc)
        url = f"{GITHUB_API}/repos/{self.repo}/actions/workflows/{self.workflow}/dispatches"
        # The index mapping is extended additively by enrich_attribute, so no
        # reset; judgments are untouched by a taxonomy change.
        payload: Dict[str, Any] = {
            "ref": self.ref,
            "inputs": {"reset_index": "false", "reindex_judgments": "false"},
        }

        try:
            response = self._client.post(url, json=payload, headers=self._headers)
        except httpx.RequestError as e:
            duration = time.monotonic() - start
            logger.error("Reindex (github): dispatch request failed: %s", e)
            return ReindexOutcome(
                triggered=True,
                success=False,
                mode=self.mode,
                duration_seconds=duration,
                run_url=self.workflow_url,
                error=f"GitHub API request failed ({type(e).__name__})",
            )

        if response.status_code != 204:
            duration = time.monotonic() - start
            message = _github_error_message(response)
            logger.error(
                "Reindex (github): dispatch returned HTTP %d: %s", response.status_code, message
            )
            return ReindexOutcome(
                triggered=True,
                success=False,
                mode=self.mode,
                duration_seconds=duration,
                run_url=self.workflow_url,
                error=f"GitHub API returned HTTP {response.status_code}: {message}",
            )

        run_url = self._find_run_url(dispatched_at) or self.workflow_url
        duration = time.monotonic() - start
        logger.info("Reindex (github): dispatched %s on %s -> %s", self.workflow, self.ref, run_url)
        return ReindexOutcome(
            triggered=True,
            success=True,
            mode=self.mode,
            duration_seconds=duration,
            run_url=run_url,
        )

    def _find_run_url(self, dispatched_at: datetime) -> Optional[str]:
        """Best-effort: a dispatch returns 204 with no run id, so look the run up."""
        url = f"{GITHUB_API}/repos/{self.repo}/actions/workflows/{self.workflow}/runs"
        params = {"event": "workflow_dispatch", "branch": self.ref, "per_page": 1}
        # GitHub's created_at has second precision and our clock is sampled
        # just before the POST, so allow a little slack.
        not_before = dispatched_at - timedelta(seconds=5)

        for attempt in range(self.run_lookup_attempts):
            if attempt:
                time.sleep(self.run_lookup_delay_seconds)
            try:
                response = self._client.get(url, params=params, headers=self._headers)
            except httpx.RequestError:
                continue
            if response.status_code != 200:
                continue
            runs = response.json().get("workflow_runs") or []
            if not runs:
                continue
            created_at = datetime.fromisoformat(runs[0]["created_at"].replace("Z", "+00:00"))
            if created_at >= not_before:
                return runs[0].get("html_url")
        return None


def _github_error_message(response: httpx.Response) -> str:
    try:
        return str(response.json().get("message", "")) or response.text[:200]
    except ValueError:
        return response.text[:200]


def build_reindex_trigger(mode: Optional[str] = None) -> ReindexTrigger:
    """Construct the configured trigger. Raises ReindexConfigurationError on bad config."""
    mode = (mode or REINDEX_TRIGGER).strip().lower()
    if mode == "local":
        return LocalReindexTrigger()
    if mode == "github":
        if not GITHUB_REINDEX_TOKEN:
            raise ReindexConfigurationError(
                "REINDEX_TRIGGER=github requires GITHUB_REINDEX_TOKEN (a fine-grained GitHub "
                "PAT with Actions: read/write on the repository). On Cloud Run it is mounted "
                "from Secret Manager (agentic-hybrid-search-github-reindex-token)."
            )
        return GitHubActionsReindexTrigger(
            repo=GITHUB_REPO, token=GITHUB_REINDEX_TOKEN, ref=GITHUB_REINDEX_REF
        )
    raise ReindexConfigurationError(
        f"Unknown REINDEX_TRIGGER '{mode}' -- expected 'local' or 'github'."
    )
