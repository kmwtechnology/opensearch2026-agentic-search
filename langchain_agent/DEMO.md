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
- **Agentic Enrichment Flywheel** (2–3 min): Agent fixes a real data gap live, twice
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

## Part 4.5: The Agentic Enrichment Flywheel (2–3 min) — THE centerpiece

**This is the "agents fix data quality, not just adjust queries" moment.**
Unlike the quality gate retry (which adjusts *how* we search), this shows
the agent noticing the *catalog itself* is missing a real color or material
term, teaching the search system about it, and re-indexing the whole
catalog live — genuinely, not simulated.

**Setup requirement**: `ENABLE_ENRICHMENT_TOOL=true` must be set in the
environment before starting the backend (default is `false`). Restart
`make dev-api` after setting it if the backend was already running.

**Mechanism** (for your own understanding, not to narrate verbatim):
Both color and material are detected live from product text
(`chunk_text`) by one generic Lucille stage, with the variant→canonical
taxonomy stored in OpenSearch — not a static file. When `attribute_filter`
intent extracts a **color** term that isn't in the taxonomy yet, the
exact-match filter against it returns nothing on the first pass, which
triggers the agent's gap-detection and offers `trigger_enrichment`. An
unrecognized **material** term instead falls back to a soft lexical match
and can also get relaxed away by the retriever's own "no dead-end results"
safety net — so material's gap can't reliably surface through natural
conversation (see Act 2 below); it's triggered directly via the admin
endpoint instead, exercising the identical underlying mechanism. Either
way, `trigger_enrichment(attribute_type, variant, canonical)` — a real
tool/endpoint, not a canned response — writes the new mapping to
OpenSearch and triggers an actual full Lucille reindex of the whole
9,618-product catalog (~15–20s, measured — not a mock, not a scoped patch).

**Both taxonomies are genuinely gap-tested and rehearsed** (this session,
2026-08-31) against the real dataset — the exact wording below reflects
real product titles and real timing, not hypothetical numbers.

### Act 1 — Color: "camel"

**Send**: `camel coat`

**Expected**: `attribute_filter` intent extracts `color: "camel"`. "camel"
isn't in the color taxonomy (102 variants, none of them "camel") — the
exact filter on `product_color_primary="camel"` matches nothing, quality
gate retries, still nothing (max_relevance < 0.10). The agent gets offered
`trigger_enrichment` and — if it recognizes "camel" as a real color — calls
it with `attribute_type="color", variant="camel", canonical="brown"`.

**Observe**:
- Observability panel: new emerald **Enrichment Triggered** card
  (`attribute_type: color`, `variant: "camel"`, `canonical: brown`)
- Agent's response references the fix (e.g. "I've added 'camel' as a
  brown color and updated the catalog...")
- **This takes ~15–20s** (measured: 19.98s and 16.48s across two real runs
  this session) — the agent's response won't appear until the reindex
  completes. Narrate through the wait; don't leave dead air.

**Then re-send**: `camel coat`

**Expected**: Now resolves via the exact filter. Real hero product:
**"Calvin Klein Women's Classic Cashmere Wool Blend Coat, CAMEL, 6"** should
appear, correctly tagged `product_color_primary: brown`.

### Act 2 — Material: "chrome" (triggered via admin endpoint, not live chat)

**Why this act is triggered differently than Act 1**: material's
attribute-filter fallback is deliberately *soft* — an unrecognized
material term falls back to a lexical `multi_match` instead of an
exact-match filter, because the same code path also has to handle
non-material feature words users type ("waterproof", "noise canceling")
that would otherwise get hard-excluded incorrectly. On top of that, the
retriever has a **separate, deliberate filter-relaxation safety net**
(`main.py`, "filter relaxation if <3 results" — see `CLAUDE.md`) that
always drops material/size constraints and retries broader whenever the
fully-filtered count is under 3, specifically to avoid dead-end
"no results" screens. Confirmed live this session: even a material term
with **zero** corpus occurrences (`malachite`) still gets relaxed to 40
returned documents — `Retriever: filter relaxation — 0 doc(s) with full
filters, retrying without material/size constraints`. Between the two
mechanisms, no material term, however rare, can produce a genuine
zero-document `attribute_filter` result through natural conversation. Color
has neither protection (hard exact-match fallback, excluded from
relaxation) — that's exactly why "camel" works live in Act 1 and no
material term ever will, as currently architected.

Rather than compromise material's real-world filtering behavior (which
correctly protects legitimate non-material queries) just to force a demo
moment, Act 2 triggers the same real mechanism directly via the
now-working `/api/admin/enrich` endpoint — still a genuine reindex, still
live on stage, just invoked by you instead of by the LLM's own tool-call
judgment.

**Trigger** (run this live, e.g. from a second terminal or Swagger UI at
`/swagger`):

```bash
curl -s -b <session-cookie-jar> -X POST http://localhost:8000/api/admin/enrich \
  -H "Content-Type: application/json" -H "Origin: http://localhost:8000" \
  -d '{"attribute_type": "material", "variant": "chrome", "canonical": "metal"}'
```

`canonical` is required here — the admin endpoint classifies
dictionary-only (no LLM fallback), so an unrecognized term like "chrome"
needs the bucket supplied explicitly, the same way the live agent tool
supplies its own LLM-classified canonical.

**Expected**: `{"success": true, "reindex_triggered": true,
"reindex_success": true, "docs_processed": 9618, ...}` after ~15–20s
(measured this session: 21.16s).

**Then send in chat**: `chrome bar table`

**Expected**: Real hero product **"Global Furniture Bar Table,
Clear/Black/Chrome"** appears as the top citation, correctly tagged
`product_material_primary: metal` (confirmed live this session).

### Narration

> **Act 1**: "Notice this isn't the agent adjusting *how* it searches —
> like the quality gate retry we just saw. The catalog itself was missing
> this color. The agent recognized a real gap, taught the system about it,
> and re-indexed the whole 9,618-product catalog live. That took about 15
> to 20 seconds — genuinely reprocessing every product, not a shortcut.
> Watch — if I ask the same question again, it works now."
>
> **Act 2**: "Same mechanism, same real reindex — this time triggered
> directly rather than through the chat turn, since material's filter is
> deliberately more forgiving than color's so it doesn't wrongly reject
> legitimate feature words like 'waterproof'. The underlying fix — new
> taxonomy entry, full catalog reindex — is identical."

### Verified this session (2026-08-31), not hypothetical

- Both taxonomies (102 color variants, 34 material variants) were rebuilt
  from scratch via discovery against real product text — not migrated from
  a hand-authored file.
- **Act 1 (color) fully proven end-to-end through real live chat**: sent
  "show me camel colored coats" via `POST /api/chat`, the LLM recognized
  the gap and called `trigger_enrichment(attribute_type="color",
  variant="camel", canonical="brown")` on its own judgment, a real 19.8s
  reindex ran, and a follow-up identical query returned the correctly
  cited, correctly tagged hero product. This required a bug fix — see
  below.
- **Act 2 (material) fully proven end-to-end via the admin endpoint**, not
  live chat — confirmed structurally impossible to trigger through natural
  conversation (see above). Real 21.16s reindex, `docs_processed: 9618`,
  hero product citation confirmed correct afterward.
- **Bug found and fixed this session**: the agent's enrichment-gap check
  originally only fired when `quality_gate_retried and max_relevance <
  threshold`. But `quality_gate_node` deliberately never retries when the
  *first* retrieval pass already returns zero documents (adjusting alpha
  can't fix an exclusionary filter) — so for the exact "unrecognized
  attribute term → hard filter excludes everything on pass one" scenario
  the whole feature exists to address, `quality_gate_retried` never became
  `True` and the tool was never offered. Fixed in `main.py`'s `agent_node`
  by adding a second, OR'd condition (`intent == "attribute_filter" and not
  retrieved_documents`). Full unit suite (813 passed) unaffected.
- The full mechanism (classify → write mapping → ensure index fields →
  regenerate Lucille config → real reindex subprocess → verify field
  population → verify query improvement) was run for real, for both acts,
  this session — not mocked. Both gap terms were reverted afterward
  (mapping deleted, affected documents' fields cleared, one more full
  reindex run) specifically so they'd be fresh for the actual demo.

### Troubleshooting this part specifically

- **Act 1 tool never gets called / agent just gives the canned "no
  results" response**: Confirm `ENABLE_ENRICHMENT_TOOL=true` is actually
  set for the running backend process (`echo $ENABLE_ENRICHMENT_TOOL` in
  the shell that started `make dev-api`, or check `/api/admin/enrich`
  returns something other than 403). If it's set correctly but the LLM
  still doesn't call the tool, confirm intent classified as
  `attribute_filter` in the observability panel and that the retriever log
  shows `hybrid=0 docs` on the first pass — that's the exact signal the
  gap-detection fix above depends on.
- **Act 2 admin curl returns 403**: same `ENABLE_ENRICHMENT_TOOL` check as
  above. If it returns 422, the request body is missing `attribute_type`,
  `variant`, or (for an unrecognized term) `canonical`.
- **Act 2 admin curl returns `success: false`**: the `canonical` value
  isn't one of the material taxonomy's known buckets (`leather`, `cotton`,
  `wool`, `synthetic`, `denim`, `canvas`, `wood`, `metal`, `glass_ceramic`,
  `rubber` — see `MATERIAL_CANONICALS` in `attribute_discovery.py`), or the
  variant is already mapped (check `reason` in the response body).
- **Reindex takes noticeably longer than ~20s live**: Docker image layer
  cache may be cold (first run after a restart rebuilds a Maven layer,
  ~1–4s extra) — acceptable, but if it's dramatically slower, check
  `docker ps` / OpenSearch health before going live.
- **Gap terms already resolved (from a prior rehearsal)**: Re-run the
  revert procedure — delete the `color#camel` / `material#chrome` mapping
  docs from `agentic_hybrid_search_attribute_mappings`, clear
  `product_color`/`product_color_primary` (or the material equivalents)
  from the affected documents via `update_by_query`, then run
  `bash scripts/lucille_ingest.sh --skip-judgments` once more. See this
  session's transcript or `enrichment_service.py`'s test file for the exact
  Painless scripts used.

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
   boosting, and field boosting

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

**Q: Is the reindex you just showed actually processing the whole catalog, or just the affected products?**

A: The whole catalog — a real, full Lucille pipeline run (~15–20s for 9,618 products), not a scoped patch. We measured that a full reindex is fast enough to run live, so there's no need for a narrower, faster-but-less-authentic mechanism. The Lucille pipeline config itself is generated fresh before every run from whatever attribute types are currently registered in OpenSearch — a brand-new attribute type (not just color/material) would need zero hand-edited config to be picked up.

**Q: What stops the agent from writing garbage into the taxonomy?**

A: A few guardrails: the canonical bucket the agent chooses is validated against a fixed, bounded list per attribute type (it can't invent a new category on the fly); the mapping write is idempotent (won't duplicate or corrupt an existing entry); and the tool is gated behind an explicit `ENABLE_ENRICHMENT_TOOL` flag, off by default.

**Q: Does this work for attributes beyond color and material?**

A: Architecturally, yes — the detection stage is one generic, parameterized Lucille class, not a dedicated class per attribute type. Adding a new attribute type is a matter of registering it in the OpenSearch-backed mapping store; the next reindex picks it up automatically. This demo only wires up color and material end-to-end, though.

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
> 4. **Agentic enrichment** — the agent fixes real catalog gaps live, not just query-side workarounds
> 5. **Observable events** — gives visibility into every decision
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
- **Agentic enrichment flywheel — Act 1 only (color)**, if time allows
- Focus on hybrid search & quality gate

### Full Demo (15–20 min)

- All 6 intents
- Hybrid search
- Quality gate retry
- **Agentic enrichment flywheel — both acts**

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
