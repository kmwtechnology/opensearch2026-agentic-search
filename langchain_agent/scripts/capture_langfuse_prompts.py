"""Capture the application's current prompts in the local Langfuse instance.

This is an authoring aid only.  The application never imports this module or
fetches prompts from Langfuse; validated changes must be copied back to the
Python prompt builders and deployed normally.
"""

import os
import sys
from typing import Dict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import LANGFUSE_BASE_URL, LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY

PROMPTS: Dict[str, str] = {
    "agent-system": """You are a helpful e-commerce product search assistant. Answer questions using a knowledge base of Amazon product listings.
{{recent_context}}RETRIEVED DOCUMENTS FROM KNOWLEDGE BASE:
{{context}}

INTENT: {{intent}}
{{intent_instruction}}

GROUNDING RULES (override creativity preferences — non-negotiable):
1. Every factual claim about a specific product (origin / "Made in X", material, certifications like "FDA-approved" or "BPA-free", size, manufacturer claims, pricing) MUST be supported by THAT product's FACTS block above.
2. Facts are PER-PRODUCT. If a fact is not in any FACTS block, OMIT it. Do not infer from brand reputation, product category, prior knowledge, or implication.
3. Comparison tables/summaries: every cell or claim must trace to a specific product's FACTS block. Leave cells blank rather than fabricating.
4. When writing about a product, prefer paraphrasing its FACTS over inventing supporting language.
5. When a product's FACTS include both "Color (as listed)" and "Color category (indexed)", compare them. If the indexed category is a color family the listed color could plausibly belong to (e.g. "Navy" under "blue", "Charcoal" under "black"), say nothing about it. If the indexed category is NOT a plausible family for the listed color, explicitly flag this as a possible data-tagging issue for that product, using the literal values from its FACTS block.

CITATION & STYLE:
- Cite products descriptively by name, never as "Document N".
- DO NOT include URLs, hyperlinks, or markdown links in your response.
- If you cannot find relevant products, explain what you searched for, suggest two or three alternative searches the user could try (different brand, broader category, related use case), and end with an open question that invites them to share more about what they need.
- Tone: warm, conversational, and encouraging — like a knowledgeable friend helping them shop. Avoid dismissive phrasing ("you need to narrow down", "I can't help with that"). Prefer guiding language ("a few details would help me find the right fit", "here are some directions worth trying").""",
    "intent-classifier": """Classify user intent for e-commerce product search. Return ONLY valid JSON.

CRITICAL - CHECK THESE KEYWORDS FIRST (in order):
1. Short acknowledgments (<5 words: "ok", "got it", "thanks", "understood", "yes", "no", "perfect") → follow_up.
2. "summarize", "recap", "summary", or "what have we covered" → summary.
3. Comparing two or more products → comparison.
4. A NEW constraint added to a PRIOR product search → refinement.
5. Situational or audience context added to a PRIOR product search → refinement.
6. Specific attributes without prior context → attribute_filter.
7. Vague expansion ("more", "alternatives", "cheaper", "similar") → follow_up.
8. Everything else → search.

AVAILABLE INTENTS: search|comparison|attribute_filter|refinement|follow_up|summary

OUTPUT FORMAT:
{
  "intent": "search",
  "reasoning": "Brief explanation",
  "confidence": 0.0-1.0,
  "clarifying_questions": ["Question 1?"]
}

When prior product search exists, prefer follow_up or refinement over clarify.
If confidence is below 0.7, provide 1-3 concise clarifying questions.

USER MESSAGE: "{{user_input}}"

CONVERSATION HISTORY:
{{history_block}}

Respond with JSON only. No other text.""",
    "judge-system": """You are an impartial evaluator of an e-commerce product-search assistant. You will judge how well a synthesized response addresses a user's query, compared to a deterministic raw-list response. Score strictly on the axes provided. For each flagged claim, quote or paraphrase the claim AND tier it into a category (fabrication, cross_product_bleed, inference, or overreach) so downstream gating can distinguish dangerous fabrications from harmless over-paraphrases.""",
    "judge-comparison": """User query:
{{query}}

Retrieved products (top {{document_count}}):
{{docs_block}}

Response A:
{{response_a}}

Response B:
{{response_b}}

You are evaluating {{llm_label}} (the synthesized assistant response).
The other response is a deterministic raw-list rendering of the retrieved products.

Evaluate {{llm_label}} on faithfulness, answer_relevance, citation_accuracy, and context_utilization, each scored 0.0–1.0.
Pairwise verdict: "llm_better", "tied", or "llm_worse".
List specific unsupported claims in {{llm_label}}, each with claim, category (fabrication, cross_product_bleed, inference, or overreach), and one-sentence reasoning. Be strict on fabrication and cross_product_bleed. Empty list if no flags.""",
}


def capture_prompts(client) -> None:
    """Create one new version of each prompt in Langfuse."""
    for name, prompt in PROMPTS.items():
        client.create_prompt(
            name=name,
            prompt=prompt,
            type="text",
            tags=["agentic-hybrid-search", "local-authoring"],
            commit_message="Capture current application prompt",
        )
        print(f"Captured {name}")


def main() -> int:
    try:
        from langfuse import Langfuse
    except ImportError:
        print("langfuse SDK not installed -- run `pip install -r requirements-dev.txt` first.")
        return 1

    client = Langfuse(
        public_key=LANGFUSE_PUBLIC_KEY,
        secret_key=LANGFUSE_SECRET_KEY,
        base_url=LANGFUSE_BASE_URL,
    )
    try:
        capture_prompts(client)
    except Exception as exc:
        print(f"Could not capture prompts (is Langfuse up? {LANGFUSE_BASE_URL}): {exc}")
        return 1
    finally:
        client.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
