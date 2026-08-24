# DEMO.md — Conference Walkthrough Script

A step-by-step guide for presenting the Agentic Hybrid Search agent at a technical conference or lecture. Use this script to showcase all key features in ~15–20 minutes with compelling live demonstrations.

**Setup**: Before the demo, ensure the application is running locally:

```bash
cd langchain_agent
./scripts/start.sh  # Starts Docker, backend on :8000, frontend on :5173
```

Open browser to **<http://localhost:5173>** and keep DevTools hidden (press `F12` to toggle).

---

## Demo Overview

### Timeline

- **Intro** (1 min): What we're building
- **Intent Classification** (2 min): Show 6 intents with different queries
- **Hybrid Search** (2 min): Demonstrate α (alpha) weighting
- **Quality Gate Retry** (2 min): Trigger low-confidence → retry
- **Observable Events** (1 min): Real-time pipeline visualization
- **Q&A** (balance of time)

---

## Part 1: Introduction (1 min)

**Slide/Visual**: Show the Mermaid diagram from README.md

**Narration**:

> "This is **Agentic Hybrid Search** — a production-grade RAG agent for e-commerce product discovery. It's built on LangGraph, uses hybrid search (vector + lexical), and leverages LLM-based reranking.
>
> The unique feature here is **dynamic alpha weighting** — the system automatically balances semantic understanding and exact keyword matching based on the query type. Watch as we demo this in action."

**Action**: Let the frontend load (show Chat Panel + Observability Panel side-by-side).

---

## Part 1.5: Typeahead Autocomplete (1–2 min)

**Narration**:

> "Before we even submit a query, the search bar itself is intelligent.
> Watch the dropdown as I type."

### Demo: prefix matches

**Type** (but don't submit): `wire`

**Observe**: Dropdown opens with a **Suggestions** section showing
wireless headphones, wireless mice, etc. — these come from a
`GET /api/suggest` request that edge-ngram prefix-matches against product
titles and brands.

### Demo: spell correction

**Type**: `nikey` (intentional typo)

**Observe**: Top of the dropdown shows a **Did you mean? nike** row — the
backend ran Levenshtein + SequenceMatcher ratio checks and returned a
correction. Distance-1 typos also benefit from a fuzzy fallback when the
prefix query returns nothing.

### Demo: recent searches + keyboard nav

**Observe**: After a few submitted queries, the dropdown shows a **Recent
Searches** section (localStorage, max 8, case-insensitive dedup, clear
button). Use `ArrowDown`/`ArrowUp` to navigate, `Enter` or `Tab` to accept
and submit, `Esc` to close. The whole surface uses ARIA combobox semantics.

**Narration**:

> "Three sections — Did you mean?, Suggestions, Recent Searches — all
> backed by `/api/suggest`. Stale requests are cancelled via
> `AbortController`, and correction is intentionally skipped when the
> query is already a corpus token or a prefix of a word, so in-progress
> typing like 'adi' isn't corrected to 'addi'."

---

## Part 2: Intent Classification (2 min)

**Narration**:

> "The agent classifies every query into one of 6 intents. This drives how we search and what we return. Let me show you each one."

### Query 1: Search Intent

**Send**: `Find me wireless headphones under $100`

**Expected**: Intent = `search`, α = LLM-assigned (likely 0.65–0.75, semantic-heavy)

**Observe**:

- Intent Classifier step shows "search" with keyword fast-path
- Query Evaluator step shows assigned α and reasoning
- Knowledge Search retrieves relevant headphones
- Observability panel shows each stage in real-time

**Narration**:

> "This is a **search intent** — open-ended product discovery. The system detects this, assigns a high α (0.7) to favor semantic understanding over exact keywords, and retrieves products by meaning."

---

### Query 2: Comparison Intent

**Send**: `Compare Sony WH-1000XM5 vs Bose QuietComfort 45`

**Expected**: Intent = `comparison`, α = 0.60 (fast-path, semantic-heavy)

**Observe**:

- Intent Classifier shows keyword match ("vs" pattern), confidence ~0.95
- Query Evaluator assigns α=0.60 instantly (fast-path, no LLM)
- Knowledge Search retrieves both specific models
- Results ranked by comparison relevance

**Narration**:

> "**Comparison intent** — users want to pit products against each other. We detect this with a keyword pattern, assign a fixed alpha, and the LLM-based reranker scores each product's relevance to both products."

---

### Query 3: Attribute Filter Intent

**Send**: `Show me blue running shoes size 10`

**Expected**: Intent = `attribute_filter`, α = 0.25 (fast-path, lexical-heavy)

**Observe**:

- Intent Classifier detects attribute keywords (brand + color + size)
- Query Evaluator assigns α=0.25 (lexical-heavy fast-path)
- Knowledge Search prioritizes exact attribute matching
- BM25 scores keywords heavily

**Narration**:

> "**Attribute filter intent** — specific product characteristics. We favor **lexical search** (α=0.25) because users are looking for exact colors, sizes, brands. The agent filters the catalog with precision."

---

### Query 4: Refinement Intent (Context-Aware)

**Send**: `Show me blue running shoes` (first search)

Then immediately: `Make them waterproof` (refinement)

**Expected**:

- First query: `search` intent, fresh retrieval
- Second query: `refinement` intent, constrains prior results

**Observe**:

- First retrieval shows blue running shoes
- Second retrieval narrows to waterproof variants **from the prior set**
- Quality Gate validates continuity (category match)
- Refinement uses α=0.35 (lexical-heavy) to filter existing results

**Narration**:

> "**Refinement intent** — users add constraints to a prior search. The system detects this, validates that we're in the same product category, and constrains the retrieval to the prior results. If the user pivots categories, we reset."

---

### Query 5: Follow-Up Intent (Vague)

**Send**: `What about the next one?` (after prior search)

**Expected**: Intent = `follow_up`, triggers query expansion

**Observe**:

- Intent Classifier detects vagueness ("next one", "that", "does it")
- Query Evaluator expands the query using conversation history
- Expanded query shown in observability panel
- Retrieval works with enriched context

**Narration**:

> "**Follow-up intent** — users reference prior results vaguely. The system resolves pronouns like 'that,' 'the next one,' 'does it' using conversation history, expanding 'What about the next one?' to 'What about the next blue running shoe?'."

---

### Query 6: Summary Intent

**Send**: `Summarize what we've discussed`

**Expected**: Intent = `summary`, bypasses retriever, LLM summarizes conversation

**Observe**:

- Intent Classifier detects "summarize", "what did we...", "recap"
- Skips retriever/reranker
- Agent node generates summary from conversation history
- Observability panel shows fewer steps

**Narration**:

> "**Summary intent** — we can ask the agent to recap. It doesn't retrieve new products; instead, it synthesizes what we've already discussed."

---

## Part 3: Hybrid Search & Alpha Weighting (2 min)

**Narration**:

> "The magic of this system is **hybrid search** — we combine vector embeddings (semantic meaning) and BM25 (exact terms) using Reciprocal Rank Fusion.
>
> The **alpha parameter** (0.0 to 1.0) controls the balance. Let me show you how this adapts to query intent."

### Demo: Same Query, Different Alpha Values

**Send**: `gifts for photographers` (naturally conceptual query)

**Expected**: α ≈ 0.75 (semantic-heavy), retrieves by meaning (tripods, lighting, camera bags)

**Observe**:

- Query Evaluator shows α=0.75, reasoning: "Conceptual, gift-based query"
- Knowledge Search shows OpenSearch query with RRF fusion
- Results are conceptually related (meaning-driven)

**Narration**:

> "For a conceptual gift query, we use **α=0.75** — favor semantics. The system retrieves photography-adjacent products (tripods, camera bags, lighting) even if they don't share exact keywords."

---

## Part 4: Quality Gate Retry (2 min)

**Narration**:

> "The **Quality Gate** is a safety mechanism. If the reranker assigns low confidence scores (<0.5), we retry with an adjusted alpha instead of returning poor results."

### Trigger a Retry

**Send**: `laptop sleeve for a 17-inch computer running Linux with RGB lighting and waterproof`

(This is intentionally complex/niche to trigger low confidence)

**Expected**:

- Retriever fetches candidates with initial α
- Reranker scores them low (< 0.5)
- Quality Gate detects low max_score
- Retrieves again with adjusted α (opposite direction)
- New results score higher

**Observe** in Observability Panel:

1. Intent Classifier: `attribute_filter` or `search`
2. Query Evaluator: α assigned
3. Knowledge Search: First retrieval
4. Reranker: Scores shown, max_score < 0.5 highlighted
5. Quality Gate: **"Retrying with adjusted alpha"** message
6. Knowledge Search (again): Second retrieval with new α
7. Reranker (again): New scores, max_score > 0.5
8. Agent: Final response generated

**Narration**:

> "The query is complex with niche attributes. The first retrieval scored poorly (0.42 max). The Quality Gate detected this, adjusted alpha from 0.35 → 0.65 (favor semantics), and re-retrieved. Second round scored better (0.68). This avoids returning low-confidence results."

---

## Part 5: Observable Events (1 min)

**Narration**:

> "Every pipeline step emits **observable events** — structured Pydantic models streamed over WebSocket. The observability panel visualizes them in real-time. This is how you see what the agent is thinking at every step."

**Action**: Send any query and point out:

1. **Intent Classifier Event**: Intent detected, confidence score
2. **Query Evaluator Event**: Alpha assigned, reasoning, expanded query if applicable
3. **OpenSearch Query Event**: Full DSL, α value, intent
4. **Reranker Event**: Per-document scores
5. **Quality Gate Event**: Pass / retry / accept decision
6. **LLM Response Chunk Event**: Token-by-token generation (streaming)
7. **Search Optimizations card**: expandable panel showing BM25
   enhancements applied to this query — synonyms, fuzzy matching, phrase
   boosting, field boosting, and phonetic matching (`double_metaphone`
   via the `analysis-phonetic` OpenSearch plugin)

**Narration**:

> "This real-time pipeline visibility is invaluable for debugging and for understanding what the system is doing. In production, you'd log these events to trace why a query succeeded or failed."

---

## Part 6: Q&A (Balance of Time)

### Likely Questions & Answers

**Q: What models are you using?**

A: Gemini 3 Flash for generation, Gemini 3.1 Flash Lite for classification/reranking (faster, cheaper), text-embedding-005 for embeddings (768-dim). All via Google AI.

**Q: How does RRF fusion actually work?**

A: For each document, we compute `score = 1/(rank_vector + 60) + 1/(rank_lexical + 60)`. It normalizes ranks from both search methods without requiring probability calibration.

**Q: Can I use a different LLM (OpenAI, Anthropic)?**

A: Yes! It's pluggable. We guide the setup in `CONTRIBUTING.md`. You'd swap `ChatGoogleGenerativeAI` for `ChatOpenAI` and update models in config.

**Q: How do you handle conversation memory?**

A: LangGraph checkpoints in PostgreSQL. Every response is saved; next turn loads the prior state. For long chats, context compaction trims older messages.

**Q: What's the latency breakdown?**

A: Typical flow: Intent (10–500ms) → Query Eval (10–500ms) → Retrieval (200–500ms) → Reranking (1–2s) → Agent (3–8s). Total: ~6–15s. Cached embeddings save ~2–3s.

**Q: How many products are in the index?**

A: We use Amazon ESCI dataset (~1.2M US products). Demo often uses a 10K sample for faster setup, but can scale to full million.

**Q: Does this work for non-e-commerce domains?**

A: Absolutely. Replace ESCI products with your own documents (news articles, internal wiki, research papers). The RAG pipeline is domain-agnostic.

**Q: Can I fine-tune the reranker?**

A: The current reranker uses LLM-based scoring (no fine-tuning needed). But you could swap for a trained cross-encoder. Setup guide in `CONTRIBUTING.md`.

---

## Part 7: Closing Remarks (1 min)

**Narration**:

> "This system demonstrates several state-of-the-art techniques:
>
> 1. **Intent routing** — tailors search strategy to query type
> 2. **Dynamic alpha** — adapts semantic/lexical balance
> 3. **Quality gates** — automatically retries if confidence is low
> 4. **Observable events** — gives visibility into every decision
>
> The architecture is fully documented in the GitHub repo: comprehensive docstrings, ARCHITECTURE.md for deep-dives, and CONTRIBUTING.md for extending it.
>
> Thanks for watching!"

---

## Post-Demo: GitHub Tour (Optional)

If time permits, show:

1. **README.md** — System overview, example queries, performance table
2. **ARCHITECTURE.md** — Deep-dive diagrams, node descriptions
3. **main.py** — Show the LangGraph pipeline code structure
4. **tests/** — Demonstrate the test suite (unit/integration/e2e)

---

## Troubleshooting During Demo

### If frontend doesn't load

```bash
# Restart the dev server
make dev
```

### If backend is slow/timing out

- Check OpenSearch is running: `docker ps`
- Restart services: `./scripts/stop.sh && ./scripts/start.sh`

### If observability panel doesn't show events

- Check WebSocket connection (DevTools → Network → WS)
- Verify `GOOGLE_API_KEY` is set

---

## Tips for Smooth Delivery

1. **Practice beforehand** — Run through all 6 intents at least once
2. **Use realistic queries** — Avoid edge cases; pick queries that work reliably
3. **Highlight the observability panel** — That's where the "wow" moment is
4. **Show error recovery** — Quality gate retry is impressive
5. **Keep chat history clean** — Start fresh each intent demo to avoid context confusion
6. **Speak to the implications** — "This is how we avoid low-quality results," "This is how we adapt to user intent"

---

## Demo Script Variants

### Quick Demo (5–8 min)

- Intent: search + comparison + quality gate retry
- Focus on hybrid search & quality gate

### Full Demo (15–20 min)

- All 6 intents
- Hybrid search
- Quality gate retry

### Deep-Dive Demo (30+ min)

- All of above
- Show code: main.py, architecture
- Run tests live
- GitHub tour
- Q&A

---

## Post-Demo Resources

Point the audience to:

- **GitHub Repo**: <https://github.com/kmwtechnology/opensearch2026-agentic-search>
- **ARCHITECTURE.md**: Deep-dive on pipeline design
- **CONTRIBUTING.md**: How to extend (add intents, nodes, events)
- **README.md**: Quick start, deployment instructions
- **Docstrings**: Every module has comprehensive docstrings
