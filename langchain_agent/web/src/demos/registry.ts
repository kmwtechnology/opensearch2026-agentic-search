/**
 * The demo script, as data (#103).
 *
 * Transcribed from langchain_agent/DEMO.md (the 7-part conference
 * walkthrough) and DEMO_QUERIES.md (three scenarios with measured numbers).
 * Deliberately a static frontend file: no event carries a scenario id, and
 * inventing backend scenario metadata to drive a header label would be a lot
 * of machinery for a dropdown.
 *
 * The presenter picks the demo; nothing here ever changes on its own. `turns`
 * drives the progress indicator and the "expected next query" hint, but a
 * presenter who improvises is not corrected or interrupted.
 *
 * Keep `query` strings EXACT. Several are load-bearing in ways that are not
 * obvious — see the notes on individual turns.
 */

export interface DemoTurn {
  /** Typed verbatim. Several of these are exact for a reason; see `note`. */
  query: string
  /** One line: what the audience should watch for. Shown to the presenter. */
  watchFor: string
  /** Presenter-only caveat, shown small. Omit when there is nothing to warn about. */
  note?: string
  /** Turn must begin a brand-new conversation (see taxonomy turn 3). */
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
    id: 'intents',
    title: 'Six Intents',
    subtitle:
      'The same search box handles six different kinds of question — and tells you which one it thinks it got.',
    turns: [
      {
        query: 'Find wireless headphones',
        watchFor: 'Intent "search" — alpha assigned by the LLM, not a fast path.',
        note: 'No price, deliberately — this scores ~0.99 where "under $100" scores ~0.30. The catalog has no price data at all, so the agent will say so rather than filter on it.',
      },
      {
        query: 'Compare Sony WH-1000XM5 vs Bose QuietComfort 45',
        watchFor: 'Intent "comparison" at ~0.95 confidence; alpha 0.60 via fast path, no LLM call.',
        note: 'The 10K ESCI sample may not contain these products. An honest "I don\'t have those" is the feature, not a failure.',
      },
      {
        query: 'Show me blue running shoes size 10',
        watchFor: 'Intent "attribute_filter", alpha 0.25 — BM25 dominant.',
      },
      {
        query: 'Show me blue running shoes',
        watchFor:
          'Classifies attribute_filter, and correctly so — "blue" is a real indexed attribute, so there is something concrete to filter on. Sets up the refinement turn.',
      },
      {
        query: 'Make them waterproof',
        watchFor: 'Intent "refinement", alpha 0.35, query expanded from history and constrained to the prior result set.',
        note: 'The dataset likely has no waterproof blue running shoe. The honest "no match" is the point.',
      },
      {
        query: 'What about the next one?',
        watchFor: 'Intent "follow_up" — watch the pronoun get resolved into a self-contained query.',
      },
      {
        query: 'Summarize what we\'ve discussed',
        watchFor: 'Intent "summary" — retriever and reranker are bypassed entirely. Notice how few steps run.',
      },
    ],
  },
  {
    id: 'alpha',
    title: 'Dynamic Alpha',
    subtitle:
      'How literally to read the question is decided per query, not configured once.',
    turns: [
      {
        query: 'gifts for photographers',
        watchFor:
          'Alpha ~0.75, semantic-heavy. Reasoning cites a conceptual, gift-based query. Results are conceptually adjacent, not keyword matches.',
      },
    ],
  },
  {
    id: 'quality-gate',
    title: 'Quality Gate Retry',
    subtitle:
      'When the results are not good enough, the agent notices and searches again by itself.',
    turns: [
      {
        query: 'gift ideas for hair dresser',
        watchFor:
          'Reranker tops out around 0.25, below the bar — then RETRY, alpha 0.85 to 0.55, and a second search. Ten steps instead of seven.',
        note: 'The retry returns the SAME max score — the cross-encoder is deterministic. Narrate the loop firing, never "the second try scored better".',
      },
    ],
  },
  {
    id: 'taxonomy-correction',
    title: 'Taxonomy Self-Correction',
    needsArming: true,
    subtitle:
      'A shopper disputes a wrong product tag, and the catalog fixes itself — live, in about twenty seconds.',
    turns: [
      {
        query: 'show me tan boots',
        watchFor:
          'The filter resolves tan to "yellow" — a real shipped bug affecting 29 products. It PASSES the quality gate at ~0.56. Ask the room: does this look right to you?',
        note: 'Use this exact phrasing. Longer variants add a spurious material_or_feature filter.',
      },
      {
        query: "that's not tan, that's tagged yellow which is wrong",
        watchFor:
          'Correction detected, the value judge approves, then a real Lucille re-index of 9,618 products in ~20s. Watch the elapsed counter.',
        note: 'Exact verified string. The phrase "that\'s not" is what trips the correction detector.',
      },
      {
        query: 'show me tan boots',
        watchFor:
          'The filter now reads product_color_primary: "brown". That field changing IS the proof.',
        note: 'Must be a brand-new conversation — same-thread rewrites the query down a lexical multi_match path. Do not promise a reshuffled result list.',
        requiresNewConversation: true,
      },
    ],
  },
  {
    id: 'refinement-context',
    title: 'Refinement Keeps Context',
    subtitle: 'A two-word follow-up inherits everything the last turn established.',
    turns: [
      {
        query: 'wireless headphones',
        watchFor: 'A plain search. Note the single filter group in the query.',
      },
      {
        query: 'only noise cancelling ones',
        watchFor:
          'Two filter groups now — the new match PLUS a terms filter pinning results to the previous turn\'s product IDs.',
      },
    ],
  },
  {
    id: 'query-rewrite',
    title: 'Query Rewrite',
    subtitle: 'The agent rewrites vague follow-ups into something a search engine can actually use.',
    turns: [
      {
        query: 'coffee maker',
        watchFor: 'Establishes the context the next turn depends on.',
      },
      {
        query: 'how about cheaper',
        watchFor:
          'Query expansion fires — watch the original and the rewritten, self-contained query side by side.',
      },
    ],
  },
]

export const DEFAULT_DEMO_ID = 'taxonomy-correction'

export function getDemo(id: string): Demo {
  return DEMOS.find((d) => d.id === id) ?? DEMOS[0]
}
