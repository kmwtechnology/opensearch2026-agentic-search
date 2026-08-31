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
- **Taxonomy Self-Correction** (2–3 min): Shopper disputes a wrong tag, agent fixes it live
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

## Part 4.5: Taxonomy Self-Correction (2–3 min) — THE centerpiece

**This is the "the agent is confidently wrong, and only a human catches
it" moment.** Earlier demo parts show the system reacting to its own
low confidence (quality gate retry). This part shows something harder:
the catalog has a real, silent data-quality bug that produces a
**passing, above-threshold result** — the automated quality gate can't
see anything wrong, because nothing about the score says so. Only a
shopper who actually looks at the product can catch it. The agent
listens, verifies, and permanently fixes the underlying data live, on
stage — not a scripted response, a real taxonomy write and a real
re-index.

**The real bug**: the color taxonomy (rebuilt from scratch via
discovery against real product text this project cycle) maps the
variant **"tan" to the canonical bucket "yellow"** instead of "brown".
This is objectively wrong — tan is a shade of brown, not yellow — and
it's not a toy example: **29 real products** in the catalog carry this
mis-mapping, including boots, jackets, and bags whose own titles say
"Tan" but whose indexed `product_color_primary` says `yellow`.

**Setup requirement**: must be set in the environment before starting
the backend (defaults to `false`):
```bash
ENABLE_ENRICHMENT_TOOL=true
```
Restart `make dev-api` after setting it if the backend was already
running. Confirm the bug state is loaded before going live — this repo
intentionally ships with `tan → yellow` still in place; if a prior
rehearsal already corrected it, see Troubleshooting below to restore it.

**Mechanism** (for your own understanding, not to narrate verbatim):
`trigger_enrichment(attribute_type, variant, canonical)` — the same real
tool used elsewhere in this codebase to add brand-new taxonomy terms —
also handles **correcting** a term that's already mapped, just to the
wrong bucket. `enrichment_service.enrich_attribute` distinguishes the
two cases: if the requested canonical differs from what's already
stored, it's a correction (tracked via `corrected_from`), not a no-op.
On the conversation side, `main.py`'s `agent_node` has a dedicated
correction-detection branch, separate from the existing zero-result
gap-detection branch: `_detect_correction_signal` is a cheap keyword
pre-filter for dispute language ("that's not right", "mistagged",
"actually that's..."), scoped to `refinement`/`follow_up` intent only
(a fresh, standalone query can't be disputing a prior turn — there's
nothing to dispute yet). When it fires, `_try_correction_tool` builds a
correction-framed prompt including recent conversation history and
offers the LLM the same `trigger_enrichment` tool, which — if the LLM
agrees a real mistagging occurred — writes the corrected mapping and
triggers a genuine full Lucille reindex of the whole 9,618-product
catalog (~19–20s, measured — not a mock, not a scoped patch).

### The demo

**Send**: `show me tan boots`

(Use this exact phrasing — confirmed this session that longer variants
like "show me tan colored boots" cause the query extractor to add a
second, unrelated `material_or_feature: "boots"` filter alongside the
color filter, which dilutes the result set and muddies the before/after
comparison. "show me tan boots" extracts a single clean
`color: "tan"` filter.)

**Expected**: `attribute_filter` intent, filter resolves `tan → yellow`
(the current, wrong mapping), retrieves real product results, reranks,
and **passes the quality gate** — the top result (a Clarks Dark Tan
Leather Boot) scores **~0.56** against a 0.45 threshold for
`attribute_filter` intent. This is the whole point: the system is
**confidently wrong**, not empty-handed. Nothing about this response
looks broken.

**Observe / narrate**: Open the observability panel's citation/DSL
detail for the top result and point out the mismatch directly — the
product's own title says "Tan", but the indexed field the filter
actually matched against is `product_color_primary: yellow`. This is
the moment to ask the audience: "does this look right to you?"

**Then send** (same conversation, as a follow-up): `that's not tan,
that's tagged yellow which is wrong` — this exact phrasing is the one
confirmed live this session to correctly trigger the correction branch
end-to-end (the LLM actually calling `trigger_enrichment` with the right
args, not just the keyword pre-filter matching). Other natural dispute
phrasings should also work in principle — `_detect_correction_signal`
matches broadly on words like "wrong", "mistagged", "not right",
"actually" — but per the earlier "camel coat" lesson in this project
(small phrasing differences can change LLM tool-calling behavior even
when a human would read them as equivalent), prefer the exact verified
string for the live demo rather than an ad-libbed paraphrase.

**Expected**: Classifies as `refinement`. The correction-detection
branch fires, offers `trigger_enrichment` to the LLM with the recent
conversation as context. The LLM calls it with
`attribute_type="color", variant="tan", canonical="brown"`. Because
`tan` is already mapped (to `yellow`), `enrich_attribute` recognizes
this as a **correction**, not a fresh addition — `corrected_from`
comes back as `"yellow"`. A real reindex runs (~19–20s, measured this
session: 19.71s).

**Observe**: Same panel visibility as any enrichment event — a header
banner while the reindex runs, an inline step badge on completion. The
agent's response is warm and specific about what changed (e.g. "You're
right — that was tagged yellow, which was wrong. I've corrected it to
brown and re-indexed the catalog.").

**Then prove it stuck**: click **New Chat** and send the identical
first-turn query, `show me tan boots`, in a fresh conversation. **Do
this in a new conversation, not as a same-thread follow-up** — confirmed
live this session that a same-thread follow-up gets the query rewriter
to expand it (e.g. into "show me tan boots that are not yellow"), which
routes through a different, lexical `multi_match` code path instead of
the same exact-filter `attribute_filter` path turn 1 used — not a clean
comparison. In a fresh conversation, the DSL viewer shows the identical
query shape as turn 1, but `product_color_primary` now reads `"brown"`
instead of `"yellow"` — open it side-by-side with a screenshot of turn
1's DSL for a direct, undeniable before/after. **The field itself
changed**: permanently, for every shopper from now on — not just for
this conversation.

**A note on ranking**: don't over-promise a dramatic before/after
reshuffling of the result *list* — confirmed this session that because
the query text itself contains the literal word "tan", lexical
matching on that word dominates ranking regardless of which color
bucket the filter uses, so the same handful of "tan"-titled products
tend to appear in both the before and after result sets. The
compelling, honest proof point is the **data field itself changing
value live** — not a reshuffled leaderboard. Lead with that.

### Narration

> "Watch the quality gate score on this result: 0.56, comfortably above
> our 0.45 threshold. As far as the system is concerned, this worked.
> But look closer — this boot's title literally says 'Tan', and it's
> indexed as `yellow`. That's a real bug in our taxonomy, and it's
> silent — no automated check catches it, because nothing about the
> score says anything is wrong. Only a shopper looking at the actual
> product would ever notice.
>
> So let's tell it. [sends the correction] The agent doesn't just
> apologize — it calls the same tool it would use to learn a brand-new
> color, except this time to fix an existing one. That's a real write
> to the taxonomy and a real re-index of all 9,618 products, about 20
> seconds. And now — [shows the citation detail again] — that exact
> field, for every shopper, from now on, says brown. Not just for me,
> not just for this session. The catalog itself got smarter because
> someone bothered to point out it was wrong."

### Verified this session (2026-08-31), not hypothetical

- The `tan → yellow` mis-mapping is real, found in the actual discovered
  color taxonomy (not planted) — confirmed via direct query against
  `AttributeMappingStore`, affecting 29 real products.
- Confirmed the wrong-tag result **passes** the quality gate
  (`attribute_filter` threshold 0.45) at scores of 0.558–0.670 across
  runs — i.e. this bug is invisible to the existing automated
  zero-result gap-detection mechanism (used elsewhere in this repo for
  brand-new taxonomy terms) by construction. Only conversational
  correction can catch it.
- Ran the full two-turn flow via direct pipeline invocation (intent
  classifier → query evaluator → retriever → reranker → quality gate →
  agent, called directly in sequence): turn 1 ("show me tan boots")
  surfaced the confidently-wrong result; turn 2 (a dispute phrase)
  correctly classified as `refinement`, triggered
  `_try_correction_tool`, called `trigger_enrichment(color, tan,
  brown)`, ran a real reindex, and returned `corrected_from="yellow"`.
- Confirmed the correction is **live in the actual index**, not just
  the mapping store: queried the affected boot document directly before
  and after — `product_color_primary` flipped from `yellow` to `brown`.
- After verification, reverted the mapping back to `tan → yellow` and
  ran one more clean full reindex (19.71s, 9,618/9,618 succeeded) so the
  repository is back in the genuine bug state, ready for the live
  demo — confirmed via a direct post-revert query that the same boot
  document is back to `product_color_primary: yellow`.
- 834 unit + 205 integration tests pass, including new coverage added
  for the correction path specifically: `EnrichmentResult.corrected_from`
  tracking, the "already mapped, different canonical → correction, not
  no-op" branch in `enrich_attribute`, `_detect_correction_signal`'s
  dispute-phrase matching, and `agent_node`'s correction-branch gating
  (fires on `refinement`/`follow_up` + dispute language + flag on;
  never on a fresh `search`/`attribute_filter` turn, even with
  dispute-shaped wording, since there's no prior turn to dispute).

### Troubleshooting this part specifically

- **The tool never gets called / agent just answers normally without
  fixing anything**: Confirm `ENABLE_ENRICHMENT_TOOL=true` is actually
  set for the running backend process. If it's set correctly, confirm
  the follow-up message actually classified as `refinement` or
  `follow_up` (not `search`) in the observability panel, and that it
  contains clear dispute language — `_detect_correction_signal` is a
  keyword pre-filter and can miss very indirect phrasing.
- **Turn 1 doesn't show the bug** (e.g. filter already resolves to
  `brown`, or no results at all): the mapping isn't in the shipped bug
  state. Restore it before going live:
  ```bash
  cd langchain_agent
  python3 -c "
  import sys; sys.path.insert(0,'.')
  from attribute_mapping_store import AttributeMappingStore
  AttributeMappingStore().add_mapping('color', 'tan', 'yellow', source='seed')
  "
  bash scripts/lucille_ingest.sh --skip-judgments
  ```
- **Reindex takes noticeably longer than ~20s live**: Docker image layer
  cache may be cold — acceptable, but if dramatically slower, check
  `docker ps` / OpenSearch health before going live.
- **Already corrected from a prior rehearsal and you want a clean
  restart**: same restore commands as above — this both re-seeds the
  bug mapping and re-indexes, undoing a prior on-stage correction.

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

A: The whole catalog — a real, full Lucille pipeline run (~19–20s for 9,618 products), not a scoped patch. We measured that a full reindex is fast enough to run live, so there's no need for a narrower, faster-but-less-authentic mechanism.

**Q: What stops the agent from writing garbage into the taxonomy?**

A: A few guardrails: the canonical bucket the agent chooses is validated against a fixed, bounded list per attribute type (it can't invent a new category on the fly); the correction path only overwrites an existing mapping when the LLM explicitly supplies a different canonical after a shopper disputes it — an unprompted, casual mention never rewrites anything; and the tool is gated behind an explicit `ENABLE_ENRICHMENT_TOOL` flag, off by default.

**Q: Why didn't the automated quality gate just catch this bug on its own?**

A: Because the mis-tagged result isn't a *failure* by any metric the system tracks — it's a wrong-but-confident result. The reranker scored it 0.56, comfortably above the 0.45 `attribute_filter` threshold, because the retrieved product genuinely is relevant to "tan boots" in every way except the specific color bucket it's filed under. Automated gap-detection in this codebase is built to catch *zero-result* dead ends (a term the taxonomy has never heard of at all) — a silent mis-mapping produces the opposite signature, a passing score, so it needs a human to actually look at the product and say something.

**Q: Does this work for attributes beyond color?**

A: Yes — the same taxonomy store, detection stage, and `trigger_enrichment` tool also cover material (used elsewhere in this codebase for filling brand-new material gaps), and the correction path itself is generic over `attribute_type`. This demo's script only walks through the color correction end-to-end.

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
> 4. **Taxonomy self-correction** — the agent fixes real, silent data-quality bugs live when a shopper points them out, not just query-side workarounds
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
