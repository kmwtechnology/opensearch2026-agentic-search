"""
Second-opinion LLM judge for trigger_enrichment: before the agent's own
tool-call decision is allowed to write a taxonomy mapping and trigger a
real Lucille reindex, an independent model evaluates whether the proposed
change would genuinely, meaningfully improve search quality for real
shoppers -- not just whether the first call's choice of canonical bucket
is semantically defensible (it already checked that).

Same bias-mitigation pattern as judge.py's LLMJudge: a different, cheap
model (config.JUDGE_MODEL) than the agent's own generation model, temp=0,
structured output.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from pydantic import BaseModel, Field

from core.llm import build_chat_model

logger = logging.getLogger(__name__)


class EnrichmentValueAssessment(BaseModel):
    """Verdict on whether a proposed trigger_enrichment call is worth a
    real catalog write + reindex."""

    is_meaningful: bool = Field(
        description=(
            "True if writing this variant->canonical mapping and re-indexing "
            "the catalog would genuinely improve search quality for real "
            "shoppers. False for trivial, ambiguous, or low-value changes."
        )
    )
    reasoning: str = Field(
        description="One sentence explaining the verdict -- shown to the user if declined.",
        max_length=300,
    )


_EVALUATOR_SYSTEM = (
    "You are an impartial reviewer deciding whether a proposed change to an "
    "e-commerce search taxonomy is worth making. A separate assistant has "
    "already decided a term should map to a given color/waterproof category, "
    "and chose that category correctly according to plain meaning. Your job "
    "is different: decide whether actually writing this mapping and "
    "re-indexing the whole product catalog (a real, non-trivial operation) "
    "would meaningfully improve search results for real shoppers -- not "
    "whether the category choice is defensible in isolation."
)


def _build_prompt(
    attribute_type: str,
    variant: str,
    canonical: str,
    current_mapping: Optional[str],
    context: str,
) -> str:
    current_line = (
        f'Currently mapped to: "{current_mapping}" (this would be a correction)'
        if current_mapping
        else "Not currently in the taxonomy (this would be a new addition)"
    )
    same_term_note = (
        "\nNote: the term and the proposed category are the SAME WORD. That is "
        "expected and NOT a reason to decline — for an attribute type with no "
        "current mappings at all, mapping a term to itself is how the very "
        "first entry (and the filter dimension it enables) gets registered, "
        "not a redundant or trivial change."
        # (x or "") because callers source these from call["args"].get(key, "")
        # — the "" default only applies to a MISSING key, so a model that
        # emits the key with a JSON null hands us None. Before this check
        # existed both values only ever reached an f-string, where None was
        # harmless; .strip() on None would raise inside agent_node and take
        # down the whole turn.
        if (variant or "").strip().lower() == (canonical or "").strip().lower()
        else ""
    )
    return f"""Proposed change:
  Attribute type: {attribute_type}
  Term: "{variant}"
  Proposed canonical category: "{canonical}"
  {current_line}{same_term_note}

Conversation context that led to this proposal:
{context or "(none given)"}

Would writing this mapping and re-indexing the catalog genuinely, \
meaningfully improve search results for real shoppers searching for this \
term? Consider: is this a real, common term shoppers would actually search \
for (not a typo, brand name, or one-off phrase)? If it's a correction, is \
the current mapping actually wrong in a way that would mislead a shopper \
(not just a matter of taste between two reasonable categories)?

Return is_meaningful (true/false) and a one-sentence reasoning."""


class EnrichmentValueJudge:
    """Gate for trigger_enrichment: judges the proposed mapping itself,
    independent of the agent's own tool-call decision."""

    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.llm = build_chat_model(model_name, temperature=0, max_tokens=512)
        self.structured_llm = self.llm.with_structured_output(EnrichmentValueAssessment)
        logger.info("EnrichmentValueJudge loaded: model=%s", model_name)

    def evaluate(
        self,
        attribute_type: str,
        variant: str,
        canonical: str,
        current_mapping: Optional[str],
        context: str = "",
    ) -> EnrichmentValueAssessment:
        prompt = _build_prompt(attribute_type, variant, canonical, current_mapping, context)
        messages = [
            {"role": "system", "content": _EVALUATOR_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        started = time.time()
        # Also deliberation, also inside agent_node — same streaming leak as
        # the tool-offer call (see core.config.INTERNAL_LLM_TAG).
        from core.config import INTERNAL_LLM_TAG

        result: EnrichmentValueAssessment = self.structured_llm.invoke(
            messages, config={"tags": [INTERNAL_LLM_TAG]}
        )
        elapsed = time.time() - started
        logger.info(
            "EnrichmentValueJudge: is_meaningful=%s in %.2fs (%s '%s' -> '%s')",
            result.is_meaningful,
            elapsed,
            attribute_type,
            variant,
            canonical,
        )
        return result
