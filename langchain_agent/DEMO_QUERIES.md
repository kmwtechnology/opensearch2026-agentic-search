# Demo Queries — Agentic Hybrid Search Conference Talk

**Validated:** 2026-05-03 against local backend; all three picks reproducible
3/3.

> **Demo notes:**
>
> - Local and prod share the same ~9,618-product corpus and the same
>   1.9M-judgment index, so the NDCG@10 numbers below are the on-stage
>   numbers (no "will populate in prod" surprises).
> - Demo 1's retry pass returns the same max_score as the first pass (same
>   docs at any α + deterministic cross-encoder). The QG firing IS the
>   audience-visible payoff — narrate the diagnostic loop, not "second try
>   wins."
> - Demo 2 emits **two** filter groups (multi_match + product_id terms);
>   Demo 3 reliably emits `QueryExpansionEvent`. Both verified post-fix
>   `7b567d9` (build-deploy run 25285876928 @ 2026-05-03T17:28Z).

---

## Scenario 1: α-Shift Wins

**Query**: `gift ideas for hair dresser`
**ESCI**: ✓ in `esci_judgments` (locale=us)

**First Pass**: intent `search`, α=**0.85** ("Pure Semantic"), reranker
max=**0.252**, QG **FAIL** → α → 0.55.

**Retry Pass**: α=**0.55** (lexical-boost), QG accepts (already retried).

| Run   | Intent   | α    | max_score   | QG           |
|-------|----------|------|-------------|--------------|
| 1–3   | search   | 0.85 | 0.252       | RETRY → 0.55 |

(Cross-encoder is deterministic — exact same scores every run.)

**Observable events** (in order):

1. `intent_classified` (search)
2. `opensearch_query` (α=0.85)
3. `reranker_progress` (40 docs)
4. **`quality_gate`** (RETRY, max=0.252, new_α=0.55) ← wow moment
5. `opensearch_query` (α=0.55) ← second retrieval
6. `reranker_progress` (40 docs)
7. `quality_gate` (accepted)
8. `agent_complete`
9. `pipeline_summary`

**Backups** (all 3/3 ESCI-judged + trigger QG, semantic→lexical direction):

| Query                                   | LLM α   | max   | retry α   | Notes                                                             |
|-----------------------------------------|---------|-------|-----------|-------------------------------------------------------------------|
| `gift ideas for hair dresser` (PRIMARY) | 0.85    | 0.252 | 0.55      | matches slide narrative                                           |
| `best 50 dollar gifts`                  | 0.85    | 0.282 | 0.55      | clean alternative                                                 |
| `ideas for young adults for christmas`  | 0.85    | 0.371 | 0.55      | close-call max                                                    |
| `best elliptical exercise machines`     | 0.50    | 0.175 | 0.20      | strongest fail signal but starting α not visibly "semantic-heavy" |

**Avoid** (trigger QG but shift the _wrong_ direction, lexical→semantic):
`best leaf electric mulcher` (0.45→0.75), `net for pool cleaning for kids`
(0.45→0.75).

---

## Scenario 2: Refinement Keeps Context

**Turn 1**: `wireless headphones` → **Turn 2**: `only noise cancelling ones`
**ESCI** (T1): ✓ 68 judged products, **NDCG@10=0.22**

**Turn 1**: intent `search`, α=0.30, reranker max=1.000, returns 10
wireless-headphone products.

**Turn 2 (the demo moment)**:

- Intent: `refinement` (continuity validation passed)
- α: 0.35 (refinement fast-path)
- **Two filters**:
  1. `multi_match: {query: "noise cancelling", fields: [title, chunk_text]}`
  2. `terms: {product_id: [<10 prior IDs>]}`
- Reranker max: 0.98, citations: 3 (10 → 3)
- **Response prefix (verbatim)**: `From the 10 products I showed you
  earlier, here are the ones that match your new criteria: filtering for
  **noise-canceling features**.`
- **Audience payoff**: the Observability Panel "OpenSearch Query" card
  shows _two_ filter groups — the system is parsing the constraint AND
  confining to prior results. The 10 product_ids match Turn 1's citations
  exactly; audience can verify.

| Run   | T2 intent   | T2 α   | T2 max   | Prefix   |
|-------|-------------|--------|----------|----------|
| 1     | refinement  | 0.35   | 0.981    | ✓        |
| 2     | refinement  | 0.35   | 0.981    | ✓        |
| 3     | refinement  | 0.35   | 0.988    | ✓        |

**Events**:

- T1: `intent_classified`, `opensearch_query`, `reranker_progress`,
  `quality_gate (PASS)`, `agent_complete`, `pipeline_summary`
- T2: same flow with `intent_classified=refinement` and `opensearch_query`
  showing both filter groups

**Backups**:

- `boots` → `make them waterproof` (matches slide; slide says "30 boots"
  but reality is 10 due to `RERANKER_TOP_K=10` — adjust slide or say
  "earlier I showed you 10 boots")
- `water bottle` → `only insulated stainless steel` (T2 max=0.667, narrows
  10→2)

**⚠️ Skip the slide's optional Turn 3 ("category switch resets context")**:
verified locally that `find me a red dress` after headphones still routes
through `refinement` and applies the prior-product-id filter (LangGraph
state-persistence quirk — `prior_search_documents` is empty in
`intent_classifier_node` at turn 3). The agent recovers with graceful prose
("It looks like you've shifted gears..."), but the routing is wrong. Skip
it, or use it to demo graceful no-results handling.

---

## Scenario 3: Query Rewrite Wins

**Turn 1**: `coffee maker` → **Turn 2**: `how about cheaper`
**ESCI** (T1): ✓ 56 judged products, **NDCG@10=0.19**

`coffee maker` routes T2 to `follow_up` intent (NOT refinement), so the
demo shows **expansion alone, no product-ID filter** — one mechanism at a
time, matching the slide's narrative cleanly.

**Turn 1**: intent `search`, α=0.30, reranker max=0.998 (PASS), 10 coffee
maker products.

**Turn 2 (the demo moment)**:

- **`QueryExpansionEvent` fires**:
  - Original: `how about cheaper`
  - Expanded: `Are there any cheaper coffee maker options available
    compared to the ones you previously mentioned?`
- Intent: `follow_up` (no product-ID filter — fresh search)
- α: 0.65, reranker top-10 spread:
  `[1.0, 0.86, 0.70, 0.41, 0.34, 0.24, 0.20, 0.19, 0.19, 0.18]`
- Pre-expansion ("how about cheaper" alone) would retrieve random cheap
  items; expanded, it pulls actual coffee makers and the cross-encoder
  spreads them.

| Run   | Expansion   | Intent    | Top-3             |
|-------|-------------|-----------|-------------------|
| 1     | ✓           | follow_up | [1.0, 0.72, 0.66] |
| 2     | ✓           | follow_up | [1.0, 0.72, 0.66] |
| 3     | ✓           | follow_up | [1.0, 0.86, 0.70] |

(LLM expansion text occasionally varies; intent and top-1 always stable.)

**Events** (T2): `query_expansion` ← wow moment, then `intent_classified
(follow_up)`, `opensearch_query (α=0.65, no filter)`, `reranker_progress`,
`quality_gate (PASS)`, `agent_complete`, `pipeline_summary`.

**Backups** (all 3/3):

| Base                  | Follow-up                             | Intent     | Notes                                                                    |
|-----------------------|---------------------------------------|------------|--------------------------------------------------------------------------|
| `wireless headphones` | `how is the battery life`             | follow_up  | Top-2 strong (0.96/0.96), then cliff                                     |
| `hiking boots`        | `are they comfortable for long walks` | follow_up  | Gentle slope, audience-friendly                                          |
| `yoga mat`            | `are they thick enough for knees?`    | refinement | T1 NDCG=0.33; clean expansion but combines with filter (cluttered story) |
| `wireless headphones` | `on a budget`                         | refinement | Expansion clean but adds filter                                          |

`_expand_vague_query` always fires on a follow-up where prior conversation
exists; whether it rewrites depends on the LLM. Short pronoun-laden queries
("are they...", "show me them...", "on a budget", "how about cheaper")
reliably get rewritten.

---

## Pre-Talk Checklist

- [x] Bug fix to `_expand_vague_query` (and 4 sibling sites) committed and
      deployed (`7b567d9`, build-deploy run 25285876928 @
      2026-05-03T17:28Z)
- [x] ESCI judgments index populated (1.9M judgments shared between local
      and prod)
- [ ] Run each demo against the live Cloud Run URL once, day-of, to confirm
      reproducibility (events fire, prefixes appear, expansion text emits)
- [ ] Demo 1 narration ready: retry won't show a higher max_score (same
      corpus → same docs at any α → same rescore). Frame as honest
      diagnostic loop, not "second try wins."
