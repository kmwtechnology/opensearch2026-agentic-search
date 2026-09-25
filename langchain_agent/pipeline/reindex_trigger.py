"""
Reindex trigger — how the enrichment flywheel applies a new attribute mapping
to the catalog. Two modes (REINDEX_TRIGGER):

* ``scoped`` (default): re-detect the changed attribute on only the products
  whose text mentions the changed variant(s), and write back what changed
  (pipeline/scoped_retag.py). Seconds, synchronous, no re-embedding -- the
  only viable live path since the corpus grew to ~158K products embedded by
  Lucille through Ollama (#147/#148).
* ``local``: re-run the full products ingest (scripts/lucille_ingest.sh) as a
  subprocess and wait for it. Re-embeds every product: 30+ minutes now, so
  only for an explicit full rebuild, never mid-conversation.
"""

import logging
import re
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol, Sequence

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
    mode: str  # "scoped" or "local"
    docs_processed: int = 0  # products whose tags changed (scoped) / ingested (local)
    docs_scanned: int = 0  # scoped only: candidate products re-detected
    duration_seconds: float = 0.0
    run_url: Optional[str] = None  # unused by the local trigger; kept for schema compat
    error: Optional[str] = None  # short, user-safe detail when success is False


class ReindexTrigger(Protocol):
    mode: str

    def trigger(
        self, attribute_type: Optional[str] = None, variants: Sequence[str] = ()
    ) -> ReindexOutcome: ...


# Guards every write that re-tags the products index -- a Lucille run and a
# scoped re-tag must never interleave. Module-level: one index, one writer.
_LOCAL_REINDEX_LOCK = threading.Lock()


class ScopedRetagTrigger:
    """Re-tag only the products a mapping change can affect (the default)."""

    mode = "scoped"

    def trigger(
        self, attribute_type: Optional[str] = None, variants: Sequence[str] = ()
    ) -> ReindexOutcome:
        if not attribute_type or not variants:
            return ReindexOutcome(
                triggered=False,
                success=False,
                mode=self.mode,
                error="scoped re-tag needs an attribute type and variant",
            )
        if not _LOCAL_REINDEX_LOCK.acquire(blocking=False):
            logger.warning("Reindex (scoped): refused — another re-index is already running")
            return ReindexOutcome(
                triggered=False,
                success=False,
                mode=self.mode,
                error="a re-index is already running",
            )
        start = time.monotonic()
        try:
            from core.config import OPENSEARCH_INDEX_NAME
            from pipeline.scoped_retag import retag
            from retrieval.attribute_mapping_store import AttributeMappingStore
            from retrieval.vector_store import get_shared_opensearch_client

            lookup = AttributeMappingStore().get_lookup_table(attribute_type)
            result = retag(
                get_shared_opensearch_client(),
                OPENSEARCH_INDEX_NAME,
                attribute_type,
                variants,
                lookup,
            )
        except Exception as e:  # noqa: BLE001 -- report, don't crash the chat turn
            logger.exception("Reindex (scoped): failed")
            return ReindexOutcome(
                triggered=True,
                success=False,
                mode=self.mode,
                duration_seconds=time.monotonic() - start,
                error=f"scoped re-tag failed: {type(e).__name__}",
            )
        finally:
            _LOCAL_REINDEX_LOCK.release()
        return ReindexOutcome(
            triggered=True,
            success=True,
            mode=self.mode,
            docs_processed=result.updated,
            docs_scanned=result.candidates,
            duration_seconds=time.monotonic() - start,
        )


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

    def trigger(
        self, attribute_type: Optional[str] = None, variants: Sequence[str] = ()
    ) -> ReindexOutcome:
        # A full ingest re-detects every attribute on every product, so the
        # scope arguments are accepted (protocol) and deliberately ignored.
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
    if mode == "scoped":
        return ScopedRetagTrigger()
    if mode == "local":
        return LocalReindexTrigger()
    raise ReindexConfigurationError(
        f"Unknown REINDEX_TRIGGER '{mode}' -- expected 'scoped' or 'local'."
    )
