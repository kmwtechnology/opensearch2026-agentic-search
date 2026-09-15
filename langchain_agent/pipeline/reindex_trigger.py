"""
Reindex trigger — how the enrichment flywheel gets the catalog re-indexed
after writing a new attribute mapping: runs scripts/lucille_ingest.sh as a
subprocess and waits for it (Docker on this host, ~20s, synchronous, reports
doc count).
"""

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from core.config import REINDEX_LOCAL_TIMEOUT_SECONDS, REINDEX_TRIGGER
from core.exceptions import ConfigurationError

logger = logging.getLogger(__name__)

LANGCHAIN_AGENT_DIR = Path(__file__).parent.parent


class ReindexConfigurationError(ConfigurationError):
    """REINDEX_TRIGGER is misconfigured (unknown mode)."""


@dataclass
class ReindexOutcome:
    triggered: bool
    success: bool
    mode: str  # "local"
    docs_processed: int = 0
    duration_seconds: float = 0.0
    run_url: Optional[str] = None  # unused by the local trigger; kept for schema compat
    error: Optional[str] = None  # short, user-safe detail when success is False


class ReindexTrigger(Protocol):
    mode: str

    def trigger(self) -> ReindexOutcome: ...


# Guards the local Lucille subprocess. Module-level: one index, one ingest.
_LOCAL_REINDEX_LOCK = threading.Lock()


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
        # Until #103 the agent node ran on the event loop thread, which meant
        # a second concurrent request physically could not start a second
        # re-index — the loop was blocked. Now that the node runs in a worker
        # thread that accidental serialization is gone, so make it explicit: a
        # stray second tab must not run Lucille over the index while another
        # ingest is mid-write.
        if not _LOCAL_REINDEX_LOCK.acquire(blocking=False):
            logger.warning("Reindex (local): refused — another re-index is already running")
            return ReindexOutcome(
                triggered=False,
                success=False,
                mode=self.mode,
                error="a re-index is already running",
            )
        try:
            return self._run()
        finally:
            _LOCAL_REINDEX_LOCK.release()

    def _run(self) -> ReindexOutcome:
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


def build_reindex_trigger(mode: Optional[str] = None) -> ReindexTrigger:
    """Construct the configured trigger. Raises ReindexConfigurationError on bad config."""
    mode = (mode or REINDEX_TRIGGER).strip().lower()
    if mode == "local":
        return LocalReindexTrigger()
    raise ReindexConfigurationError(f"Unknown REINDEX_TRIGGER '{mode}' -- expected 'local'.")
