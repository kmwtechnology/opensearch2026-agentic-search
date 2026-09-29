"""The eight LangGraph pipeline nodes and their helpers.

`PipelineNodesMixin` is mixed into `main.EcommerceSearchAgent`; every method here
expects the attributes `initialize_components` sets up (llm, vector_store,
reranker, judge, ...). The graph wiring and routers stay in main.py.
"""

import asyncio
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict, List, Optional, Sequence, Tuple

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from pydantic import BaseModel

from api.schemas.events import (
    HybridSearchResultEvent,
    LLMResponseChunkEvent,
    LLMResponseStartEvent,
    OpenSearchQueryEvent,
    QueryExpansionEvent,
    RerankerProgressEvent,
    RerankerStartEvent,
    SearchCandidate,
    SearchProgressEvent,
)
from core.agent_state import CustomAgentState
from core.config import (
    ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS,
    ANSWER_STREAM_TAG,
    CROSS_ENCODER_MODEL,
    DEFAULT_ALPHA,
    EVALUATOR_FALLBACK_ALPHA,
    INTERNAL_LLM_TAG,
    RERANKER_FETCH_K,
    RERANKER_TOP_K,
    RETRIEVER_FETCH_K,
    RETRY_FETCH_MULTIPLIER,
)
from observability.llm_content import _flatten_llm_content
from pipeline import enrichment_events
from quality.enrichment_value_judge import EnrichmentValueJudge
from quality.judge import RETRY_ELIGIBLE_CATEGORIES, LLMJudge
from retrieval.attribute_discovery import CANONICALS_BY_TYPE, single_term_classify

logger = logging.getLogger(__name__)

# Fixed alpha (and the reasoning shown in the UI) for intents that skip the LLM estimator.
_FIXED_ALPHA_BY_INTENT = {
    "comparison": (
        0.60,
        "Comparison query: prioritizing semantic search for quality/feature differences",
    ),
    "attribute_filter": (
        0.25,
        "Attribute filter query: prioritizing lexical search for exact attribute matches",
    ),
    "refinement": (
        0.35,
        "Refinement query: preserving category context while matching new attribute constraint",
    ),
}


# Reranker top-score floor per intent below which the quality gate retries.
_QUALITY_THRESHOLD_BY_INTENT = {
    "comparison": 0.55,
    "attribute_filter": 0.45,
    "refinement": 0.45,
    "search": 0.50,
    "follow_up": 0.50,
}


class AlphaEstimation(BaseModel):
    alpha: float
    reasoning: str


class IntentClassification(BaseModel):
    intent: str
    reasoning: str
    confidence: float
    clarifying_questions: list[str] = []


class PipelineNodesMixin:
    """Pipeline node methods for EcommerceSearchAgent (see module docstring)."""

    # Declared (not assigned) so mypy can type the lazily-initialized judges
    # that EcommerceSearchAgent.__init__ sets to None and the nodes build on
    # first use. Everything else the nodes touch is inferred from usage.
    judge: Optional[LLMJudge]
    enrichment_value_judge: Optional[EnrichmentValueJudge]

    # ========================================================================
    # AGENT GRAPH NODES FOR DYNAMIC QUERY EVALUATION
    # ========================================================================

    def intent_classifier_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Classify the latest user message with one structured LLM call.

        Intents: search, comparison, attribute_filter, refinement, follow_up, summary.
        Confidence below 0.7 routes to `agent` (as `clarify`) for a clarifying
        question. Also resets the per-turn hallucination-retry guard.
        """
        messages = state["messages"]
        user_query = ""
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage) and hasattr(msg, "content") and msg.content:
                user_query = _flatten_llm_content(msg)
                break

        intent, reasoning, confidence, clarifying_questions = self._classify_intent(
            user_query, messages
        )
        logger.info(
            f"Intent classification: intent={intent}, confidence={confidence:.2f}, query={user_query[:50] if user_query else '<empty>'}..."
        )

        # Category continuity check for refinements. Skipped for tag disputes
        # ("that's not tan, that's tagged yellow"): the category extractor's LLM
        # fallback invents a category for them, which would downgrade the turn to
        # `search` and skip the taxonomy-correction tool.
        if intent == "refinement" and not self._detect_correction_signal(user_query):
            prior_docs = state.get("prior_search_documents", [])
            if prior_docs:
                # Validate category continuity
                continuity_score, category_reasoning = self._validate_category_continuity(
                    prior_docs, user_query, []
                )

                # If categories are very different, downgrade to search
                if continuity_score < 0.3:
                    logger.info(
                        f"Category continuity check failed ({continuity_score:.2f}): {category_reasoning} → downgrading to search"
                    )
                    intent = "search"
                    reasoning = (
                        f"{category_reasoning}. Treating as new search instead of refinement."
                    )
                    confidence = 0.95  # High confidence that this is a new search
                # If ambiguous, lower confidence to trigger clarification
                elif continuity_score < 0.7:
                    logger.info(
                        f"Category continuity ambiguous ({continuity_score:.2f}): {category_reasoning}"
                    )
                    confidence = min(confidence, 0.65)
                    reasoning = f"{category_reasoning}. Need clarification on intent."

        return {
            "intent": intent,
            "user_query": user_query,
            "reasoning": reasoning,
            "confidence": confidence,  # For UI display
            "intent_confidence": confidence,
            "clarifying_questions": clarifying_questions,
            # Checkpointed state would otherwise carry a spent retry into every later turn.
            "hallucination_retry_used": False,
        }

    def query_evaluator_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Choose the hybrid-search alpha (0 = pure BM25, 1 = pure vector).

        Comparison, attribute_filter and refinement intents take a fixed alpha with
        no LLM call; search and follow_up ask the LLM, falling back to the
        collection default on any failure.

        Returns `alpha` and `query_analysis` (the reasoning, shown in the UI).
        """
        start_time = time.time()
        default_alpha = EVALUATOR_FALLBACK_ALPHA

        last_user_msg = None
        for msg in reversed(state["messages"]):
            if isinstance(msg, HumanMessage):
                last_user_msg = _flatten_llm_content(msg)
                break

        if not last_user_msg:
            return {"alpha": default_alpha, "query_analysis": "No query detected"}

        intent = state.get("intent", "search")

        fixed = _FIXED_ALPHA_BY_INTENT.get(intent)
        if fixed:
            alpha, reasoning = fixed
            logger.info(
                f"Query evaluation (fixed alpha, {intent}): alpha={alpha:.2f}, elapsed={time.time() - start_time:.3f}s"
            )
            return {"alpha": alpha, "query_analysis": reasoning}

        if intent == "follow_up":
            intent_guidance = "\nNOTE: This is a FOLLOW_UP query continuing a previous search. Analyze query semantics and adjust alpha to refine previous results."
        else:
            intent_guidance = "\nNOTE: This is a general SEARCH query. Analyze semantics to determine optimal balance between exact matching and conceptual relevance."

        evaluation_prompt = f"""Determine the optimal alpha for hybrid search on this query.{intent_guidance}

=== YOUR TASK ===
Query to analyze: "{last_user_msg}"

=== ALPHA GUIDE (0.0=pure lexical/BM25, 1.0=pure semantic/vector) ===
- 0.00-0.15: PURE LEXICAL - Exact product model numbers, ASINs, UPCs, brand+model combos
- 0.15-0.40: LEXICAL-HEAVY - Brand + category, specific features, color/size combos
- 0.40-0.60: BALANCED - Feature comparisons, activity-based product queries, how-to usage
- 0.60-0.75: SEMANTIC-HEAVY - Conceptual needs, occasion-based queries, comfort/quality focus
- 0.75-1.0: PURE SEMANTIC - Gift ideas, mood/style queries, open-ended exploration

=== EXAMPLES ===
"Sony WH-1000XM5" → alpha=0.05 (exact model number needs exact match)
"B07XJ8C8F5" → alpha=0.05 (ASIN identifier, pure lexical)
"Samsung noise cancelling headphones" → alpha=0.25 (brand + feature, lexical-heavy)
"blue running shoes size 10" → alpha=0.30 (specific attributes, lexical-heavy)
"best headphones for long flights" → alpha=0.55 (activity-based, balanced)
"comfortable office chair for back pain" → alpha=0.65 (conceptual need, semantic-heavy)
"good gift ideas for music lovers" → alpha=0.85 (open-ended exploration, semantic)

=== OUTPUT ===
Respond with ONLY valid JSON. The "reasoning" MUST describe the actual query "{last_user_msg}", not copy example text.

{{"alpha": <0.0-1.0>, "reasoning": "<1 sentence about THIS specific query>"}}
"""

        structured_llm = self.alpha_structured or self.llm.with_structured_output(AlphaEstimation)
        try:
            result = self._invoke_with_timeout(
                structured_llm, evaluation_prompt, ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS
            )
            alpha = max(0.0, min(1.0, result.alpha))
            reasoning = result.reasoning or "No reasoning provided"
            logger.info(
                f"Query evaluation (LLM): alpha={alpha:.2f}, elapsed={time.time() - start_time:.3f}s"
            )
            logger.debug(f"Query evaluation details: reasoning={reasoning}, query={last_user_msg}")
            return {"alpha": alpha, "query_analysis": reasoning}
        except Exception as e:
            # Timeout, LLM error, or malformed output: the default alpha still yields a usable search.
            logger.warning(
                "Query evaluation failed",
                extra={
                    "error": repr(e),
                    "elapsed_ms": int((time.time() - start_time) * 1000),
                    "fallback_alpha": default_alpha,
                },
            )
            return {"alpha": default_alpha, "query_analysis": f"Evaluation failed: {e}"}

    @staticmethod
    def _build_grounded_context(documents: List[Document]) -> str:
        """Render documents as numbered FACTS blocks with hard per-product boundaries.

        Shared by the agent prompt and the judge's regeneration helper so both
        ground on identical text.
        """
        if not documents:
            return "No relevant documents were found."

        blocks = []
        sep = "═══════════════════════════════════════════════════════════"
        for i, doc in enumerate(documents, 1):
            title = doc.metadata.get("title", "(untitled)")
            product_id = doc.metadata.get("product_id") or "—"
            brand = doc.metadata.get("product_brand") or ""
            color = doc.metadata.get("product_color") or ""
            color_category = doc.metadata.get("product_color_primary") or ""
            score = doc.metadata.get("reranker_score") or doc.metadata.get("retrieval_score") or 0.0

            facts: List[str] = [f"  Title: {title}"]
            if brand:
                facts.append(f"  Brand: {brand}")
            if color:
                facts.append(f"  Color (as listed): {color}")
            if color_category:
                facts.append(f"  Color category (indexed): {color_category}")
            content = (doc.page_content or "").strip()
            if content:
                facts.append(f"  Description: {content}")

            blocks.append(
                f"{sep}\n"
                f"[Product {i}] product_id={product_id} (relevance: {score:.3f})\n"
                f"FACTS — only the lines below count as supported context for this product:\n"
                + "\n".join(facts)
            )
        return "\n".join(blocks) + f"\n{sep}"

    # Markdown links: [text](url). DOTALL so multi-line link text still matches.
    _MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\(\s*<?https?://[^)\s]+>?\s*\)", re.DOTALL)
    # Bare http(s) URLs (with optional surrounding ** or angle brackets).
    _BARE_URL_RE = re.compile(r"<?\*{0,2}https?://\S+?\*{0,2}>?(?=[\s.,;:!?)\]]|$)")

    @staticmethod
    def _citation_url_for_doc(doc: Document) -> Optional[str]:
        """Explicit `metadata['url']`, else an Amazon search by title (robust to delisted
        ASINs), else by product_id; None when the document has none of them."""
        url = doc.metadata.get("url")
        if url:
            return url

        from urllib.parse import quote_plus

        title = doc.metadata.get("title", "")
        if title:
            return f"https://www.amazon.com/s?k={quote_plus(title)}"

        product_id = doc.metadata.get("product_id", "")
        if product_id:
            return f"https://www.amazon.com/s?k={quote_plus(product_id)}"

        return None

    @staticmethod
    def _strip_inline_links(text: str) -> str:
        """Collapse `[text](url)` to `text` and drop bare URLs from LLM output.

        The prompt forbids URLs (the model hallucinates ASINs); this catches any that slip through.
        """
        if not text or "http" not in text:
            return text
        cleaned = PipelineNodesMixin._MARKDOWN_LINK_RE.sub(r"\1", text)
        cleaned = PipelineNodesMixin._BARE_URL_RE.sub("", cleaned)
        return cleaned

    @staticmethod
    def _format_search_results(documents: List[Document], user_query: Optional[str]) -> str:
        """Plain markdown result list, in reranked order; the judge's fallback baseline."""
        if not documents:
            return (
                f"No products found for **{user_query or 'your search'}**.\n\n"
                "Try a different keyword or relax your filters."
            )

        header = (
            f"### Search results for *{user_query}*  \n*{len(documents)} products*\n\n"
            if user_query
            else f"### Search results  \n*{len(documents)} products*\n\n"
        )

        rows = []
        for i, doc in enumerate(documents, 1):
            title = doc.metadata.get("title") or "(untitled product)"
            brand = doc.metadata.get("product_brand") or doc.metadata.get("brand")
            url = doc.metadata.get("url") or ""
            reranker_score = doc.metadata.get("reranker_score")
            retrieval_score = doc.metadata.get("retrieval_score")
            snippet = (doc.page_content or "").strip().replace("\n", " ")
            if len(snippet) > 240:
                snippet = snippet[:240].rstrip() + "…"

            meta_bits = []
            if brand:
                meta_bits.append(f"**Brand:** {brand}")
            if reranker_score is not None and reranker_score > 0:
                meta_bits.append(f"**Reranker Score:** {reranker_score:.3f}")
            elif retrieval_score is not None and retrieval_score > 0:
                meta_bits.append(f"**Score:** {retrieval_score:.3f}")
            meta_line = " · ".join(meta_bits)

            heading = f"**{i}. [{title}]({url})**" if url else f"**{i}. {title}**"
            block = [heading]
            if meta_line:
                block.append(meta_line)
            if snippet:
                block.append(snippet)
            rows.append("\n\n".join(block))

        return header + "\n\n---\n\n".join(rows)

    async def aagent_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Run agent_node in a worker thread so a scoped re-tag (synchronous OpenSearch
        calls) cannot block the event loop and starve WebSocket frames.

        asyncio.to_thread copies the context, so LangChain callbacks and the
        ContextVar emit bridge reach the worker unchanged.
        """
        return await asyncio.to_thread(self.agent_node, state)

    def agent_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Answer from the retrieved documents, or ask for clarification / run a taxonomy tool."""
        # Read at call time: tests patch core.config.ENABLE_ENRICHMENT_TOOL.
        from core.config import ENABLE_ENRICHMENT_TOOL

        start_time = time.time()
        messages = list(state["messages"])
        retrieved_documents = state.get("retrieved_documents", [])
        intent = state.get("intent", "question")
        summary_text = state.get("summary_text")

        if intent == "summary" and summary_text:
            logger.info("Agent: summary intent detected, returning cached summary")
            return {"messages": [AIMessage(content=summary_text)], "citations": []}

        # Handle clarify intent - ask user for more context
        if intent == "clarify":
            clarifying_questions = state.get("clarifying_questions", [])
            if clarifying_questions:
                questions_text = "\n".join(f"- {q}" for q in clarifying_questions)
                clarify_response = (
                    "I'd love to help you find the right product! A few details would let me "
                    "give you better recommendations:\n\n"
                    f"{questions_text}\n\n"
                    'You could also try a more specific search like "wireless headphones under '
                    '$100" or "running shoes for flat feet" — I can take it from there.'
                )
            else:
                clarify_response = (
                    "I'd love to help! To point you at the right products, could you share a "
                    "little more about what you're looking for? For example:\n\n"
                    '- A category or use case ("headphones for the gym", "a gift for a coffee lover")\n'
                    "- A brand, color, or feature you care about\n"
                    "- Who it is for, or the occasion\n\n"
                    "Even a rough idea helps me narrow things down."
                )
            logger.info(
                f"Agent: clarify intent detected, asking {len(clarifying_questions)} questions"
            )
            return {"messages": [AIMessage(content=clarify_response)], "citations": []}

        logger.info(f"Agent: processing with {len(retrieved_documents)} retrieved documents")

        # Extract user query
        user_query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                user_query = _flatten_llm_content(msg)
                break

        # Taxonomy correction: the shopper disputes a tag from a prior turn. Checked
        # before gap detection because it is independent of this turn's retrieval.
        if (
            ENABLE_ENRICHMENT_TOOL
            and intent in ("refinement", "follow_up")
            and self._detect_correction_signal(user_query)
        ):
            correction_result = self._try_correction_tool(messages, user_query)
            if correction_result is not None:
                logger.info("Agent: taxonomy correction triggered via trigger_enrichment")
                return correction_result
            # LLM declined: not a search failure, so fall through to normal generation.

        MIN_RELEVANCE_THRESHOLD = 0.10  # also the citation cutoff below
        quality_gate_retried = state.get("quality_gate_retried", False)
        max_relevance = max(
            (doc.metadata.get("reranker_score", 0.0) for doc in retrieved_documents),
            default=0.0,
        )

        # Two retrieval failures signal a taxonomy gap: (1) documents scored poorly even
        # after a quality-gate retry; (2) an attribute_filter's hard filter excluded
        # everything on the first pass (the quality gate never retries that), which is
        # what an unrecognized color/waterproof term produces.
        retry_exhausted_gap = quality_gate_retried and max_relevance < MIN_RELEVANCE_THRESHOLD
        zero_result_filter_gap = intent == "attribute_filter" and not retrieved_documents

        if retry_exhausted_gap or zero_result_filter_gap:
            logger.info(
                f"Agent: retrieval failed "
                f"(retry_exhausted_gap={retry_exhausted_gap}, "
                f"zero_result_filter_gap={zero_result_filter_gap}, "
                f"max_relevance={max_relevance:.3f} < {MIN_RELEVANCE_THRESHOLD})"
            )

            if ENABLE_ENRICHMENT_TOOL:
                enrichment_result = self._try_enrichment_tool(user_query)
                if enrichment_result is not None:
                    return enrichment_result

            no_info_response = (
                f"I searched for \"{user_query or 'your question'}\" but didn't find a strong "
                "match in the catalog. A few things that usually help:\n\n"
                '- Try a more specific phrase — a brand ("Sony"), a use case '
                '("wireless earbuds for running"), or a feature ("noise cancelling")\n'
                "- Add a color, a feature (like waterproof), or a size\n"
                "- Or describe who it's for and what they'd use it for, and I'll suggest "
                "categories worth exploring\n\n"
                "Want to try one of those?"
            )
            return {"messages": [AIMessage(content=no_info_response)], "citations": []}

        context = self._build_grounded_context(retrieved_documents)

        # url -> (label, doc indices, asin, image_url). Citations dedup by title-derived
        # URL, keeping the first product seen for a URL; asin and image_url let the UI
        # render each citation as a product card.
        citations_dict: Dict[str, Tuple[str, List[int], str, str]] = {}

        # max_relevance (computed above) < cutoff means nothing is worth citing.
        MIN_CITATION_RELEVANCE = MIN_RELEVANCE_THRESHOLD

        if max_relevance >= MIN_CITATION_RELEVANCE:
            for i, doc in enumerate(retrieved_documents, 1):
                doc_score = doc.metadata.get("reranker_score", 0.0)
                if doc_score < MIN_CITATION_RELEVANCE:
                    continue

                url = self._citation_url_for_doc(doc)
                if not url:
                    continue
                if url in citations_dict:
                    citations_dict[url][1].append(i)
                    continue
                label = doc.metadata.get("title") or "(untitled product)"
                citations_dict[url] = (
                    label,
                    [i],
                    doc.metadata.get("product_id", "") or "",
                    doc.metadata.get("image_url", "") or "",
                )
        else:
            logger.info(
                f"Suppressing citations: max_relevance={max_relevance:.3f} < {MIN_CITATION_RELEVANCE}"
            )

        citations = []
        for url, (label, indices, asin, image_url) in citations_dict.items():
            index_prefix = ",".join(str(idx) for idx in indices)
            citation: Dict[str, str] = {"label": f"[{index_prefix}] {label}", "url": url}
            if asin:
                citation["asin"] = asin
            if image_url:
                citation["image_url"] = image_url
            citations.append(citation)

        recent_context = self._build_recent_context(messages)
        recent_context_block = f"Recent context:\n{recent_context}\n\n" if recent_context else ""

        # Intent-specific instructions
        if intent == "comparison":
            intent_instruction = """Your task is to COMPARE the retrieved products, highlighting key differences and trade-offs:
- Discuss quality, features, performance, and other relevant dimensions
- Help the user understand which product is best for their specific needs
- Clearly indicate product names and key differentiators
- Use a structured format (e.g., "Product A is better for X because..., while Product B excels at Y...")"""
        elif intent == "attribute_filter":
            intent_instruction = """Your task is to filter and present products matching specific criteria:
- Focus on products that match the requested attributes (color, size, features, etc.)
- For each product, clearly state which attributes it matches and which it doesn't
- Recommend the best matches first
- Be specific: e.g., "This product comes in blue and is listed in size 10"
- If some requested attributes aren't available, note that clearly"""
        elif intent == "refinement":
            prior_docs = state.get("prior_search_documents", [])
            prior_category = (
                self._extract_product_category_from_documents(prior_docs) if prior_docs else ""
            )
            prior_count = len(prior_docs)

            category_context = (
                f"From the {prior_count} {prior_category}"
                if prior_category
                else f"From the {prior_count} products"
            )

            intent_instruction = f"""Your task is to narrow the prior search results by applying the user's new constraint:
- Start with explicit context: "{category_context} I showed you earlier, here are the ones that match your new criteria:"
- State the new constraint being applied: "...filtering for [new attribute]..."
- List ONLY products that satisfy BOTH the original search AND the new constraint
- Where possible, cross-reference against products mentioned in the previous response
- If a previously recommended product also meets the new constraint, highlight it: "Notably, [Product X] from my earlier recommendations also meets this requirement"
- If no products satisfy both criteria, be honest: "None of the {prior_category} options I found earlier are [attribute]. Here are the closest matches..."
- Be specific about which attribute is being filtered (e.g., "waterproof", "under $100", "leather")"""
        elif intent == "follow_up":
            intent_instruction = """Your task is to refine your previous search results based on the user's follow-up:
- Connect this response to your previous recommendation(s)
- Address what the user is asking for (a different color, other features, etc.)
- Clearly show how new suggestions compare to earlier recommendations"""
        else:  # search (default)
            intent_instruction = """Your task is to help the user find products matching their needs:
- Recommend relevant products from the knowledge base
- Explain why each product is a good match for their stated needs
- Include key product features and specifications
- Help them make an informed decision"""

        system_prompt = f"""You are a helpful e-commerce product search assistant. Answer questions using a knowledge base of Amazon product listings.
{recent_context_block}RETRIEVED DOCUMENTS FROM KNOWLEDGE BASE:
{context}

INTENT: {intent.upper()}
{intent_instruction}

GROUNDING RULES (override creativity preferences — non-negotiable):
1. Every factual claim about a specific product (origin / "Made in X", material, certifications like "FDA-approved" or "BPA-free", size, manufacturer claims) MUST be supported by THAT product's FACTS block above.
1a. NEVER mention price, cost, budget, "cheaper", "affordable", "value for money", or any currency amount — not for a product, not as a comparison, not as a follow-up question, and not as a suggestion for how to narrow the search. This catalog carries NO price data in any field, so anything you say about price is invented, and a made-up dollar figure is the single most damaging thing you can put on screen. If the user asks about price or asks for something cheaper, say plainly that you do not have pricing information, then help them on an attribute you DO have (color, size, brand, feature, waterproofing).
2. Facts are PER-PRODUCT. If "Made in USA" appears in Product 3's FACTS but not in Product 1's FACTS, you MUST NOT attribute "Made in USA" to Product 1, even if it's the same brand or category.
3. If a fact is not in any FACTS block, OMIT it. Do not infer from brand reputation, product category, prior knowledge, or implication.
4. Comparison tables/summaries: every cell or claim must trace to a specific product's FACTS block. Leave cells blank rather than fabricating.
5. When writing about a product, prefer paraphrasing its FACTS over inventing supporting language.
6. When a product's FACTS include both "Color (as listed)" and "Color category (indexed)", compare them. If the indexed category is a color family the listed color could plausibly belong to (e.g. "Navy" under "blue", "Charcoal" under "black"), say nothing about it. If the indexed category is NOT a plausible family for the listed color (e.g. "Tan" indexed under "yellow" — tan is a shade of brown, not yellow), explicitly flag this as a possible data-tagging issue for that product, using the literal values from its FACTS block.

LENGTH — this is read aloud off a projector, so be brief:
- Open with ONE sentence that answers the question. No preamble, no restating the question, no "Great choice!" or "I'd love to help".
- Then a MARKDOWN BULLET LIST of at most 3 products — this must be a real list, one bullet per product, never a paragraph with the names run together. Exactly this shape:

  - **Product Name** — short clause naming only what makes it a match.

  One sentence per bullet. No sub-bullets, no headings, no "Details:" / "Matches:" / "Size:" labels, and no blank lines between bullets.
- Aim for under 100 words total. Stop when the question is answered — do not add a closing offer, a follow-up question, or a summary of what you just said.
- Exception: if nothing relevant was found, say so in one sentence and suggest two alternative searches. That case may end with a question.
- BREVITY NEVER OVERRIDES GROUNDING RULE 6. If a product's listed color and its indexed color category disagree implausibly, you MUST say so — omitting it hides a real data defect from the person who could report it. State it ONCE, as a single clause, using the literal values (e.g. "all of these are listed Tan but indexed as yellow, which looks like a tagging error"). Do not repeat it on every product line; if it applies to several, say so once and name them collectively.

CITATION & STYLE:
- Cite products descriptively by name (e.g., "the Nylabone 3 Pack Puppy Chew listing"), never as "Document N".
- DO NOT include URLs, hyperlinks, or markdown links (e.g., `[name](url)`) in your response. The system appends a verified "Sources" list separately — any link you write yourself will be wrong because you do not have access to canonical product URLs.
- Refer to products by name only. Do not write `https://...`, `amazon.com/...`, `[text](http...)`, or any link-shaped text.
- If you cannot find relevant products, explain what you searched for, suggest two or three alternative searches the user could try (different brand, broader category, related use case), and end with an open question that invites them to share more about what they need.
- Tone: plain and direct, like a knowledgeable friend who respects your time — helpful without being chatty. Avoid dismissive phrasing ("you need to narrow down", "I can't help with that"), but do not pad with enthusiasm, apologies, or filler either. Warmth comes from being useful, not from extra words.
"""

        llm_messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query or "Please summarize the context."),
        ]

        # Tokens go out over the socket as they stream; response_streamed tells
        # observable_agent not to re-send the finished text at node end.
        response = self._stream_llm_response_simple(llm_messages)

        # The generated `citations` are the only link surface; strip any URLs the model wrote.
        if hasattr(response, "content") and isinstance(response.content, str):
            stripped = self._strip_inline_links(response.content)
            if stripped != response.content:
                logger.info("Agent: stripped inline URLs from LLM response")
                response = AIMessage(content=stripped)

        elapsed = time.time() - start_time
        logger.info(f"Agent: generated response ({len(response.content)} chars) in {elapsed:.3f}s")

        return {"messages": [response], "citations": citations, "response_streamed": True}

    def _try_enrichment_tool(
        self, user_query: Optional[str], prompt: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Offer the LLM `trigger_enrichment` on a detected taxonomy gap (or, with an
        explicit `prompt`, a disputed tag; see _try_correction_tool).

        A manual two-call loop (bind tools, execute the one tool call, invoke again
        without tools for the final text) rather than a ToolNode, which would change
        the graph topology around quality_gate and llm_judge.

        Returns None if the LLM declined to call the tool, else a full agent_node return dict.
        """
        from quality.enrichment_service import enrich_attribute
        from tools.enrichment_tool import format_enrichment_message, trigger_enrichment

        gap_prompt = (
            prompt or f"""A shopper searched for "{user_query or 'their query'}" and the catalog \
search returned no strong matches, even after retrying with adjusted search weighting.

If the query plausibly mentions a COLOR term or a WATERPROOF/water-resistance requirement that \
a product catalog should recognize but might not have in its current taxonomy (e.g. an unusual \
color name, or "waterproof"/"water-resistant"/"weatherproof" as a feature the shopper needs), \
you may call trigger_enrichment to add it and re-index the catalog live.

Only call the tool if you're genuinely confident the query contains a real color term or a \
genuine waterproofing requirement worth adding — not for typos, brand names, or unrelated \
words. If nothing in the query looks like a color/waterproof gap, don't call the tool; just say \
so briefly."""
        )

        llm_with_tools = self.llm.bind_tools([trigger_enrichment])
        tool_messages = [HumanMessage(content=gap_prompt)]
        # INTERNAL_LLM_TAG keeps a declining call's prose out of the chat stream.
        response = llm_with_tools.invoke(tool_messages, config={"tags": [INTERNAL_LLM_TAG]})

        tool_calls = getattr(response, "tool_calls", None)
        if not tool_calls:
            return None

        call = tool_calls[0]
        logger.info(f"Agent: trigger_enrichment called with args={call['args']}")

        attribute_type = call["args"].get("attribute_type", "")
        variant = call["args"].get("variant", "")
        canonical = call["args"].get("canonical", "")

        if self.enrichment_value_judge is None:
            from core.config import JUDGE_MODEL

            self.enrichment_value_judge = EnrichmentValueJudge(model_name=JUDGE_MODEL)

        from retrieval.attribute_mapping_store import AttributeMappingStore

        current_mapping = (
            AttributeMappingStore().get_lookup_table(attribute_type).get(variant.lower())
            if attribute_type and variant
            else None
        )
        assessment = self.enrichment_value_judge.evaluate(
            attribute_type=attribute_type,
            variant=variant,
            canonical=canonical,
            current_mapping=current_mapping,
            context=user_query or "",
        )
        if not assessment.is_meaningful:
            logger.info(f"Agent: declined trigger_enrichment — {assessment.reasoning}")
            # Published only for a judge rejection, never for the LLM merely not calling
            # the tool (the correction gate is broad; that would narrate noise).
            enrichment_events.publish(
                status="declined",
                attribute_type=attribute_type,
                variant=variant,
                canonical=canonical,
                error=assessment.reasoning,
            )
            decline_response = AIMessage(
                content=(
                    f"I looked into this, but I don't think changing "
                    f"'{variant}' would meaningfully improve search results "
                    f"right now — {assessment.reasoning} I'll leave the "
                    "catalog as-is for this one."
                )
            )
            return {
                "messages": [decline_response],
                "citations": [],
                "enrichment_triggered": False,
            }

        # Call enrich_attribute() directly (not trigger_enrichment.invoke()) to get the
        # structured result without a second re-index. Announce first: the re-index
        # blocks for seconds and this is the UI's only signal that work is underway.
        # `corrected_from` is sent only for a real correction: when the canonical
        # matches what is on file, enrich_attribute writes nothing.
        started_corrected_from = current_mapping if current_mapping != canonical else None
        enrichment_events.publish(
            status="started",
            attribute_type=attribute_type,
            variant=variant,
            canonical=canonical,
            corrected_from=started_corrected_from,
        )

        enrichment_result = enrich_attribute(attribute_type, variant, explicit_canonical=canonical)

        enrichment_events.publish(
            status="complete" if enrichment_result.reindex_success else "failed",
            attribute_type=attribute_type,
            variant=variant,
            canonical=enrichment_result.canonical or canonical,
            corrected_from=enrichment_result.corrected_from,
            error=enrichment_result.reindex_error,
            reindex_mode=enrichment_result.reindex_mode,
            duration_seconds=(
                enrichment_result.duration_seconds if enrichment_result.reindex_success else None
            ),
            docs_processed=(
                enrichment_result.docs_processed if enrichment_result.reindex_success else None
            ),
            docs_scanned=(
                enrichment_result.docs_scanned if enrichment_result.reindex_success else None
            ),
        )

        tool_result = format_enrichment_message(enrichment_result)
        tool_messages.append(response)
        tool_messages.append(ToolMessage(content=tool_result, tool_call_id=call["id"]))

        final_response = self.llm.invoke(tool_messages)

        return {
            "messages": [final_response],
            "citations": [],
            "enrichment_triggered": True,
        }

    # Deliberately broad pre-filter for "might be disputing a taxonomy tag": a false
    # positive costs one LLM call that declines, a false negative drops a real correction.
    _CORRECTION_SIGNAL_PHRASES = (
        "that's not",
        "thats not",
        "that isn't",
        "that is not",
        "isn't really",
        "isn't actually",
        "doesn't look",
        "does not look",
        "not really",
        "actually",
        "mistag",
        "miscategor",
        "incorrectly tagged",
        "wrong color",
        "should be tagged",
        "tagged wrong",
        "that's wrong",
        "thats wrong",
        "not correct",
    )

    def _detect_correction_signal(self, user_query: Optional[str]) -> bool:
        """Keyword gate run before any LLM call, so ordinary follow-ups skip the correction prompt."""
        if not user_query:
            return False
        q = user_query.lower()
        return any(phrase in q for phrase in self._CORRECTION_SIGNAL_PHRASES)

    def _try_correction_tool(
        self, messages: Sequence[BaseMessage], user_query: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """Offer trigger_enrichment for a correction: the shopper disputes a tag from a
        prior turn, so this fires regardless of this turn's retrieval.

        Reuses _try_enrichment_tool with a correction-framed prompt; enrich_attribute
        overwrites the existing mapping when the LLM proposes a different canonical.
        """
        history = self._build_recent_context(messages, limit=8)

        correction_prompt = f"""A shopper is following up on a previous product search. Their \
latest message may be disputing or correcting a color or waterproof tag the catalog assigned to \
a product you showed them earlier in this conversation.

Recent conversation:
{history}

Latest message: "{user_query}"

If the shopper is disputing a color or waterproof tag as WRONG (they may name the wrong tag \
explicitly, e.g. "that's not tan, that's tagged yellow which is wrong" -- here the shopper is \
telling you "yellow" is the INCORRECT tag, not proposing it as the fix), and you can tell from \
the conversation which term is mistagged and what the correct canonical bucket should be, call \
trigger_enrichment with:
- attribute_type: "color" or "waterproof"
- variant: the term that's currently mistagged (e.g. "tan")
- canonical: the CORRECT canonical bucket it should map to instead

Determine the correct canonical from the actual product descriptions shown earlier in this \
conversation (e.g. a product listed "Tan/Brown" or "Dark Tan Leather" indicates the correct \
canonical is "brown") -- never from the shopper's message alone. The canonical you propose MUST \
be different from whatever tag the shopper is disputing as wrong; proposing the same value back \
is not a correction and will be rejected.

Only call the tool if you're genuinely confident this is a real tagging correction — not a \
typo, a brand-new search, or an unrelated complaint. If you're not sure, don't call the tool; \
just respond to the shopper normally."""

        return self._try_enrichment_tool(user_query, prompt=correction_prompt)

    def _build_recent_context(self, messages: Sequence[BaseMessage], limit: int = 6) -> str:
        """Short history block from the most recent messages, excluding the current query."""
        if not messages:
            return ""

        history_entries: list[str] = []
        recent_messages = list(messages)

        if recent_messages and isinstance(recent_messages[-1], HumanMessage):
            recent_messages = recent_messages[:-1]

        for msg in reversed(recent_messages):
            content = getattr(msg, "content", "")
            if not content or not str(content).strip():
                continue
            label = self._label_for_message(msg)
            history_entries.append(f"{label}: {str(content).strip()}")
            if len(history_entries) >= limit:
                break

        history_entries.reverse()
        return "\n".join(history_entries)

    def _expand_vague_query(self, query: str, messages: Sequence[BaseMessage]) -> str:
        """Rewrite a vague follow-up ("those but blue") into a self-contained query, or return it unchanged."""
        # User turns only: AI product listings bloat the query and trip maxClauseCount.
        user_messages = [m for m in messages if isinstance(m, HumanMessage)]
        context = self._build_recent_context(user_messages, limit=4)
        if not context:
            return query

        prompt = f"""Given the conversation context and a follow-up message, determine if the message needs expansion to be self-contained.

USER MESSAGE: "{query}"

CONVERSATION CONTEXT:
{context}

TASK:
If the message references previous context (pronouns, comparisons, vague mentions), rewrite it to be self-contained.
Otherwise, return it unchanged.

RULES:
- Replace pronouns ("it", "them", "those") with actual names from context
- Expand vague references ("For a wedding", "In winter") with previous topic context
- For comparisons ("Which is cheaper?"), include what's being compared
- If already self-contained, return unchanged

Return ONLY the query text, nothing else."""

        try:
            response = self._invoke_with_timeout(
                self.alpha_estimator_llm, prompt, ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS
            )
            expanded = _flatten_llm_content(response).strip().strip("\"'")

            if not expanded or len(expanded) > 500:
                return query

            if expanded != query:
                logger.info(f"Query expansion: '{query}' → '{expanded}'")
                self._emit_event_from_sync(
                    QueryExpansionEvent(
                        original_query=query,
                        expanded_query=expanded,
                        expansion_reason="Follow-up expanded with conversation context",
                    )
                )

            return expanded
        except Exception as e:
            logger.warning(f"Query expansion failed: {e}, using original query")
            return query

    def _extract_product_category_from_documents(self, docs: List[Document]) -> str:
        """Infer the primary category ("boots", "headphones", ...) from the first 5 titles; "" if unknown."""
        if not docs:
            return ""

        try:
            titles = [
                doc.metadata.get("title", "") for doc in docs[:5] if doc.metadata.get("title")
            ]

            if not titles:
                return ""

            prompt = f"""Based on these product titles, what is the primary product category?
Answer with ONLY the category name in lowercase (e.g., boots, headphones, shoes, dresses).
Do not include any explanation.

Titles:
{chr(10).join(titles)}"""

            response = self._invoke_with_timeout(
                self.alpha_estimator_llm, prompt, ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS
            )
            category = _flatten_llm_content(response).strip().lower()

            # A short name (multi-word allowed: "trail running shoes"), not an explanation.
            if category and len(category) < 50 and category.count(" ") <= 2:
                return category

            return ""
        except Exception as e:
            logger.debug(f"Category extraction from documents failed: {e}")
            return ""

    def _extract_product_category_from_query(self, query: str) -> str:
        """Category named in the query: keyword patterns first, then the LLM; "" if none."""
        if not query:
            return ""

        query_lower = query.lower()

        category_patterns = {
            "boots": ["boot", "bootie", "ankle boot"],
            "shoes": ["shoe", "sneaker", "loafer", "heel", "pump"],
            "headphones": ["headphone", "earbud", "earphone", "headset", "wireless"],
            "dresses": ["dress", "gown", "evening", "cocktail", "maxi"],
            "shirts": ["shirt", "t-shirt", "top", "blouse"],
            "pants": ["pant", "trouser", "jean", "jeans", "legging"],
            "jackets": ["jacket", "coat", "blazer", "cardigan"],
            "watches": ["watch", "smartwatch", "timepiece"],
            "bags": ["bag", "purse", "backpack", "handbag", "tote"],
            "electronics": ["phone", "laptop", "tablet", "computer", "device"],
        }

        for category, keywords in category_patterns.items():
            if any(kw in query_lower for kw in keywords):
                return category

        try:
            prompt = f"""What product category does this query mention?
Answer with ONLY the category name in lowercase (e.g., boots, headphones, shoes, dresses).
If no specific category is mentioned, respond with empty string.
Do not include any explanation.

Query: "{query}" """

            response = self._invoke_with_timeout(
                self.alpha_estimator_llm, prompt, ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS
            )
            category = _flatten_llm_content(response).strip().lower()

            if category and len(category) < 50 and category.count(" ") <= 2:
                return category
        except Exception as e:
            logger.debug(f"Category extraction from query (LLM) failed: {e}")

        return ""

    def _validate_category_continuity(
        self,
        prior_docs: List[Document],
        current_query: str,
        current_results: List[Document],
    ) -> Tuple[float, str]:
        """Score (0-1) whether the query continues the prior search, from category match
        and, when `current_results` is given, product-id overlap. Returns (score, reasoning);
        > 0.7 strong continuity, 0.3-0.7 ambiguous, < 0.3 a new search."""
        if not prior_docs:
            return 0.5, "No prior search context available"

        scores = []
        reasons = []

        # 1. Category name matching
        prior_category = self._extract_product_category_from_documents(prior_docs)
        current_category = self._extract_product_category_from_query(current_query)

        if prior_category and current_category:
            if prior_category == current_category:
                scores.append(1.0)
                reasons.append(f"Category match: {prior_category} == {current_category}")
            elif self._are_related_categories(prior_category, current_category):
                scores.append(0.7)
                reasons.append(f"Related categories: {prior_category} ≈ {current_category}")
            else:
                scores.append(0.0)
                reasons.append(f"Different categories: {prior_category} ≠ {current_category}")
        elif current_category:
            scores.append(0.5)
            reasons.append(f"Could not extract prior category, current: {current_category}")

        # Document-id overlap counts only when there are current results to compare:
        # scoring "no results yet" as 0% overlap would sink every refinement whose
        # category can't be keyword-matched (e.g. a tag dispute).
        prior_ids = {
            doc.metadata.get("product_id") for doc in prior_docs if doc.metadata.get("product_id")
        }
        if prior_ids and current_results:
            current_ids = {
                doc.metadata.get("product_id")
                for doc in current_results
                if doc.metadata.get("product_id")
            }
            overlap = len(prior_ids & current_ids) / len(prior_ids)
            scores.append(overlap)
            reasons.append(f"Document overlap: {overlap:.1%} of prior results")

        final_score = sum(scores) / len(scores) if scores else 0.5

        if final_score > 0.7:
            conclusion = "Strong category continuity - treating as refinement"
        elif final_score > 0.3:
            conclusion = "Ambiguous category continuity - need clarification"
        else:
            conclusion = "Different product categories - treating as new search"

        full_reasoning = f"{conclusion} (score: {final_score:.2f}). " + "; ".join(reasons)

        logger.info(f"Category continuity check: {full_reasoning}")

        return final_score, full_reasoning

    @staticmethod
    def _are_related_categories(cat1: str, cat2: str) -> bool:
        """Check if two categories are related (e.g., 'boots' and 'shoes')."""
        related_groups = [
            {"boots", "shoes", "sneakers", "heels", "loafers"},
            {"headphones", "earbuds", "earphones", "headsets"},
            {"dresses", "gowns", "shirts", "tops", "blouses"},
            {"pants", "trousers", "jeans", "leggings"},
        ]

        for group in related_groups:
            if cat1 in group and cat2 in group:
                return True
        return False

    @staticmethod
    def _classify_attribute(attribute_type: str, term: str) -> Optional[str]:
        """Resolve an LLM-extracted color/waterproof term against the OpenSearch-backed taxonomy.

        None for unresolved terms; callers then hard-filter on the raw term, because a
        novel term is exactly the gap the enrichment flywheel grows. No LLM here: this is
        the query-time read path.
        """
        canonical_seeds = CANONICALS_BY_TYPE.get(attribute_type)
        if canonical_seeds is None:
            return None

        try:
            from retrieval.attribute_mapping_store import AttributeMappingStore

            lookup = AttributeMappingStore().get_lookup_table(attribute_type)
        except Exception as exc:  # noqa: BLE001 - OS unreachable falls back to lexical
            logger.debug(f"'{attribute_type}' taxonomy lookup unavailable, using fallback: {exc}")
            lookup = {}

        return single_term_classify(term, canonical_seeds, existing_lookup=lookup)

    def _invoke_with_timeout(self, llm, prompt: str, timeout_seconds: float):
        """Invoke an LLM off-thread with a hard wall-clock bound.

        Raises ``concurrent.futures.TimeoutError``; the orphaned call finishes in the
        background rather than blocking the node.
        """
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(llm.invoke, prompt)
            return future.result(timeout=timeout_seconds)
        finally:
            executor.shutdown(wait=False)

    def _extract_attributes(self, query: str) -> list:
        """OpenSearch filter clauses (implicitly AND'd) for brand, color, waterproof, feature and size; [] if none."""
        if not query or len(query) < 5:
            return []

        prompt = f"""Extract product attributes from a shopping query. Return ONLY a JSON object.

QUERY: "{query}"

Extract these attributes if present:
- brand: Product brand/manufacturer (e.g., "Sony", "Apple", "Nike")
- color: Product color (e.g., "blue", "black", "red", "white", "silver")
- waterproof: "waterproof" if the query expresses a waterproofing / water-resistance
  requirement (e.g., "waterproof", "water resistant", "water-resistant", "weatherproof",
  "water repellent"), else null
- feature: Any OTHER physical feature or material keyword users add as constraints,
  EXCLUDING waterproofing (e.g., "breathable", "insulated", "vegan leather", "leather",
  "mesh", "wireless", "noise canceling", "anti-slip", "slip-resistant", "Gore-Tex")
- size: Size specification (e.g., "size 10", "XL", "large", "medium", "10.5")

Return ONLY a JSON object (use null for missing attributes):
{{"brand": "...", "color": "...", "waterproof": null, "feature": "...", "size": "..."}}"""

        try:
            try:
                response = self._invoke_with_timeout(
                    self.alpha_estimator_llm, prompt, ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS
                )
            except FutureTimeoutError:
                logger.warning(
                    "Attribute extraction timed out after %.1fs -- proceeding without "
                    "attribute filters",
                    ALPHA_ESTIMATOR_CALL_TIMEOUT_SECONDS,
                )
                return []
            text = _flatten_llm_content(response).strip()

            json_match = re.search(r"\{.*?\}", text, re.DOTALL)
            if not json_match:
                return []

            attributes = json.loads(json_match.group())
            filters = []

            def _coerce(val: Any) -> Optional[str]:
                """LLM values to a clean string or None.

                Lists are joined (a list in a multi_match ``query`` is an OpenSearch error).
                Bools are dropped: str(False) is a truthy "False" that would hard-filter to
                zero results and falsely trip the zero-result taxonomy-gap signal.
                """
                if val is None or isinstance(val, bool):
                    return None
                if isinstance(val, list):
                    parts = [
                        str(v).strip()
                        for v in val
                        if v not in (None, "") and not isinstance(v, bool)
                    ]
                    return " ".join(parts) if parts else None
                s = str(val).strip()
                return s or None

            brand = _coerce(attributes.get("brand"))
            if brand:
                filters.append({"match": {"product_brand_normalized": {"query": brand}}})

            # Color and waterproof are hard filters whether or not the term resolves in
            # the taxonomy (the raw term is the fallback). WATERPROOF_CANONICALS ships
            # empty on purpose, so a fresh cluster's "waterproof boots" is a genuine
            # zero-result gap that the enrichment flywheel then fills.
            color = _coerce(attributes.get("color"))
            if color:
                color_canonical = self._classify_attribute("color", color)
                filters.append(
                    {"match": {"product_color_primary": {"query": color_canonical or color}}}
                )

            # The model often answers `waterproof` as a bool: true means the requirement
            # is present (use the term itself); false is dropped by _coerce like null.
            raw_waterproof = attributes.get("waterproof")
            waterproof = "waterproof" if raw_waterproof is True else _coerce(raw_waterproof)
            if waterproof:
                waterproof_canonical = self._classify_attribute("waterproof", waterproof)
                filters.append(
                    {
                        "match": {
                            "product_waterproof_primary": {
                                "query": waterproof_canonical or waterproof
                            }
                        }
                    }
                )

            # Feature and size are soft multi_match clauses: an unrecognized word narrows
            # results without excluding everything the way a hard filter would.
            for attr in ("feature", "size"):
                value = _coerce(attributes.get(attr))
                if value:
                    filters.append(
                        {
                            "multi_match": {
                                "query": value,
                                "fields": ["title", "chunk_text"],
                                "type": "best_fields",
                            }
                        }
                    )

            return filters

        except Exception as e:
            logger.debug(f"Attribute extraction failed: {e}")
            return []

    def _format_filter_summary(self, filters: Optional[List[Dict[str, Any]]]) -> Optional[str]:
        """Human-readable summary of filter clauses, e.g. "color: blue, feature: mesh"."""
        if not filters:
            return None

        parts = []
        for f in filters:
            if "match" in f:
                match_obj = f["match"]
                if "product_brand_normalized" in match_obj:
                    parts.append(f"brand: {match_obj['product_brand_normalized'].get('query', '')}")
                elif "product_color_primary" in match_obj:
                    parts.append(f"color: {match_obj['product_color_primary'].get('query', '')}")
                elif "product_waterproof_primary" in match_obj:
                    parts.append(
                        f"waterproof: {match_obj['product_waterproof_primary'].get('query', '')}"
                    )
            elif "multi_match" in f:
                mm = f["multi_match"]
                if "chunk_text" in mm.get("fields", []) or "title" in mm.get("fields", []):
                    parts.append(f"feature: {mm.get('query', '')}")
        return ", ".join(parts) if parts else None

    def _classify_intent(
        self, user_input: str, messages: Sequence[BaseMessage]
    ) -> tuple[str, str, float, list]:
        """Returns (intent, reasoning, confidence, clarifying_questions); intent is
        "clarify" for a low-confidence first message."""
        prompt = self._build_intent_prompt(user_input, messages)

        structured_llm = self.intent_structured or self.llm.with_structured_output(
            IntentClassification
        )
        try:
            result = structured_llm.invoke(prompt)
            intent = result.intent.strip().lower()
            reasoning = result.reasoning
            confidence = result.confidence
            clarifying_questions = result.clarifying_questions

            # Low confidence asks for clarification, unless a search is already under way:
            # then the message is almost certainly a follow-up, and re-asking is jarring.
            CONFIDENCE_THRESHOLD = 0.7
            if confidence < CONFIDENCE_THRESHOLD and clarifying_questions:
                prior_human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
                has_prior_context = len(prior_human_msgs) > 1
                if has_prior_context:
                    logger.info(
                        f"Low confidence ({confidence:.2f}) but prior context exists — "
                        f"downgrading clarify to follow_up"
                    )
                    return "follow_up", reasoning, confidence, []
                logger.info(f"Low confidence ({confidence:.2f}), will ask for clarification")
                return "clarify", reasoning, confidence, clarifying_questions

            # A refinement needs a prior turn to refine.
            if intent == "refinement":
                prior_human_msgs = [m for m in messages if isinstance(m, HumanMessage)]
                if len(prior_human_msgs) <= 1:
                    logger.info(
                        "Refinement intent with no prior context — downgrading to attribute_filter"
                    )
                    intent = "attribute_filter"

            return intent, reasoning, confidence, clarifying_questions
        except Exception as e:
            logger.error(f"Intent classification failed: {e}")
            return (
                "question",
                f"Classification failed, defaulting to question: {str(e)[:50]}",
                0.5,
                [],
            )

    def _build_intent_prompt(self, user_input: str, messages: Sequence[BaseMessage]) -> str:
        """Build the LLM prompt for intent classification, including recent conversation context."""
        history_block = self._build_recent_context(messages, limit=6)

        # Available intents for e-commerce product search
        available_intents = [
            "search",
            "comparison",
            "attribute_filter",
            "refinement",
            "follow_up",
            "summary",
        ]

        intents_str = "|".join(available_intents)
        example_intent = "search"

        prompt = f"""Classify user intent for e-commerce product search. Return ONLY valid JSON.

CRITICAL - CHECK THESE KEYWORDS FIRST (in order):
1. Is message a short acknowledgment (<5 words: "ok", "got it", "thanks", "understood", "yes", "no", "perfect")? → follow_up (ALWAYS)
2. Does message contain "summarize", "recap", "summary", "what have we covered"? → summary (ALWAYS)
3. Does message compare two or more products? ("Compare X vs Y", "Which is better: X or Y?", "How does X compare to Y?") → comparison (ALWAYS)
4. Does message add a NEW constraint to a PRIOR product search in this conversation? ("they should also be waterproof", "make them under $100", "only in leather", "but size 10", "can they also be breathable?") AND prior search exists in history? → refinement (ALWAYS - takes priority over attribute_filter when prior search exists)
5. Does message add SITUATIONAL or AUDIENCE context to a prior product search? ("my coworkers will be there", "it's an outdoor event", "the venue is fancy", "I'm 5'8\"", "I'll be the host", "it's a daytime event") AND prior search exists? → refinement (ALWAYS — context narrows the prior search even without an explicit product attribute)
6. Does message request products with specific attributes (standalone, no prior context)? ("Show me X in [color/size/brand]", "Find X with [attribute]", "X under/over [price]") → attribute_filter (ALWAYS)
7. Is message vague expansion? ("more", "show", "tell me", "alternatives", "cheaper", "similar", "other options") → follow_up (ALWAYS)
8. Everything else (general product searches) → search (DEFAULT)

IMPORTANT FOR E-COMMERCE:
- "Find wireless headphones" → search (general discovery)
- "Compare Sony vs Bose headphones" → comparison (product comparison)
- "Show me headphones in blue under $100" → attribute_filter (specific attributes, standalone)
- "Oh, they should also be waterproof" (after boot search) → refinement (constraint added to prior search)
- "Make them under $100" (after showing options) → refinement (narrowing prior search)
- "My coworkers will all be there" (after dress search) → refinement (audience context narrows the prior search)
- "It's an outdoor event" (after attire search) → refinement (situational context narrows the prior search)
- "But they need to be waterproof" (no prior context) → attribute_filter (standalone filter)
- "Tell me more about those" → follow_up (vague expansion)

WHEN PRIOR PRODUCT SEARCH EXISTS, prefer follow_up or refinement over clarify — even if the new message is short or doesn't name a product. Only fall back to clarify when the message is genuinely incomprehensible in the surrounding context.

AVAILABLE INTENTS: {intents_str}

OUTPUT FORMAT:
{{
  "intent": "{example_intent}",  // MUST be one of: {intents_str}
  "reasoning": "Brief explanation",
  "confidence": 0.0-1.0,
  "clarifying_questions": ["Question 1?", "Question 2?"]  // Only if confidence < 0.7
}}

CLASSIFICATION RULES:

1. SEARCH: General product discovery and information queries
   - User is looking for products without specific filtering or comparison
   - Examples: "Find wireless headphones", "What are the best gaming laptops?", "Show me running shoes"
   - Key: Open-ended product search - the DEFAULT intent for most queries

2. COMPARISON: User wants to compare two or more products
   - Keywords: "compare", "vs", "versus", "which is better", "how does X compare to Y", "difference between"
   - Examples: "Compare Sony WH-1000XM5 vs Bose QuietComfort 45", "Which is better: Apple Watch or Garmin?"
   - Key: User wants to understand differences/tradeoffs between products

3. ATTRIBUTE_FILTER: User requests products with specific attributes/filters (standalone)
   - Keywords: colors, sizes, brands, prices, features, ranges
   - Examples: "Show me headphones in blue under $100", "Find wireless earbuds with 30+ hour battery", "Running shoes in size 10"
   - Key: User has specific attribute requirements (color/size/brand/price/feature) WITHOUT prior search context
   - Pattern: "[Product] with/in [attribute] [value]" or "[Product] under/over [price]"

4. REFINEMENT: User adds a NEW constraint to a prior product search in this conversation
   - REQUIRES: Conversation history must contain a prior product search
   - Keywords/patterns: "they should also", "but also", "make them", "only if", "can they be", "I want ones that are", implicit constraint additions using pronouns
   - Examples: "Oh, they should also be waterproof" (after "show me men's boots"), "Make them under $100" (after showing headphones), "Can they also be breathable?" (after running shoe search)
   - CONTRAST with ATTRIBUTE_FILTER: "Show me waterproof boots" with NO prior search → attribute_filter
   - CONTRAST with FOLLOW_UP: "Tell me more about those" (vague, no new constraint) → follow_up

5. FOLLOW_UP: Vague continuation/expansion requests that need conversation context
   - Vague expansion: "show me more", "tell me more", "other options", "alternatives", "something cheaper"
   - Short acknowledgments: "ok", "got it", "thanks", "yes", "no"
   - Key: Request only makes sense with conversation history
   - Examples: "Any cheaper alternatives?", "Tell me more about that one", "What else do you have?"

6. SUMMARY: User explicitly requests a recap of the conversation
   - Keywords: "summarize", "recap", "summary", "what have we covered"
   - Examples: "Summarize what we discussed", "What products did we look at?"

PRIORITY ORDER - Check in this exact order:
1. SUMMARY if "summarize", "recap", or "summary" present
2. FOLLOW_UP if very short acknowledgment or vague expansion keyword
3. COMPARISON if "compare", "vs", "which is better", "how does X compare"
4. REFINEMENT if a new constraint is being added to a PRIOR search (check conversation history for prior product search)
5. ATTRIBUTE_FILTER if specific attribute/filter keywords AND no prior search context
6. SEARCH for everything else (DEFAULT)

CONFIDENCE GUIDELINES:
- 0.9-1.0: Very clear intent, unambiguous message
- 0.7-0.9: Reasonably clear, minor ambiguity
- 0.5-0.7: Ambiguous, could be interpreted multiple ways
- 0.0-0.5: Very unclear, need more context

IF CONFIDENCE < 0.7:
- Provide 1-3 clarifying questions in "clarifying_questions" array
- Questions should help disambiguate the user's intent
- Keep questions concise and specific

USER MESSAGE: "{user_input}"

CONVERSATION HISTORY:
{history_block or 'No prior context.'}

Respond with JSON only. No other text."""
        return prompt

    def _label_for_message(self, message: BaseMessage) -> str:
        """Return a human-readable role label for a message (User / Assistant / Tool)."""
        if isinstance(message, HumanMessage):
            return "User"
        if isinstance(message, AIMessage):
            return "Assistant"
        if isinstance(message, ToolMessage):
            tool_name = getattr(message, "tool_name", "tool")
            return f"Tool:{tool_name}"
        if isinstance(message, SystemMessage):
            return "System"
        return "Message"

    def _stream_llm_response_simple(self, messages: Sequence[BaseMessage]) -> AIMessage:
        """Stream the answer, emitting start and chunk events, and return the accumulated AIMessage."""
        stream_start = time.time()

        # Events go through _emit_event_from_sync, which hops back onto the event loop:
        # LangChain's stream callbacks fire on this worker thread and never reach astream_events.
        self._emit_event_from_sync(LLMResponseStartEvent())

        accumulated_content = ""
        chunk_count = 0

        try:
            for chunk in self.llm.stream(messages, config={"tags": [ANSWER_STREAM_TAG]}):
                chunk_count += 1

                if getattr(chunk, "content", None):
                    content = _flatten_llm_content(chunk)
                    if content:
                        accumulated_content += content
                        self._emit_event_from_sync(
                            LLMResponseChunkEvent(content=content, is_complete=False)
                        )

        except StopIteration:
            pass
        except RuntimeError as e:
            if "StopIteration" not in str(e):
                logger.warning(f"RuntimeError during LLM streaming: {e}. Falling back to invoke.")
        except Exception as e:
            logger.warning(f"Exception during LLM streaming: {e}. Falling back to invoke.")

        # If streaming produced no content, fall back to invoke
        if not accumulated_content:
            invoke_result = self.llm.invoke(messages, config={"tags": [ANSWER_STREAM_TAG]})
            if hasattr(invoke_result, "content"):
                accumulated_content = invoke_result.content if invoke_result.content else ""
            else:
                accumulated_content = str(invoke_result)

        stream_elapsed = time.time() - stream_start
        logger.debug(
            f"Streaming complete: {chunk_count} chunks, {len(accumulated_content)} chars in {stream_elapsed:.3f}s"
        )

        return AIMessage(content=accumulated_content)

    def _emit_progress(self, stage: str, message: str) -> None:
        self._emit_event_from_sync(SearchProgressEvent(stage=stage, message=message))

    def _emit_event_from_sync(self, event) -> None:
        """Schedule an event on the running loop from a sync node, without blocking."""
        if not self.emit_callback or not self.event_loop:
            return

        try:
            asyncio.run_coroutine_threadsafe(self.emit_callback(event), self.event_loop)
        except Exception as e:
            logger.debug(f"Could not emit event immediately: {e}, queueing instead")
            self.event_queue.append(event)

    def llm_judge_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """LLM-as-judge for the Pipeline Summary "Generation" stage: compares the agent's
        answer with the raw product list and returns a `JudgmentResult` (verdict, scores,
        hallucinations). Returns `judgment=None` for summary turns, when nothing was
        retrieved, and on enrichment turns."""
        intent = state.get("intent", "search")
        documents = state.get("retrieved_documents") or []

        if intent == "summary" or not documents:
            return {"judgment": None}

        # Enrichment turns are unjudgeable: the load-bearing claim ("tan now maps to
        # brown") is grounded in the tool result, which the judge never sees, so it would
        # be flagged as fabrication and regeneration would rewrite the answer from the
        # documents alone, omitting or even contradicting the correction.
        if state.get("enrichment_triggered"):
            logger.info(
                "llm_judge_node: skipping — enrichment ran this turn, so the "
                "answer is grounded in a tool result rather than in documents."
            )
            return {"judgment": None}

        llm_response = ""
        for msg in reversed(state["messages"]):
            if isinstance(msg, AIMessage) and msg.content and not getattr(msg, "tool_calls", None):
                llm_response = _flatten_llm_content(msg)
                break

        if not llm_response:
            logger.debug("llm_judge_node: no agent response found, skipping judge")
            return {"judgment": None}

        query = state.get("user_query", "")
        baseline = self._format_search_results(documents, query)

        if self.judge is None:
            from core.config import JUDGE_MODEL

            self.judge = LLMJudge(model_name=JUDGE_MODEL)

        t0 = time.time()
        try:
            result = self.judge.judge(query, documents, llm_response, baseline)
        except Exception as exc:
            logger.warning("llm_judge_node failed: %s", exc, exc_info=True)
            return {"judgment": None}

        elapsed_ms = (time.time() - t0) * 1000.0
        logger.info(
            "llm_judge_node: verdict=%s, faithfulness=%.2f, in %.0fms",
            result.verdict,
            result.faithfulness,
            elapsed_ms,
        )

        # Retry once when a flagged claim is fabrication / cross_product_bleed. The
        # category is the gate, not faithfulness (the judge can score 0.9 while flagging a
        # fabrication). Inference/overreach flags reach the UI but skip the slow retry:
        # regenerating those usually makes the answer worse.
        retry_worthy_claims = [
            h for h in result.hallucinations if h.category in RETRY_ELIGIBLE_CATEGORIES
        ]
        retry_eligible = len(retry_worthy_claims) > 0 and not state.get(
            "hallucination_retry_used", False
        )
        if not retry_eligible:
            if result.hallucinations:
                logger.info(
                    "llm_judge_node: skipping retry — %d flag(s) but none are "
                    "fabrication/cross_product_bleed (inference/overreach only).",
                    len(result.hallucinations),
                )
            return {"judgment": result.model_dump()}

        logger.info(
            "llm_judge_node: auto-retrying — faithfulness=%.2f, %d retry-worthy "
            "flag(s) of %d total",
            result.faithfulness,
            len(retry_worthy_claims),
            len(result.hallucinations),
        )
        try:
            corrected = self._regenerate_without_hallucinations(
                query, documents, llm_response, [h.claim for h in retry_worthy_claims]
            )
        except Exception as exc:
            logger.warning("Auto-retry regeneration failed: %s", exc, exc_info=True)
            return {"judgment": result.model_dump()}

        try:
            new_baseline = self._format_search_results(documents, query)
            new_result = self.judge.judge(query, documents, corrected, new_baseline)
        except Exception as exc:
            logger.warning("Auto-retry re-judge failed: %s", exc, exc_info=True)
            return {"judgment": result.model_dump()}

        logger.info(
            "llm_judge_node: retry result faithfulness=%.2f → %.2f, flags %d → %d",
            result.faithfulness,
            new_result.faithfulness,
            len(result.hallucinations),
            len(new_result.hallucinations),
        )
        return {
            "judgment": new_result.model_dump(),
            "original_judgment": result.model_dump(),
            "corrected_response": corrected,
            "hallucination_retry_used": True,
        }

    def _regenerate_without_hallucinations(
        self,
        query: str,
        documents: List["Document"],
        original_response: str,
        hallucinations: List[str],
    ) -> str:
        """Re-prompt the LLM with explicit "do not say X" instructions (no streaming, no state)."""
        forbidden = "\n".join(f"  - {h}" for h in hallucinations)
        context = self._build_grounded_context(documents)
        correction_prompt = f"""Your previous response to "{query}" contained UNSUPPORTED claims that are NOT in the retrieved product descriptions. You MUST omit them and stay strictly grounded.

UNSUPPORTED CLAIMS YOU MADE (do NOT include these in the new response):
{forbidden}

PREVIOUS RESPONSE (for reference — rewrite it without the unsupported claims):
{original_response}

RETRIEVED PRODUCTS:
{context}

GROUNDING RULES (non-negotiable):
- Every factual claim about a specific product must appear in THAT product's FACTS block above.
- Facts are PER-PRODUCT — never transfer a fact from one product's FACTS block to another product.
- If a fact (e.g. "Made in USA", "BPA-free", certifications, country of origin) isn't in a product's FACTS, OMIT it for that product. Do not infer.
- Keep the helpful structure (recommendations, comparisons, summaries) but ground every detail in the FACTS blocks.

Regenerate the response to the original query, removing all unsupported claims. Preserve the helpful synthesis.

Original query: {query}
"""
        messages = [
            SystemMessage(
                content=(
                    "You are a careful product-search assistant. Stay strictly grounded in "
                    "the provided FACTS blocks. Omit any claim you cannot trace to a "
                    "specific product's FACTS."
                )
            ),
            HumanMessage(content=correction_prompt),
        ]
        return _flatten_llm_content(self.llm.invoke(messages))

    def summary_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Summarize the conversation when the intent is `summary`."""
        intent = state.get("intent", "question")
        messages = state["messages"]
        if intent != "summary":
            return {"summary_text": None, "message_count": len(messages)}

        logger.info(f"Generating summary for {len(messages)} messages")
        summary_text = self.summarize_messages(messages)
        if not summary_text:
            summary_text = "No additional context available for summary."
        return {"summary_text": summary_text, "message_count": len(messages)}

    def retriever_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Hybrid (BM25 + vector, RRF) retrieval at the query evaluator's alpha; the LLM is
        used only to rewrite vague follow-ups and extract attribute filters.

        Refinements are constrained to the prior turn's products; summary turns skip retrieval.
        """
        start_time = time.time()
        messages = state["messages"]
        alpha = state.get("alpha", 0.25)
        intent = state.get("intent", "search")

        prior_search_documents = state.get("retrieved_documents", [])
        prior_search_intent = state.get("intent", None)

        if intent == "summary":
            logger.debug("Retriever: skipping hybrid search (intent=summary)")
            return {
                "retrieved_documents": [],
                "prior_search_documents": prior_search_documents,
                "prior_search_intent": prior_search_intent,
            }

        query = None
        for msg in reversed(messages):
            if isinstance(msg, HumanMessage):
                query = _flatten_llm_content(msg)
                break

        if query:
            query = self._expand_vague_query(query, messages)

        if not query:
            logger.warning("Retriever: no user query found in messages")
            return {
                "retrieved_documents": [],
                "prior_search_documents": prior_search_documents,
                "prior_search_intent": prior_search_intent,
            }

        logger.info(f"Retriever: query='{query[:50]}...', alpha={alpha:.2f}")

        attribute_filters = None
        if intent in ("attribute_filter", "refinement"):
            self._emit_progress("attribute_extraction", "Extracting attribute filters...")
            attribute_filters = self._extract_attributes(query)
            if attribute_filters:
                logger.info(f"Retriever: applying {len(attribute_filters)} attribute filter(s)")

        if intent == "refinement" and prior_search_documents:
            prior_product_ids = [
                doc.metadata.get("product_id")
                for doc in prior_search_documents
                if doc.metadata.get("product_id")
            ]
            if prior_product_ids:
                # Constrain by document _id, not a product_id field: the index build used
                # product_id as the _id, so _source.product_id is null and a `terms` filter
                # on it matches nothing.
                product_id_filter = {"ids": {"values": prior_product_ids}}
                if attribute_filters is None:
                    attribute_filters = []
                attribute_filters.append(product_id_filter)
                logger.info(
                    f"Retriever (refinement): constraining to {len(prior_product_ids)} prior search product(s)"
                )

        self._emit_progress("embedding", "Embedding query...")

        # Filled with the DSL body actually sent to OpenSearch, for the observability panel.
        hybrid_capture: Dict[str, Any] = {}

        # On a quality-gate retry, search deeper rather than only re-weighting: alpha alone
        # barely moves the top reranker score (measured identical at alpha 0.1-1.0), while a
        # wider pool can only match or beat the first pass.
        is_gate_retry = bool(state.get("quality_gate_retried", False))
        fetch_k = RETRIEVER_FETCH_K * RETRY_FETCH_MULTIPLIER if is_gate_retry else RETRIEVER_FETCH_K
        k = RERANKER_FETCH_K
        if is_gate_retry:
            k *= RETRY_FETCH_MULTIPLIER
            # Drop soft multi_match filters (feature/size); color, waterproof and brand stay.
            if attribute_filters:
                attribute_filters = [f for f in attribute_filters if "multi_match" not in f]
            logger.info(
                "Retriever: quality-gate retry — widening pool to fetch_k=%d, k=%d "
                "and dropping soft filters",
                fetch_k,
                k,
            )

        retriever = self.vector_store.as_retriever(
            search_kwargs={
                "k": k,
                "fetch_k": fetch_k,
                "alpha": alpha,
                "filters": attribute_filters,
                "capture_body": hybrid_capture,
            },
        )

        self._emit_progress("vector_search", "Searching vector index...")

        retrieve_start = time.time()
        results = retriever.invoke(query)
        retriever_latency_ms = (time.time() - retrieve_start) * 1000.0
        logger.info(f"Retriever: hybrid={len(results)} docs ({retriever_latency_ms:.0f}ms)")

        # Filter relaxation: too few results with soft multi_match filters (feature/size)
        # means they over-constrain, so retry without them. Color, waterproof and brand
        # `match` filters stay.
        MIN_ATTR_FILTER_RESULTS = 3
        if (
            attribute_filters
            and len(results) < MIN_ATTR_FILTER_RESULTS
            and intent in ("attribute_filter", "refinement")
        ):
            hard_filters = [f for f in attribute_filters if "multi_match" not in f]
            if len(hard_filters) < len(attribute_filters):
                logger.info(
                    "Retriever: filter relaxation — %d doc(s) with full filters, "
                    "retrying without feature/size constraints (%d → %d filter(s))",
                    len(results),
                    len(attribute_filters),
                    len(hard_filters),
                )
                relaxed_retriever = self.vector_store.as_retriever(
                    search_kwargs={
                        "k": RERANKER_FETCH_K,
                        "fetch_k": RETRIEVER_FETCH_K,
                        "alpha": alpha,
                        "filters": hard_filters or None,
                        "capture_body": hybrid_capture,
                    },
                )
                relaxed_results = relaxed_retriever.invoke(query)
                if len(relaxed_results) > len(results):
                    results = relaxed_results
                    attribute_filters = hard_filters or None
                    logger.info(
                        "Retriever: relaxation succeeded — %d doc(s) returned",
                        len(results),
                    )

        # `quality_gate_retry` on the second pass lets the UI surface the retry separately.
        self._emit_event_from_sync(
            OpenSearchQueryEvent(
                query=query,
                alpha=alpha,
                filters=attribute_filters,
                filter_summary=self._format_filter_summary(attribute_filters),
                intent=intent,
                query_type="quality_gate_retry" if is_gate_retry else "hybrid",
                body=hybrid_capture.get("body"),
                index=hybrid_capture.get("index"),
                params=hybrid_capture.get("params"),
            )
        )

        self._emit_progress("text_search", "Full-text search complete")
        self._emit_progress("fusion", "Fusing results with Reciprocal Rank Fusion...")

        if results:
            self._emit_event_from_sync(
                HybridSearchResultEvent(
                    candidate_count=len(results),
                    candidates=[
                        SearchCandidate(
                            source=doc.metadata.get("source", "unknown"),
                            snippet=(
                                doc.page_content[:200] + "..."
                                if len(doc.page_content) > 200
                                else doc.page_content
                            ),
                            url=doc.metadata.get("url"),
                        )
                        for doc in results[:10]
                    ],
                )
            )

        elapsed = time.time() - start_time

        logger.info(f"Retriever ({intent}): retrieved {len(results)} documents in {elapsed:.3f}s")

        return {
            "retrieved_documents": results,
            "pre_rerank_documents": list(results),
            "retriever_latency_ms": retriever_latency_ms,
            "prior_search_documents": prior_search_documents,
            "prior_search_intent": prior_search_intent,
            "user_query": query,
            "intent": intent,
        }

    def reranker_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Cross-encoder rerank of the retrieved candidates.

        Every candidate is scored (the UI shows the full ranking); the agent gets the top
        RERANKER_TOP_K. Returns `reranker_max_score` for the quality gate.
        """
        retrieved_documents = state.get("retrieved_documents", [])
        intent = state.get("intent", "search")

        if not retrieved_documents:
            logger.debug(f"Reranker: skipped (intent={intent}, docs={len(retrieved_documents)})")
            return {
                "retrieved_documents": retrieved_documents,
                "reranker_max_score": 0.0,
                "reranker_latency_ms": 0.0,
                "quality_gate_retried": state.get("quality_gate_retried", False),
                "intent": intent,
            }

        query = state.get("user_query", "")
        if not query:
            for msg in reversed(state["messages"]):
                if isinstance(msg, HumanMessage):
                    query = _flatten_llm_content(msg)
                    break

        self._emit_event_from_sync(
            RerankerStartEvent(model=CROSS_ENCODER_MODEL, candidate_count=len(retrieved_documents))
        )

        for i, doc in enumerate(retrieved_documents, 1):
            doc.metadata["original_rank"] = i

        rerank_start = time.time()
        logger.info(
            f"Reranker: processing {len(retrieved_documents)} candidates, "
            f"batch_size={self.reranker.batch_size}, device={self.reranker.device}"
        )
        self._emit_event_from_sync(
            RerankerProgressEvent(
                stage="scoring",
                progress=0.0,
                message=f"Scoring {len(retrieved_documents)} documents...",
            )
        )

        all_scored = self.reranker.score_documents(query, retrieved_documents)
        rerank_elapsed = time.time() - rerank_start

        self._emit_event_from_sync(
            RerankerProgressEvent(
                stage="ranking",
                progress=1.0,
                message=f"Ranking complete - {len(retrieved_documents)} documents scored",
            )
        )

        # The top-K subset shares Document instances with the agent's documents, so these
        # scores carry over to what the agent sees.
        for doc, score in all_scored:
            doc.metadata["reranker_score"] = score

        top = all_scored[:RERANKER_TOP_K]
        results = [doc for doc, _ in top]
        max_score = max((score for _, score in top), default=0.0)
        avg_score = sum(score for _, score in top) / len(top) if top else 0.0
        logger.info(
            f"Reranker ({intent}): complete in {rerank_elapsed:.3f}s, top {len(results)} selected, "
            f"avg_score={avg_score:.4f}, max_score={max_score:.4f}"
        )

        return {
            "retrieved_documents": results,
            "all_reranked_documents": [doc for doc, _ in all_scored],
            "reranker_max_score": max_score,
            "reranker_latency_ms": rerank_elapsed * 1000.0,
            "intent": intent,
        }

    def quality_gate_node(self, state: CustomAgentState) -> Dict[str, Any]:
        """Retry retrieval once, with alpha shifted 0.3 the other way, when the top reranker
        score is under the intent's threshold (comparison 0.55, attribute_filter/refinement
        0.45, else 0.50).

        Every return path sets `quality_gate_status` to "pass" or "retry": a stale "retry"
        in checkpointed state would make the router loop back to the retriever forever.
        """
        from core.config import ENABLE_QUALITY_GATE, QUALITY_GATE_THRESHOLD

        current_alpha = state.get("alpha", DEFAULT_ALPHA)
        max_score = state.get("reranker_max_score", 0.0)
        intent = state.get("intent", "search")

        quality_threshold = _QUALITY_THRESHOLD_BY_INTENT.get(intent, QUALITY_GATE_THRESHOLD)

        def verdict(status: str, reason: str, **extra: Any) -> Dict[str, Any]:
            return {
                "quality_gate_status": status,
                "quality_gate_reason": reason,
                "quality_gate_threshold_used": quality_threshold,
                "reranker_max_score": max_score,
                **extra,
            }

        if not ENABLE_QUALITY_GATE:
            return verdict("pass", "Quality gate disabled in config", quality_gate_retried=False)

        if state.get("quality_gate_retried", False):
            logger.info(
                f"QualityGate: already retried, accepting results (max_score={max_score:.3f})"
            )
            return verdict("pass", f"Accepted after retry (max_score={max_score:.3f})")

        if not state.get("retrieved_documents", []):
            return verdict("pass", "No documents to evaluate", quality_gate_retried=False)

        if max_score >= quality_threshold:
            logger.info(
                f"QualityGate ({intent}): PASS - score {max_score:.3f} above threshold {quality_threshold:.2f}"
            )
            return verdict(
                "pass",
                f"PASS: max_score {max_score:.3f} >= threshold {quality_threshold:.2f}",
                quality_gate_retried=False,
            )

        if current_alpha >= 0.5:
            new_alpha = max(0.0, current_alpha - 0.3)
            direction = "lexical"
        else:
            new_alpha = min(1.0, current_alpha + 0.3)
            direction = "semantic"

        logger.info(
            f"QualityGate ({intent}): RETRY - score {max_score:.3f} below threshold {quality_threshold:.2f}, alpha {current_alpha:.2f} → {new_alpha:.2f} ({direction}-boost)"
        )
        return verdict(
            "retry",
            f"RETRY ({intent}): score {max_score:.3f} < {quality_threshold:.2f}, alpha → {new_alpha:.2f}",
            alpha=new_alpha,
            quality_gate_retried=True,
        )
