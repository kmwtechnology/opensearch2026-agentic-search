"""
Reindex trigger — how the enrichment flywheel applies a new attribute mapping
to the catalog: re-detect the changed attribute on only the products whose
text mentions the changed variant(s), and write back what changed
(pipeline/scoped_retag.py). Seconds, synchronous, no re-embedding -- the only
mode there is, since the corpus is a permanent precomputed export (#147/#148,
#150) with no local rebuild path.
"""

import logging
import threading
import time
from dataclasses import dataclass
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


@dataclass
class ReindexOutcome:
    triggered: bool
    success: bool
    mode: str  # "scoped"
    docs_processed: int = 0  # products whose tags changed
    docs_scanned: int = 0  # candidate products re-detected
    duration_seconds: float = 0.0
    error: Optional[str] = None  # short, user-safe detail when success is False


# Guards every write that re-tags the products index -- two re-tags must
# never interleave. Module-level: one index, one writer.
_LOCAL_REINDEX_LOCK = threading.Lock()


class ScopedRetagTrigger:
    """Re-tag only the products a mapping change can affect."""

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


def build_reindex_trigger() -> ScopedRetagTrigger:
    """Construct the reindex trigger; ``scoped`` is the only mode there is."""
    return ScopedRetagTrigger()
