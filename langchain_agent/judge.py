"""
LLM-as-judge for Pipeline Quality Summary "Generation" stage.

Compares the agent's synthesized response (LLM:on path) against the
deterministic raw-product-list response (LLM:off path) and emits a
structured judgment with a pairwise verdict, four absolute scores
(faithfulness, answer_relevance, citation_accuracy, context_utilization),
a brief justification, and any specific hallucinations the judge spotted.

Bias mitigations:
  * Use a different model for the judge than the agent (we use
    gemini-3.1-flash-lite-preview by default; the agent uses
    gemini-3-flash-preview). Reduces self-preference.
  * Randomize "Response A" / "Response B" labels per call to mitigate
    positional bias on the pairwise verdict. The judge sees blind
    labels; we map back to llm/baseline server-side.
  * Tight token limits + temperature=0 for repeatability.

Cost: one extra Gemini Flash Lite call per judged query (~1-2s,
~$0.0005). Skipped when ``optimizations.llm_judge:false`` or
``optimizations.llm:false``.
"""

from __future__ import annotations

import logging
import random
import time
from enum import Enum
from typing import List, Literal, Optional

from langchain_core.documents import Document
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


Verdict = Literal["llm_better", "tied", "llm_worse"]


class HallucinationCategory(str, Enum):
    """Tier a flagged claim by severity so the retry gate can route on it.

    ``fabrication`` and ``cross_product_bleed`` are dangerous and trigger the
    auto-correction retry. ``inference`` and ``overreach`` are surfaced to the
    user but skip the ~20–30s retry — regenerating typically makes the answer
    worse, not better.
    """

    fabrication = "fabrication"
    cross_product_bleed = "cross_product_bleed"
    inference = "inference"
    overreach = "overreach"


# Categories that justify the auto-correction retry path.
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
            if isinstance(item, FlaggedClaim):
                coerced.append(item)
            elif isinstance(item, str):
                if item.strip():
                    coerced.append(
                        {
                            "claim": item.strip(),
                            "category": HallucinationCategory.fabrication,
                        }
                    )
            elif isinstance(item, dict):
                coerced.append(item)
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
    """Compact numbered render of the retrieved docs, truncated for prompt size.

    Default 10 000 chars/doc — effectively no truncation for any realistic ESCI
    product (ceiling ~2498 chars, e.g. Thursday Boot Company Captain B07PQ9M1C5).
    At RETRIEVER_K=4 docs the block is ≤40 000 chars (~10 000 tokens), still
    negligible for Gemini Flash Lite's 1M-token context. Earlier limits (360 in
    issue #81, 1500 in PR #82, 2500 in issue #84) all caused false-positive
    fabrication flags when grounded product attributes appeared in late Amazon
    bullet points past the cutoff. 10 000 is a safety cap against pathological
    documents, not a tuned budget.
    """
    lines = []
    for i, doc in enumerate(documents, 1):
        title = doc.metadata.get("title") or "(untitled)"
        product_id = doc.metadata.get("product_id") or "?"
        snippet = (doc.page_content or "").replace("\n", " ").strip()
        if len(snippet) > max_chars:
            snippet = snippet[:max_chars].rstrip() + "…"
        lines.append(f"{i}. [{product_id}] {title}\n   {snippet}")
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

    def __init__(self, model_name: str = "gemini-3.1-flash-lite-preview"):
        self.model_name = model_name
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0,
            streaming=False,
            max_output_tokens=1024,
        )
        self.structured_llm = self.llm.with_structured_output(JudgmentResult)
        logger.info("LLMJudge loaded: model=%s", model_name)

    def judge(
        self,
        query: str,
        documents: List[Document],
        llm_response: str,
        baseline_response: str,
        *,
        seed: Optional[int] = None,
    ) -> JudgmentResult:
        """Score the LLM response against the baseline raw-list response.

        The verdict's polarity is normalized: "llm_better" always means the
        synthesized response wins, regardless of which blind label the model
        actually saw. We randomize A/B per call to mitigate positional bias.
        """
        rng = random.Random(seed) if seed is not None else random
        a_is_llm = rng.random() < 0.5
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
