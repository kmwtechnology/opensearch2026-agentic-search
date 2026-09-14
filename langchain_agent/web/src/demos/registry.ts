/**
 * The demo script, as data (#103).
 *
 * TWO demos, matching the two halves of the talk's thesis (see
 * docs/presentation/Agentic Search Presentation Outline.md §1):
 *
 *   1. Adaptive Query Enhancements — the agent improves results on the fly:
 *      classify intent, weight hybrid retrieval per query, keep context across
 *      turns, rewrite vague follow-ups, and retry once when confidence is low.
 *      This is the part most agentic-search systems already do.
 *
 *   2. Taxonomy & Ingestion — the agent recognises that the CATALOG is wrong,
 *      not the query, and fixes it: correcting a shipped mis-mapping and
 *      triggering a real Lucille re-index, live. The talk's centerpiece.
 *
 * This was six demos, one per capability, which is the wrong shape for a
 * 30-45 minute session: six dropdown entries invite six context switches, and
 * the audience loses the thesis in the enumeration. Each capability is now a
 * TURN inside the arc it belongs to.
 *
 * Transcribed from DEMO.md and DEMO_QUERIES.md. Keep `query` strings EXACT —
 * several are load-bearing in ways that are not obvious; see each `note`.
 */

export interface DemoTurn {
  /** Typed verbatim. Several of these are exact for a reason; see `note`. */
  query: string
  /** One line: what the audience should watch for. Shown to the presenter. */
  watchFor: string
  /** Presenter-only caveat, shown small. Omit when there is nothing to warn about. */
  note?: string
  /** Turn must begin a brand-new conversation (see the taxonomy proof turn). */
  requiresNewConversation?: boolean
}

export interface Demo {
  id: string
  title: string
  /** The one-line "what you're about to see", spoken before the first turn. */
  subtitle: string
  /**
   * This demo CONSUMES a data defect, so it has to be re-armed before it can
   * run again. The taxonomy demo works because the catalog mis-tags tan as
   * yellow; succeeding rewrites that mapping and re-tags the products, after
   * which turn 1 shows nothing wrong — no mismatch to spot, nothing to
   * dispute, nothing to correct. It does not error, it just stops
   * demonstrating anything, which is the worst way to discover it on stage.
   *
   * The UI therefore re-arms automatically: on selecting the demo, and again
   * before its first turn. Nobody should have to remember a reset step.
   */
  needsArming?: boolean
  turns: DemoTurn[]
}

export const DEMOS: Demo[] = [
  {
    id: 'adaptive-query',
    title: 'Adaptive Query Enhancements',
    subtitle:
      'One shopper, one conversation. Each question is read differently from the last, and the agent carries what it already knows from turn to turn.',
    /*
     * ONE shopper, ONE conversation, three turns that narrow — the way a person
     * actually shops. No turn starts a new thread and no turn contradicts an
     * earlier one, which is what makes it a story rather than a feature list.
     *
     * The spine, visible in the narrator panel as it runs, is ALPHA MOVING:
     * 0.25 lexical-heavy → 0.35 balanced → 0.70 semantic-heavy. The dial swings
     * as the questions get less literal, and nobody configured that per query.
     *
     * Every turn below was run end-to-end against the live local stack as a
     * single conversation before being written down; the numbers in `watchFor`
     * are measured, not estimated.
     *
     * Two queries were tested and REJECTED, for reasons worth keeping:
     *   - "only the lightweight ones" — "lightweight" appears nowhere in the
     *     shoe documents, so filter relaxation widened to the whole catalog and
     *     the agent answered a running-shoe question with MGEOY Girls Rain
     *     Jackets. Refine only on attributes the current results actually have.
     *   - "which of these is best for trail running?" — "these" promises the
     *     answer comes from the products already on screen, but the agent
     *     re-searches and introduces a shoe that was not in that list. The
     *     vaguer "what about trail running?" makes no such promise, and it
     *     exercises the rewriter harder anyway.
     *
     * Intent labels are deliberately NOT promised per turn. The classifier is
     * stable on turns 1 and 2 but has returned both "refinement" and "search"
     * for conversational turns like turn 3 across runs. Narrate the BEHAVIOR —
     * the filters, the pinning, the rewrite — all of which hold every time.
     */
    turns: [
      {
        query: 'Show me blue running shoes',
        watchFor:
          'Alpha 0.25 — lexical-heavy, BM25 dominant. "blue" and "running" are real indexed attributes, so there is something concrete to filter on: watch the filter line read color: blue, feature: running.',
        note: 'Never ask this catalog about price, here or off-script. There is no price field in any form, so every turn stays on attributes that exist: color, size, material, brand, feature.',
      },
      {
        query: 'only size 10',
        watchFor:
          'Three words. Alpha moves to 0.35 and a THIRD filter appears (feature: 10) while the results stay pinned to the products from turn 1 — the reply says so out loud: "From the 10 products I showed you earlier". Context is narrowed, not re-searched.',
        note: 'This is the turn that was silently broken until the product_id filter was fixed — it matched zero documents and the agent said it found nothing.',
      },
      {
        query: 'what about trail running?',
        watchFor:
          'Four words, no subject, no colour, no size — and the rewriter turns it into "Show me blue trail running shoes in size 10", carrying BOTH earlier constraints forward. Alpha jumps to 0.70, semantic-heavy, because this question is about purpose rather than a literal attribute.',
      },
      /*
       * NO retry turn here, and the reason is worth recording so nobody spends
       * an afternoon hunting for one again.
       *
       * The gate's retry now genuinely searches deeper rather than only
       * re-weighting (see RETRY_FETCH_MULTIPLIER), so recovery is possible in
       * principle — offline, "shoes that will not give me blisters on long
       * runs" goes 0.24 -> 0.98 once the pool widens. But no query has been
       * found that fails and then recovers INSIDE this conversation:
       *
       *   - A query specific enough to fail usually classifies as
       *     attribute_filter at alpha 0.25, where the first pass already scores
       *     0.86-0.99 and the gate never fires.
       *   - A query vague enough to fire the gate almost always fires it
       *     because the catalog genuinely has nothing: the reranker rescales a
       *     uniformly-irrelevant batch to a 0.30 ceiling (reranker.py), and no
       *     amount of extra candidates invents a product that does not exist.
       *   - From turn 2 onward the rewriter folds "blue running shoes in size
       *     10" into every follow-up, which lifts scores to 0.69-0.91 — the
       *     conversation itself prevents the failure.
       *   - On a refinement turn the results are pinned to the prior turn's
       *     product ids, so widening the pool cannot escape that pin.
       *
       * Twenty-plus queries were run through the live pipeline looking for the
       * signature (two searches AND a final score over threshold); three fired
       * the gate, none recovered. The closest was "shoes that stay comfortable
       * after twenty miles", which improved 0.30 -> 0.35 and still missed the
       * 0.45 bar.
       */
    ],
  },
  {
    id: 'taxonomy-ingestion',
    title: 'Taxonomy & Ingestion',
    needsArming: true,
    subtitle:
      'A different person: the developer who owns this catalog. They spot a tag that is wrong, say so, and the agent repairs the data itself — live, in about twenty seconds.',
    turns: [
      {
        query: 'show me tan boots',
        watchFor:
          'The filter resolves tan to "yellow" — a real shipped bug affecting every product the catalog lists as Tan. It PASSES the quality gate, so no automated check can catch it. Ask the room: does this look right to you?',
        note: 'Use this exact phrasing. Longer variants add a spurious material_or_feature filter.',
      },
      {
        query: "that's not tan, that's tagged yellow which is wrong",
        watchFor:
          'Correction detected, a second model approves the change, then a real Lucille re-index of 9,618 products. Watch the elapsed counter — this is the ingest pipeline running, not a cached swap.',
        note: 'Exact verified string. The phrase "that\'s not" is what trips the correction detector.',
      },
      {
        query: 'show me tan boots',
        watchFor:
          'The filter now reads product_color_primary: "brown". That field changing IS the proof — the fix is permanent, for every future shopper.',
        note: 'Must be a brand-new conversation — same-thread rewrites the query down a lexical path. Do not promise a reshuffled result list.',
        requiresNewConversation: true,
      },
    ],
  },
]

export const DEFAULT_DEMO_ID = 'adaptive-query'

export function getDemo(id: string): Demo {
  return DEMOS.find((d) => d.id === id) ?? DEMOS[0]
}
