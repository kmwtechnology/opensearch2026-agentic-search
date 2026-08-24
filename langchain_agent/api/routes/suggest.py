"""
Autocomplete suggestion endpoint for product titles and brands.

Provides typeahead suggestions using edge-ngram prefix matching, with optional
phonetic-based spell correction when the top hit is plausibly a misspelling
of the user's query.
"""

import logging
import re
from difflib import SequenceMatcher
from typing import List, Optional

from fastapi import APIRouter, Query
from pydantic import BaseModel

from config import OPENSEARCH_INDEX_NAME
from vector_store import create_opensearch_client

logger = logging.getLogger(__name__)

router = APIRouter()

_HIGHLIGHT_PRE = "<mark data-th>"
_HIGHLIGHT_POST = "</mark>"
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


class SuggestionItem(BaseModel):
    """A single autocomplete suggestion."""

    title: str
    brand: Optional[str] = None
    score: Optional[float] = None
    highlight: Optional[List[str]] = None

    model_config = {
        "json_schema_extra": {
            "example": {
                "title": "Sony WH-1000XM5 Wireless Headphones",
                "brand": "Sony",
                "score": 0.95,
                "highlight": ["<mark data-th>Son</mark>y WH-1000XM5 Wireless Headphones"],
            }
        }
    }


class SuggestResponse(BaseModel):
    """Response model for autocomplete suggestions."""

    suggestions: List[SuggestionItem]
    spell_correction: Optional[SuggestionItem] = None

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "suggestions": [
                        {
                            "title": "Sony WH-1000XM5 Wireless Headphones",
                            "brand": "Sony",
                            "score": 0.95,
                            "highlight": [
                                "<mark data-th>Son</mark>y WH-1000XM5 Wireless Headphones"
                            ],
                        }
                    ],
                    "spell_correction": None,
                },
                {
                    "suggestions": [],
                    "spell_correction": {
                        "title": "nike",
                        "brand": "Nike",
                        "score": 0.889,
                        "highlight": None,
                    },
                },
            ]
        }
    }


def _levenshtein(a: str, b: str) -> int:
    """Small Levenshtein distance (iterative DP). a/b expected short (query tokens)."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
        prev = curr
    return prev[-1]


def _detect_spell_correction(
    query: str, top_hits: List[dict], max_score: float
) -> Optional[SuggestionItem]:
    """
    Detect a likely spell correction for a single-token query.

    Strategy: for each of the top hits, tokenize the title; keep any token
    that looks similar to the query (SequenceMatcher ratio >= 0.6) but is
    spelled differently (Levenshtein >= 1). Pick the token with the highest
    ratio. If the resulting confidence is >= 0.5, surface it.

    The distance-1 threshold catches real typos like nikey→nike and
    samsong→samsung; shorter/weaker matches are filtered by the 0.6
    ratio floor and the 0.5 confidence cutoff.

    Multi-word queries are skipped — phrase-level correction needs more
    machinery (n-gram indexes, edit graphs) than this endpoint warrants.
    """
    q = query.strip().lower()
    if " " in q or len(q) < 4:
        return None

    # Collect tokens from top hits. If the query itself appears verbatim as
    # a corpus token, the user is already finding real products — a "Did you
    # mean X" banner is redundant and creates bidirectional cross-suggestion
    # between close real words that co-occur in titles (e.g. "charger" and
    # "charging" both appearing in the AGVEE lightning-cable title would
    # otherwise have each query suggest the other).
    corpus_tokens: set[str] = set()
    for hit in top_hits[:3]:
        title = (hit.get("_source", {}).get("title") or "").strip().lower()
        for match in _TOKEN_RE.finditer(title):
            corpus_tokens.add(match.group(0))

    if q in corpus_tokens:
        return None

    best_token: Optional[str] = None
    best_hit: Optional[dict] = None
    best_ratio = 0.0

    for hit in top_hits[:3]:
        source = hit.get("_source", {})
        title = (source.get("title") or "").strip()
        if not title:
            continue
        for match in _TOKEN_RE.finditer(title.lower()):
            token = match.group(0)
            if len(token) < 4:
                continue
            # Skip when the query is an in-progress prefix of this token.
            # e.g. query "charg" with candidate "charger" — the Suggestions
            # section already surfaces products containing "charger", so a
            # "Did you mean: charger" banner is noise rather than correction.
            if token.startswith(q):
                continue
            if _levenshtein(q, token) < 1:
                continue
            ratio = SequenceMatcher(None, q, token).ratio()
            if ratio >= 0.6 and ratio > best_ratio:
                best_ratio = ratio
                best_token = token
                best_hit = hit

    if not best_token or not best_hit:
        return None

    raw_score = best_hit.get("_score") or 0.0
    normalized = min(raw_score / max_score, 1.0) if max_score else best_ratio
    confidence = min(normalized, best_ratio)
    if confidence < 0.5:
        return None

    source = best_hit.get("_source", {})
    return SuggestionItem(
        title=best_token,
        brand=source.get("product_brand") or None,
        score=round(confidence, 3),
    )


@router.get(
    "/suggest",
    response_model=SuggestResponse,
    summary="Typeahead autocomplete with spell correction",
    description=(
        "Edge-ngram prefix matching against `title_suggest` (boost 2.0) and "
        "`brand_suggest` (boost 1.5) fields on the ESCI product index. "
        "Returns up to `limit` deduplicated suggestions plus an optional "
        "`spell_correction` when the query looks misspelled.\n\n"
        "**Spell correction strategy:**\n"
        "- Levenshtein distance + `SequenceMatcher` ratio (≥ 0.6)\n"
        "- Confidence threshold ≥ 0.5\n"
        "- Skipped when query is already a corpus token\n"
        "- Skipped when query is a prefix of the candidate (e.g. `charg`→`charger`)\n\n"
        "**Fuzzy fallback:** when the primary prefix query returns zero hits "
        "and the query is ≥ 4 chars, runs a second search with "
        "`fuzziness=AUTO` against `title`/`product_brand` to catch "
        "distance-1 typos like `nikey` → `nike`.\n\n"
        "Fails open — if OpenSearch is unreachable, returns an empty list "
        "with HTTP 200 rather than surfacing an error to the typeahead UI."
    ),
    responses={
        200: {
            "description": "Suggestions (possibly empty) plus optional spell correction",
        },
        422: {
            "description": ("Validation error — `q` must be 1–100 chars, `limit` must be 1–20"),
        },
    },
)
async def suggest(
    q: str = Query(
        ...,
        min_length=1,
        max_length=100,
        description="Query prefix for suggestions",
        examples=["sony", "nikey", "wire"],
    ),
    limit: int = Query(
        8,
        ge=1,
        le=20,
        description="Max suggestions to return (1-20, default 8)",
    ),
) -> SuggestResponse:
    """
    Get autocomplete suggestions for product titles and brands.

    Returns up to `limit` deduplicated SuggestionItem objects, plus an
    optional spell_correction suggestion if the query looks misspelled.
    """
    if not q or len(q.strip()) == 0:
        return SuggestResponse(suggestions=[])

    try:
        client = create_opensearch_client()

        body = {
            "size": max(limit, 3),
            "_source": ["title", "product_brand"],
            "query": {
                "bool": {
                    "should": [
                        {"match": {"title_suggest": {"query": q, "boost": 2.0}}},
                        {"match": {"brand_suggest": {"query": q, "boost": 1.5}}},
                    ],
                    # Require at least one should clause to actually match.
                    # Without this, the filter alone returns every ESCI product
                    # with score=0 when the suggest fields are missing from
                    # the mapping — the UI renders random products as "Match: 0%".
                    "minimum_should_match": 1,
                    "filter": [{"term": {"collection_id": "esci_products"}}],
                }
            },
            "highlight": {
                "pre_tags": [_HIGHLIGHT_PRE],
                "post_tags": [_HIGHLIGHT_POST],
                "fields": {
                    "title_suggest": {"number_of_fragments": 0},
                    "brand_suggest": {"number_of_fragments": 0},
                },
            },
        }

        response = client.search(index=OPENSEARCH_INDEX_NAME, body=body)
        hits = response["hits"]["hits"]
        max_score = response["hits"].get("max_score") or 1.0

        seen_titles = set()
        suggestions: List[SuggestionItem] = []
        for hit in hits:
            if len(suggestions) >= limit:
                break
            source = hit.get("_source", {})
            title = (source.get("title") or "").strip()
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            raw_score = hit.get("_score") or 0.0
            hl = hit.get("highlight") or {}
            fragments = (hl.get("title_suggest") or []) + (hl.get("brand_suggest") or [])

            suggestions.append(
                SuggestionItem(
                    title=title,
                    brand=(source.get("product_brand") or None),
                    score=min(raw_score / max_score, 1.0) if max_score else None,
                    highlight=fragments or None,
                )
            )

        spell_correction = _detect_spell_correction(q, hits, max_score)

        # Fuzzy fallback: if the primary edge-ngram query found nothing AND
        # the correction heuristic had no hits to mine, do a second search
        # against the standard `title`/`product_brand` fields with
        # fuzziness=AUTO. This only runs on genuine misspellings (like
        # "nikey" / "samsong") where the edge-ngram index can't tolerate
        # the extra/wrong character. Fuzzy hits are used ONLY for correction
        # mining — they are not surfaced as suggestions.
        if not spell_correction and not hits and " " not in q and len(q) >= 4:
            try:
                fuzzy_response = client.search(
                    index=OPENSEARCH_INDEX_NAME,
                    body={
                        "size": 3,
                        "_source": ["title", "product_brand"],
                        "query": {
                            "bool": {
                                "should": [
                                    {"match": {"title": {"query": q, "fuzziness": "AUTO"}}},
                                    {"match": {"product_brand": {"query": q, "fuzziness": "AUTO"}}},
                                ],
                                "minimum_should_match": 1,
                                "filter": [{"term": {"collection_id": "esci_products"}}],
                            }
                        },
                    },
                )
                fuzzy_hits = fuzzy_response["hits"]["hits"]
                fuzzy_max = fuzzy_response["hits"].get("max_score") or 1.0
                spell_correction = _detect_spell_correction(q, fuzzy_hits, fuzzy_max)
            except Exception as fallback_exc:  # noqa: BLE001
                logger.warning("Fuzzy fallback search failed: %s", fallback_exc)

        logger.info(
            "Suggest query=%r returned %d suggestions (correction=%s)",
            q,
            len(suggestions),
            spell_correction.title if spell_correction else None,
        )
        return SuggestResponse(suggestions=suggestions, spell_correction=spell_correction)

    except Exception as e:
        logger.error("Error during suggest query: %s", e)
        return SuggestResponse(suggestions=[])
