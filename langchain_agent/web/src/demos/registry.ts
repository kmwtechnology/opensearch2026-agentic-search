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
      'The agent reads each question differently, keeps its place in the conversation, and notices when its own results are not good enough.',
    turns: [
      {
        query: 'Find wireless headphones',
        watchFor:
          'Intent "search". Alpha is assigned by the LLM per query, not configured once — and the reranker clears the bar comfortably.',
        note: 'Deliberately no price. The catalog has no price data at all, so "under $100" scores far worse and the agent has to say so.',
      },
      {
        query: 'only noise cancelling ones',
        watchFor:
          'Intent "refinement" — two filter groups now: the new match PLUS a filter pinning results to the previous turn\'s products. Context is kept, not re-searched.',
      },
      {
        query: 'Show me blue running shoes size 10',
        watchFor:
          'Intent "attribute_filter" at alpha 0.25 — BM25 dominant. Correctly so: "blue" is a real indexed attribute, so there is something concrete to filter on rather than only something to match semantically.',
        // Fresh thread on purpose. The intent rules bias hard toward
        // "refinement" whenever a prior product search exists, and refinement
        // pins results to the PREVIOUS turn's product ids — so asked after the
        // headphones pair this would be constrained to headphones, return
        // nothing, and contradict the label above. The arc is three mini
        // threads, which is also how each was validated.
        requiresNewConversation: true,
      },
      {
        query: 'gift ideas for hair dresser',
        // Same reason, and the quality-gate retry was only ever verified from
        // a clean thread.
        requiresNewConversation: true,
        watchFor:
          'Semantic-heavy alpha for a conceptual query — then the quality gate fires: the best match falls under the bar, so the agent rebalances and searches AGAIN on its own.',
        note: 'The retry returns the SAME max score — the cross-encoder is deterministic. Narrate the loop firing, never "the second try scored better".',
      },
      {
        query: 'how about cheaper',
        watchFor:
          'Three words with no subject. Watch the rewriter turn it into a self-contained query using the conversation so far.',
      },
    ],
  },
  {
    id: 'taxonomy-ingestion',
    title: 'Taxonomy & Ingestion',
    needsArming: true,
    subtitle:
      'The harder case: the catalog itself is wrong. A shopper disputes a tag, and the agent fixes the data — live, in about twenty seconds.',
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
