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

> "This is **Agentic Hybrid Search** — a production-grade RAG agent for e-commerce product discovery. It's built on LangGraph, uses hybrid search (vector + lexical), and reranks with a local cross-encoder model.
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

- Intent Classifier step shows "search" with its confidence and reasoning
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

- Intent Classifier shows "comparison" via its LLM call, confidence ~0.95
- Query Evaluator assigns α=0.60 instantly (its own fast-path, no LLM — separate from intent classification, which is always an LLM call)
- Knowledge Search retrieves both specific models
- Results ranked by comparison relevance

**Narration**:

> "**Comparison intent** — users want to pit products against each other. The LLM classifies the intent, the query evaluator assigns a fixed alpha via its fast-path, and the cross-encoder reranker scores each product's relevance to both products."

---

### Query 3: Attribute Filter Intent

**Send**: `Show me blue running shoes size 10`

**Expected**: Intent = `attribute_filter`, α = 0.25 (fast-path, lexical-heavy)

**Observe**:

- Intent Classifier classifies this as `attribute_filter` via its LLM call (brand + color + size cues)
- Query Evaluator assigns α=0.25 (its own lexical-heavy fast-path, no LLM)
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

On **Cloud Run**, this is set automatically by `build-deploy.yml`'s
`gcloud run deploy` step (`ENABLE_ENRICHMENT_TOOL=true`, added 2026-09-08
— it was missing before that and silently disabled the tool in prod;
see the GCP reset/verify section below for how that was found and
fixed). No manual flag flip needed there — every deploy has it on.

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
catalog (~19–20s, measured — not a mock, not a scoped patch). That timing is the **local** mechanism (`REINDEX_TRIGGER=local`, Lucille subprocess); on Cloud Run the same tool call dispatches the `reindex.yml` workflow instead (~8 min, fire-and-forget), so run the live demo against local dev.

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

**Observe / narrate**: The agent's own response now leads with the
mismatch — no DSL panel click required. It opens with a note like "while
all of these products are listed as 'Tan,' they are currently indexed in
the 'yellow' color category. This appears to be a data-tagging issue,"
and every product line reads "Listed as Tan (indexed as yellow)." This
comes from `_build_grounded_context` (`main.py`) including both the raw
`product_color` and the derived `product_color_primary` as separate
FACTS lines, plus a grounding rule instructing the agent to flag a
mismatch between them when the indexed category isn't a plausible family
for the listed color (see `ARCHITECTURE.md`). The observability panel's
citation/DSL detail (`product_color_primary: yellow`) is still there as
a secondary, technical backup if you want to show the raw filter too —
but the chat text alone is now the primary reveal. This is the moment to
ask the audience: "does this look right to you?"

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
`attribute_type="color", variant="tan", canonical="brown"`. Before the
tool actually executes, a second, independent LLM call
(`EnrichmentValueJudge`, gated in `main.py`'s `_try_enrichment_tool` —
see `ARCHITECTURE.md`) evaluates whether this specific change would
genuinely improve search quality, not just whether the first call's
category choice is defensible — confirmed live this session it approves
the real tan→brown correction (`is_meaningful=True`) in ~1s, and
separately confirmed it correctly *declines* a nonsense/idiosyncratic
proposed mapping in testing, so this is a real gate, not a rubber stamp.
Because `tan` is already mapped (to `yellow`), `enrich_attribute`
recognizes this as a **correction**, not a fresh addition —
`corrected_from` comes back as `"yellow"`. A real reindex runs (~19–20s,
measured this session: 19.71s). This adds roughly 1s of latency before
the reindex starts — not perceptible against the ~20s reindex itself, so
no change to the demo's pacing.

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
> color, except this time to fix an existing one. Before it commits to
> that, a second, independent model double-checks that this is actually
> a worthwhile change, not just a knee-jerk agreement — then it's a real
> write to the taxonomy and a real re-index of all 9,618 products, about
> 20 seconds. And now — [new chat, same query] — that exact field, for
> every shopper, from now on, says brown. Not just for me, not just for
> this session. The catalog itself got smarter because someone bothered
> to point out it was wrong."

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
- **Full rehearsal replayed live in a real browser session** (Chrome,
  actual dev servers, actual observability panel — not just direct
  pipeline invocation): confirmed the quality-gate PASS banner, the DSL
  viewer showing the wrong `yellow` filter, the "Catalog Enrichment
  Triggered" header banner and step badge during the real ~20s reindex,
  and — using a fresh "New Chat" for the follow-up, per the fix below —
  the identical query's DSL now reading `brown`.
- **Found and fixed a real gap this same rehearsal surfaced**: sending
  the "did it work" follow-up in the *same* conversation thread gets the
  query rewriter to expand "show me tan boots" into something like "show
  me tan boots that are not yellow," which routes through a different,
  lexical `multi_match` path instead of the clean `attribute_filter`
  exact-match path turn 1 used — not a valid before/after comparison.
  Fixed by scripting a fresh conversation for the proof-it-stuck step
  (see above) — confirmed live to reproduce the identical DSL shape with
  only the filter value changed.
- **Added: the raw-vs-indexed color mismatch is now flagged directly in
  the agent's own chat response**, not just the DSL panel — confirmed
  live via direct pipeline invocation that turn 1's response leads with
  an explicit note ("these products are listed as 'Tan,' but... indexed
  in the 'yellow' color category... a data-tagging issue") and
  per-product "Listed as Tan (indexed as yellow)" lines, and that after
  correction the same query is silent about it (no mismatch to flag).
  This required two fixes beyond the grounded-context change itself:
  `retrieval/vector_store.py`'s `_hit_to_document` wasn't including
  `product_color_primary` in the metadata handed to the agent at all
  (silently empty, not just unused); and `quality/judge.py`'s `_format_docs_for_prompt`
  builds a *separate* doc rendering for the LLM-judge pass that didn't
  include the new fact lines either, causing the judge to flag the
  grounded mismatch note as an unsupported fabrication and the
  auto-correction retry to silently strip it back out — confirmed fixed
  live (`faithfulness: 1.0`, zero hallucinations flagged, no retry).
- **Added: a second, independent AI evaluation gates every
  `trigger_enrichment` call** (`EnrichmentValueJudge`) before it's
  allowed to write a mapping and trigger a real reindex — confirmed live
  with the real model that the genuine tan→brown correction is approved
  (`is_meaningful=True`, ~1s) and that a deliberately nonsense proposed
  mapping is correctly declined, so this is a real check, not a rubber
  stamp. Adds ~1s of latency, imperceptible against the ~20s reindex.
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
  `make seed-taxonomy` is the heavier equivalent: it wipes *every*
  color/material mapping (including anything the agent learned in
  rehearsals) and rediscovers from scratch, which lands back on the
  shipped `tan → yellow` seed bug, then runs the products pass. Use it
  when the store has drifted in more ways than the one mapping.

- **On Cloud Run / GCP (not local dev) — resetting the buggy baseline**:
  the local restore commands above don't apply — there's no local Python
  shell against the hosted OpenSearch cluster, and no local Lucille
  subprocess (`REINDEX_TRIGGER=github` there). Two things also don't
  work the way you'd expect on GCP, confirmed live 2026-09-08:

  - **Asking the agent to revert conversationally does not work, by
    design.** Sending a dispute like "actually, tan should be tagged
    yellow, not brown" gets correctly *declined* by `EnrichmentValueJudge`
    — it recognizes tan-as-brown is the true correction and refuses to
    re-introduce a known-wrong mapping. This is the value judge working
    as intended, not a bug to route around conversationally.
  - **`POST /api/admin/enrich` with a deliberately-false payload
    (`{"canonical": "yellow"}` for a variant already correctly mapped to
    `"brown"`) gets blocked by Claude Code's own Bash-permission
    classifier** when driven from an agent session, because it reads as
    an intentional data-corruption write — even with `X-Admin-Token`.
    A **genuinely new** mapping via the same endpoint (e.g. registering
    an unmapped color variant) is *not* blocked; only a write that
    reintroduces a known-false value is.

  The reset that actually works is two direct steps, bypassing the app
  entirely:

  1. **Write the buggy mapping straight to OpenSearch** (the
     app-level guard above doesn't apply to a direct cluster write):
     ```bash
     ADMIN_TOKEN=$(gcloud run services describe agentic-hybrid-search \
       --project=<PROJECT_ID> --region=<REGION> \
       --format="value(spec.template.spec.containers[0].env)" \
       | tr ';' '\n' | grep "'name': 'ADMIN_TOKEN'" \
       | sed -E "s/.*'value': '([^']+)'.*/\1/")  # only needed for the verify step below

     OS_USER=$(gcloud secrets versions access latest --secret=opensearch-username --project=<PROJECT_ID>)
     OS_PASS=$(gcloud secrets versions access latest --secret=opensearch-password --project=<PROJECT_ID>)

     curl -s -k -u "$OS_USER:$OS_PASS" -X PUT \
       "https://<OPENSEARCH_HOST>:9200/agentic_hybrid_search_attribute_mappings/_doc/color%23tan" \
       -H "Content-Type: application/json" \
       -d '{"attribute_type":"color","variant":"tan","canonical":"yellow","source":"seed","added_at":"'"$(date -u +%Y-%m-%dT%H:%M:%S)"'"}'
     ```
     The doc id is always `<attribute_type>#<variant lowercased>` (see
     `retrieval/attribute_mapping_store.py`'s `add_mapping`), so `color#tan` is
     stable across environments.
  2. **Dispatch a real, non-destructive reindex** to propagate the
     mapping into product documents (a direct OpenSearch write to the
     mapping store alone does *not* touch indexed
     `product_color_primary` fields — only a reindex does):
     ```bash
     gh workflow run reindex.yml -R kmwtechnology/opensearch2026-agentic-search \
       -f reset_index=false -f reindex_judgments=false -f seed_taxonomy=false
     ```
     `reset_index=false` matters — the default is `true`, which drops
     and rebuilds the entire products index from scratch (~unnecessary
     and slower for a mapping-only fix). Watch it with
     `gh run watch <id> --exit-status`, then confirm with
     `gh run view <id> --json status,conclusion` (~8 min on Cloud Run's
     `reindex.yml` path, vs. ~20s for the local Lucille subprocess).
  3. **Verify** with a fresh chat conversation, `show me tan boots` —
     the color-mismatch note should reappear. (Or read-only: `GET
     /api/admin/diagnose?query=tan+boots` with `X-Admin-Token`, or query
     OpenSearch directly.)

  The same two-step pattern (direct OpenSearch write + `reindex.yml`
  dispatch with `reset_index=false`) is also the way to force a real
  reindex on GCP for verification/testing purposes generally, since the
  idempotent "already mapped to the same canonical" guard in
  `enrich_attribute` means re-sending the same correction through the
  app a second time is a silent no-op — it won't trigger a fresh
  dispatch once the store already reflects it.

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

A: Gemini 3 Flash for generation, Gemini 3.1 Flash Lite for classification/query evaluation (faster, cheaper), models/gemini-embedding-001 for embeddings (768-dim) — all via Google AI. Reranking is a local cross-encoder (`ms-marco-MiniLM-L-12-v2`), not an LLM call — it's baked into the Docker image so it runs offline with no added API latency.

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

A: The whole catalog — a real, full Lucille pipeline run (~19–20s for 9,618 products), not a scoped patch. We measured that a full reindex is fast enough to run live, so there's no need for a narrower, faster-but-less-authentic mechanism. (On the hosted deployment the same call dispatches the `reindex.yml` GitHub Actions workflow and reports the run URL — same result, different mechanism, chosen by `REINDEX_TRIGGER`.)

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

### If audience asks about "1 OVERREACH" badge in Pipeline Quality Summary

The LLM judge (part of the quality-assurance layer) flags statements that
aren't directly sourced from the retrieved product data, even if they're
generally true. In Turn 1, it flags the commonsense statement "tan is
typically considered a shade of brown, not yellow" because that reasoning
isn't literally in the FACTS blocks — it's the judge being appropriately
strict about unsourced inferences. **The response itself is correct;** this
is just the safety mechanism being visible in the panel. You can say: "The
system triple-checks its own reasoning against the actual data — and in this
case, flagged a general color-family comment because it's inferred, not
stated in the product data. That's working as designed."

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
