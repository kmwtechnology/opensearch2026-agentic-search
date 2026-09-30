"""LLM-as-judge for the Pipeline Summary "Generation" stage.

Compares the agent's answer with the raw product list and returns a pairwise verdict, four
0-1 scores (faithfulness, answer_relevance, citation_accuracy, context_utilization), a
justification, and tiered hallucination flags.

Response A/B labels are randomized per call to counter positional bias, and temperature is
0. JUDGE_MODEL can differ from the agent's model to reduce self-preference, but both default
to the same resident model.
"""

from __future__ import annotations

import logging
import random
import time
from enum import Enum
from typing import List, Literal

from langchain_core.documents import Document
from pydantic import BaseModel, Field, field_validator

from core.llm import build_chat_model

logger = logging.getLogger(__name__)


Verdict = Literal["llm_better", "tied", "llm_worse"]


class HallucinationCategory(str, Enum):
    """Severity tier of a flagged claim. Fabrication and cross_product_bleed trigger the
    auto-correction retry; inference and overreach are only surfaced."""

    fabrication = "fabrication"
    cross_product_bleed = "cross_product_bleed"
    inference = "inference"
    overreach = "overreach"


RETRY_ELIGIBLE_CATEGORIES: frozenset[HallucinationCategory] = frozenset(
    {HallucinationCategory.fabrication, HallucinationCategory.cross_product_bleed}
)


class FlaggedClaim(BaseModel):
    """A single judged claim from the LLM response that wasn't fully grounded."""

    claim: str = Field(description="The unsupported claim, quoted or paraphrased.")
    category: HallucinationCategory = Field(
        description=(
            "Severity tier: fabrication / cross_product_bleed (retry-worthy) "
            "vs inference / overreach (surface only)."
        ),
    )
    reasoning: str = Field(
        default="",
        description="One-sentence why this claim landed in this category.",
        max_length=300,
    )


class JudgmentResult(BaseModel):
    """Structured output of one LLM-as-judge call."""

    verdict: Verdict = Field(description="Pairwise verdict: is the LLM response more useful?")
    pairwise_justification: str = Field(
        description="One or two sentences explaining the verdict.",
        max_length=500,
    )
    faithfulness: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "0.0-1.0. 1.0 means every factual claim in the LLM response is "
            "supported by the retrieved products. Lower for hallucinated facts."
        ),
    )
    answer_relevance: float = Field(
        ge=0.0,
        le=1.0,
        description="0.0-1.0. How well the LLM response addresses the user query.",
    )
    citation_accuracy: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "0.0-1.0. If the response cites products, the citations match what the "
            "response says about them. 1.0 if no citations or all citations correct."
        ),
    )
    context_utilization: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "0.0-1.0. Fraction of the retrieved products that the LLM response "
            "meaningfully references."
        ),
    )
    hallucinations: List[FlaggedClaim] = Field(
        default_factory=list,
        description=(
            "Specific claims in the LLM response NOT supported by the retrieved "
            "products, each tagged with a severity category. Empty list if none."
        ),
        max_length=10,
    )

    @field_validator("hallucinations", mode="before")
    @classmethod
    def _coerce_hallucinations(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            stripped = v.strip()
            return (
                [{"claim": stripped, "category": HallucinationCategory.fabrication}]
                if stripped
                else []
            )
        coerced: list = []
        for item in v:
            if isinstance(item, str):
                if item.strip():
                    coerced.append(
                        {"claim": item.strip(), "category": HallucinationCategory.fabrication}
                    )
            else:
                coerced.append(item)
        return coerced


_JUDGE_SYSTEM = (
    "You are an impartial evaluator of an e-commerce product-search assistant. "
    "You will judge how well a synthesized response addresses a user's query, "
    "compared to a deterministic raw-list response. Score strictly on the "
    "axes provided. For each flagged claim, quote or paraphrase the claim AND "
    "tier it into a category (fabrication, cross_product_bleed, inference, or "
    "overreach) so downstream gating can distinguish dangerous fabrications "
    "from harmless over-paraphrases."
)


def _format_docs_for_prompt(documents: List[Document], max_chars: int = 10_000) -> str:
    """Numbered render of the retrieved docs. The 10,000-char cap is a safety limit, not a
    budget: shorter caps caused false fabrication flags on facts in late bullet points."""
    lines = []
    for i, doc in enumerate(documents, 1):
        title = doc.metadata.get("title") or "(untitled)"
        product_id = doc.metadata.get("product_id") or "?"
        snippet = (doc.page_content or "").replace("\n", " ").strip()
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"
        entry = f"{i}. [{product_id}] {title}\n   {snippet}"
        # The judge must see every fact the generator saw (see _build_grounded_context),
        # or it flags grounded claims such as "indexed as yellow" as fabrication.
        color = doc.metadata.get("product_color") or ""
        color_category = doc.metadata.get("product_color_primary") or ""
        if color:
            entry += f"\n   Color (as listed): {color}"
        if color_category:
            entry += f"\n   Color category (indexed): {color_category}"
        lines.append(entry)
    return "\n".join(lines)


def _build_prompt(
    query: str,
    documents: List[Document],
    response_a: str,
    response_b: str,
    a_is_llm: bool,
) -> str:
    """Build the judge prompt with blind A/B labels."""
    docs_block = _format_docs_for_prompt(documents)
    llm_label = "Response A" if a_is_llm else "Response B"

    return f"""User query:
{query}

Retrieved products (top {len(documents)}):
{docs_block}

Response A:
{response_a}

Response B:
{response_b}

You are evaluating {llm_label} (the synthesized assistant response).
The other response is a deterministic raw-list rendering of the retrieved products.

Evaluate {llm_label} on these axes (each scored 0.0–1.0):
  • faithfulness: Every factual claim in {llm_label} is supported by the retrieved products. 1.0 = no unsupported claims; lower for hallucinations.
  • answer_relevance: How well {llm_label} addresses the user query intent.
  • citation_accuracy: If {llm_label} cites products, the citations match what it says about them. 1.0 if no citations or all are correct.
  • context_utilization: Proportion of retrieved products that {llm_label} meaningfully references.

Pairwise verdict — which response is more useful TO THIS USER for THIS query?
  • "llm_better": {llm_label} is meaningfully more useful (good synthesis, comparison, or recommendation justifies the prose form).
  • "tied": Both equally useful, or both poor.
  • "llm_worse": The raw-list response is more useful ({llm_label} added confusion, hallucination, or omitted relevant products).

List specific flagged claims in {llm_label} — claims not fully supported by the retrieved products. For EACH flagged claim, return an object with:
  • claim: the unsupported text (quoted or paraphrased)
  • category: ONE of
      - "fabrication": an outright wrong fact (e.g. "Made in USA" when the product's FACTS say nothing of the sort)
      - "cross_product_bleed": a fact that's true of one retrieved product but transferred to a different one
      - "inference": a paraphrase that goes slightly beyond the source (e.g. "designed to aid plaque removal" when the FACTS say "chewy texture cleans teeth")
      - "overreach": a general claim that exceeds what's grounded in any FACTS block (e.g. "best-selling in its category")
  • reasoning: one short sentence explaining why this category fits

Be strict on fabrication / cross_product_bleed — those are the dangerous ones. Use inference / overreach for paraphrases or general claims that aren't dangerous lies. Empty list if no flags.

Provide a 1-2 sentence justification for the pairwise verdict."""


class LLMJudge:
    """Pairwise + absolute LLM-as-judge for the Generation stage."""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self.llm = build_chat_model(self.model_name, temperature=0, max_tokens=1024)
        self.structured_llm = self.llm.with_structured_output(JudgmentResult)
        logger.info("LLMJudge loaded: model=%s", self.model_name)

    def judge(
        self,
        query: str,
        documents: List[Document],
        llm_response: str,
        baseline_response: str,
    ) -> JudgmentResult:
        """Score the LLM response against the baseline. The A/B assignment is random per call;
        the verdict is reported in terms of the LLM response, whichever label it wore."""
        a_is_llm = random.random() < 0.5
        response_a = llm_response if a_is_llm else baseline_response
        response_b = baseline_response if a_is_llm else llm_response

        prompt = _build_prompt(query, documents, response_a, response_b, a_is_llm)
        messages = [
            {"role": "system", "content": _JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ]
        started = time.time()
        result: JudgmentResult = self.structured_llm.invoke(messages)
        elapsed = time.time() - started
        logger.info(
            "LLMJudge: verdict=%s in %.2fs (a_is_llm=%s)",
            result.verdict,
            elapsed,
            a_is_llm,
        )
        return result
