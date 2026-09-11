"""
Document Replacement Module - Intelligently replaces broken-link documents.

When a retrieved document has a broken citation link, this module finds
a suitable replacement from the broader retrieval results to maintain
document count while ensuring all links are valid.

Strategy:
1. Identify documents with broken links
2. For each broken document, find replacements:
   - Same source file (different section) → prefer this
   - Similar relevance score (nearby results)
   - Valid link available
3. Replace broken doc with valid alternative
4. Maintain requested document count
5. Track all replacements for observability
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.documents import Document

logger = logging.getLogger(__name__)


class DocumentReplacer:
    """
    Intelligently replaces documents with broken links.

    Maintains document count by substituting broken-link documents
    with valid alternatives from the retrieval results.
    """

    def __init__(self):
        """Initialize document replacer."""
        self.replacements_made = 0
        self.replacement_log: List[Dict[str, str]] = []

    def get_source_base(self, source: str) -> str:
        """
        Extract base source path (file without section).

        Examples:
            "docs/foo.md#section1" → "docs/foo.md"
            "docs/foo.md" → "docs/foo.md"
        """
        if not source:
            return ""
        return source.split("#")[0]

    def calculate_replacement_score(
        self,
        candidate: Document,
        broken_doc: Document,
        used_indices: set,
    ) -> float:
        """
        Calculate suitability score for replacing a broken document.

        Higher score = better replacement. Considers:
        - Same source file (high priority)
        - Similar relevance (reranker score)
        - Not already used
        - Valid link
        """
        doc_index = None

        # Find candidate's index in original list
        for i, doc in enumerate(broken_doc.metadata.get("_original_list", [])):
            if doc is candidate:
                doc_index = i
                break

        if doc_index is None:
            return 0.0

        # Already used as replacement?
        if doc_index in used_indices:
            return -1.0

        score = 0.0

        # Factor 1: Same source file (0-100 points)
        broken_source_base = self.get_source_base(broken_doc.metadata.get("source", ""))
        candidate_source_base = self.get_source_base(candidate.metadata.get("source", ""))

        if broken_source_base and broken_source_base == candidate_source_base:
            score += 100  # Prefer same file

        # Factor 2: Relevance proximity (0-50 points)
        broken_score = broken_doc.metadata.get("reranker_score", 0.0) or 0.0
        candidate_score = candidate.metadata.get("reranker_score", 0.0) or 0.0

        if broken_score > 0:
            score_ratio = candidate_score / broken_score
            # Penalize if much worse, reward if similar
            if score_ratio >= 0.7:
                score += 50 * score_ratio
            else:
                score -= 50  # Too much worse

        # Factor 3: Position proximity (0-30 points)
        broken_index = broken_doc.metadata.get("_doc_index", 999)
        distance = abs(doc_index - broken_index)
        if distance < 5:
            score += (5 - distance) * 6

        return max(0.0, score)

    def find_replacement(
        self,
        broken_doc: Document,
        all_docs: List[Document],
        used_indices: set,
    ) -> Optional[Document]:
        """
        Find best replacement for a broken-link document.

        Args:
            broken_doc: Document with broken/missing link
            all_docs: All retrieved documents to choose from
            used_indices: Set of already-used document indices

        Returns:
            Best replacement document, or None if none suitable
        """
        if not all_docs:
            return None

        best_candidate = None
        best_score = -1.0

        for candidate in all_docs:
            # Skip if broken doc itself
            if candidate is broken_doc:
                continue

            # Skip if no URL
            if not candidate.metadata.get("url"):
                continue

            score = self.calculate_replacement_score(candidate, broken_doc, used_indices)

            if score > best_score:
                best_score = score
                best_candidate = candidate

        return best_candidate if best_score > 0 else None

    def replace_broken_documents(
        self,
        documents: List[Document],
        broken_urls: Dict[str, Tuple[bool, str]],
        min_valid_documents: int = 10,
    ) -> Tuple[List[Document], Dict[str, str]]:
        """
        Replace documents with broken links while maintaining count.

        Args:
            documents: Retrieved documents (may have broken links)
            broken_urls: Dict mapping URL -> (is_valid, reason)
            min_valid_documents: Maintain this many documents with valid links

        Returns:
            Tuple of (updated_documents, replacement_log)
            - updated_documents: Documents with valid links
            - replacement_log: Tracking info about replacements
        """
        self.replacement_log = []
        replaced_count = 0

        # Store original list for reference (creates circular references)
        for i, doc in enumerate(documents):
            doc.metadata["_original_list"] = documents
            doc.metadata["_doc_index"] = i

        try:
            # Identify broken documents
            broken_docs = []
            for doc in documents:
                doc_url = doc.metadata.get("url", "")
                if doc_url and not broken_urls.get(doc_url, (True, ""))[0]:
                    broken_docs.append(doc)

            if not broken_docs:
                logger.info("✓ All document links are valid")
                return documents, {}

            logger.info(f"Found {len(broken_docs)} documents with broken links")

            # Replace broken documents
            used_indices = set()
            for broken_doc in broken_docs:
                replacement = self.find_replacement(broken_doc, documents, used_indices)

                if replacement:
                    # Log replacement
                    old_source = broken_doc.metadata.get("source", "unknown")
                    old_url = broken_doc.metadata.get("url", "unknown")
                    new_source = replacement.metadata.get("source", "unknown")
                    new_url = replacement.metadata.get("url", "unknown")

                    log_entry = {
                        "old_source": old_source,
                        "old_url": old_url,
                        "new_source": new_source,
                        "new_url": new_url,
                        "reason": "Link verification failed",
                    }

                    self.replacement_log.append(log_entry)
                    logger.info(
                        f"[DocReplacer] Replaced broken doc: {old_source[:40]}... "
                        f"→ {new_source[:40]}..."
                    )

                    # Replace in documents list
                    broken_index = documents.index(broken_doc)
                    documents[broken_index] = replacement
                    used_indices.add(broken_index)
                    replaced_count += 1
                else:
                    logger.warning(
                        f"[DocReplacer] Could not find replacement for {broken_doc.metadata.get('source', 'unknown')}"
                    )

            self.replacements_made += replaced_count

            # Ensure we have minimum documents
            if len(documents) < min_valid_documents:
                logger.warning(
                    f"Document count ({len(documents)}) below minimum ({min_valid_documents})"
                )

            logger.info(f"✓ Replaced {replaced_count} documents with broken links")
            return documents, self._log_to_dict()
        finally:
            # Always clean up temporary metadata (prevent circular references/memory leaks)
            for doc in documents:
                doc.metadata.pop("_original_list", None)
                doc.metadata.pop("_doc_index", None)

    def _log_to_dict(self) -> Dict[str, str]:
        """Convert replacement log to dictionary for events."""
        if not self.replacement_log:
            return {}

        summary = []
        for entry in self.replacement_log:
            summary.append(f"{entry['old_source']} → {entry['new_source']}")

        return {"replacements": summary, "count": len(self.replacement_log)}

    def get_stats(self) -> Dict[str, Any]:
        """Get replacement statistics."""
        return {
            "replacements_made": self.replacements_made,
            "replacement_log": self.replacement_log,
        }
