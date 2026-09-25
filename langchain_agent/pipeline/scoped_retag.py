"""
Scoped re-tag: apply a taxonomy change to only the products it can affect (#147).

The live enrichment flywheel (``trigger_enrichment`` -> ``enrich_attribute``)
used to re-run the whole Lucille ingest after writing a mapping. That was ~20s
at 9.6K products; at ~158K products with Lucille embedding every document
through Ollama it is 30+ minutes -- unusable mid-conversation. A mapping change
cannot alter ``chunk_text`` (so no embedding changes either); it can only
change the ``product_<type>``/``_primary``/``_secondary`` tags of products whose
text mentions the changed variant. So: find exactly those products, re-run
detection on them, and write back only what changed.

Detection is a line-for-line port of ``AttributeDetectorStage.detectAttributes``
(lucille-esci, Java) so a scoped re-tag leaves every product exactly as a full
Lucille run would:

* one alternation regex over all variants, longest first, ``\\b``-bounded;
* case-insensitive and ASCII word semantics -- Java 21's defaults for
  ``Pattern.CASE_INSENSITIVE`` and ``\\b`` (``re.ASCII | re.IGNORECASE`` here);
* scan in order of appearance; the first two *distinct* canonicals become
  primary and secondary; the raw field is the first match's original text.

One asymmetry, also copied from the Java stage: ``product_<type>`` (the raw
field) is only ever *overwritten* on a detection, never removed -- for color
it is the ESCI dataset's own ``product_color`` column, which a no-detection
product keeps. So a scoped re-tag sets ``_primary``/``_secondary`` exactly
(set or remove) but only writes the raw field when something was detected.

``tests/unit/test_scoped_retag.py`` pins the port to the Java stage's own test
cases; ``scripts/check_retag_parity.py`` checks it against a real index.
"""

import logging
import re
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Pattern, Tuple

logger = logging.getLogger(__name__)

# Same page size as a Lucille indexer batch; big enough that a demo re-tag
# (a few hundred to a few thousand products) is a handful of round trips.
_PAGE_SIZE = 1000


def build_variant_pattern(lookup: Dict[str, str]) -> Optional[Pattern[str]]:
    """Longest-first alternation over every variant, like buildVariantPattern()."""
    if not lookup:
        return None
    variants = sorted(lookup, key=len, reverse=True)
    alternation = "|".join(re.escape(v) for v in variants)
    return re.compile(rf"\b(?:{alternation})\b", re.IGNORECASE | re.ASCII)


def detect_attributes(
    text: str, lookup: Dict[str, str], pattern: Optional[Pattern[str]] = None
) -> Tuple[Optional[Tuple[str, str]], Optional[Tuple[str, str]]]:
    """(raw, canonical) for primary and secondary; either may be None."""
    pattern = pattern if pattern is not None else build_variant_pattern(lookup)
    if pattern is None or not text:
        return None, None
    found: List[Tuple[str, str]] = []
    seen = set()
    for match in pattern.finditer(text):
        if len(found) >= 2:
            break
        raw = match.group()
        canonical = lookup.get(raw.lower())
        if canonical is not None and canonical not in seen:
            seen.add(canonical)
            found.append((raw, canonical))
    primary = found[0] if found else None
    secondary = found[1] if len(found) > 1 else None
    return primary, secondary


def tag_fields(
    attribute_type: str, text: str, lookup: Dict[str, str], pattern: Optional[Pattern[str]] = None
) -> Dict[str, Optional[str]]:
    """The three product_<type> fields detection produces; None means 'not detected'.

    For ``_primary``/``_secondary`` None means the field must be absent. For
    the raw ``product_<type>`` it means "leave whatever is there" -- see the
    module docstring.
    """
    primary, secondary = detect_attributes(text, lookup, pattern)
    return {
        f"product_{attribute_type}": primary[0] if primary else None,
        f"product_{attribute_type}_primary": primary[1] if primary else None,
        f"product_{attribute_type}_secondary": secondary[1] if secondary else None,
    }


@dataclass
class RetagResult:
    candidates: int  # products whose text (or raw tag) mentions a changed variant
    updated: int  # of those, products whose tags actually changed


# Painless: set each field, or remove it when detection produced nothing --
# the same end state as Lucille re-indexing the document from scratch.
_SET_OR_REMOVE = """
for (entry in params.fields.entrySet()) {
  if (entry.getValue() == null) { ctx._source.remove(entry.getKey()); }
  else { ctx._source[entry.getKey()] = entry.getValue(); }
}
"""


def candidate_query(attribute_type: str, variants: Iterable[str]) -> dict:
    """Every product a change to ``variants`` could re-tag.

    A superset is fine (detection re-runs exactly); a miss is not. Products
    whose chunk_text contains the variant as a phrase can gain or change a
    tag; products whose raw tag *is* the variant can lose one (e.g. the
    mapping was deleted). ``scripts/check_retag_parity.py`` measures recall.
    """
    should = []
    for variant in variants:
        # chunk_text.words, not chunk_text: the standard tokenizer keeps
        # "Color:black" / "Brown.All" as one token, so a phrase query on the
        # main field misses text the detector's ASCII \b regex matches.
        should.append({"match_phrase": {"chunk_text.words": variant}})
        should.append({"match_phrase": {f"product_{attribute_type}": variant}})
    return {"bool": {"should": should, "minimum_should_match": 1}}


def retag(
    client, index: str, attribute_type: str, variants: Iterable[str], lookup: Dict[str, str]
) -> RetagResult:
    """Re-detect ``attribute_type`` on every candidate product; write back changes.

    ``lookup`` is the attribute type's *full* current variant->canonical table
    (after the change) -- detection on a product depends on every variant its
    text contains, not just the changed one.
    """
    variants = [v for v in dict.fromkeys(v.strip().lower() for v in variants) if v]
    if not variants:
        return RetagResult(candidates=0, updated=0)
    pattern = build_variant_pattern(lookup)
    field_names = list(tag_fields(attribute_type, "", {}).keys())
    raw_field = f"product_{attribute_type}"

    candidates = 0
    actions: List[dict] = []
    search_after = None
    while True:
        body = {
            "size": _PAGE_SIZE,
            "query": candidate_query(attribute_type, variants),
            "_source": ["chunk_text", *field_names],
            "sort": [{"_id": "asc"}],
        }
        if search_after is not None:
            body["search_after"] = search_after
        hits = client.search(index=index, body=body)["hits"]["hits"]
        if not hits:
            break
        for hit in hits:
            candidates += 1
            src = hit.get("_source", {})
            new = tag_fields(attribute_type, src.get("chunk_text", ""), lookup, pattern)
            if new[raw_field] is None:
                del new[raw_field]  # never remove the raw field (dataset column)
            if any(src.get(k) != v for k, v in new.items()):
                actions.append({"update": {"_index": index, "_id": hit["_id"]}})
                actions.append(
                    {
                        "script": {
                            "source": _SET_OR_REMOVE,
                            "lang": "painless",
                            "params": {"fields": new},
                        }
                    }
                )
        search_after = hits[-1]["sort"]

    updated = len(actions) // 2
    for start in range(0, len(actions), 2 * _PAGE_SIZE):
        response = client.bulk(body=actions[start : start + 2 * _PAGE_SIZE])
        if response.get("errors"):
            failed = [i for i in response["items"] if i.get("update", {}).get("error")]
            raise RuntimeError(f"scoped re-tag: {len(failed)} bulk updates failed: {failed[:1]}")
    if updated:
        client.indices.refresh(index=index)
    logger.info(
        "Scoped re-tag %s %s: %d candidates, %d updated",
        attribute_type,
        variants,
        candidates,
        updated,
    )
    return RetagResult(candidates=candidates, updated=updated)
