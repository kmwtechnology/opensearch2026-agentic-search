import { describe, expect, it } from 'vitest'
import { MAX_VISIBLE_LINES, narrate, visibleLines } from '../narrate'
import type { AgentEvent, EnrichmentTriggeredEvent } from '../../../types/events'

const TS = '2026-09-14T12:00:00Z'

function enrichment(overrides: Partial<EnrichmentTriggeredEvent>): EnrichmentTriggeredEvent {
  return {
    type: 'enrichment_triggered',
    node: 'agent',
    timestamp: TS,
    attribute_type: 'color',
    variant: 'tan',
    status: 'complete',
    ...overrides,
  } as EnrichmentTriggeredEvent
}

describe('narrate', () => {
  it('phrases intent in plain language with confidence', () => {
    const line = narrate({
      type: 'intent_classification',
      node: 'intent_classifier',
      timestamp: TS,
      intent: 'refinement',
      user_query: "that's not tan",
      reasoning: 'disputes a prior tag',
      confidence: 0.94,
    } as AgentEvent)

    expect(line?.text).toBe('Read this as a refinement of the last turn — 94% confident.')
    expect(line?.weight).toBe('step')
  })

  it('reuses the backend search_strategy rather than re-deriving it from alpha', () => {
    const line = narrate({
      type: 'query_evaluation',
      node: 'query_evaluator',
      timestamp: TS,
      query: 'gifts for photographers',
      alpha: 0.85,
      query_analysis: 'conceptual',
      search_strategy: 'semantic-heavy',
    } as AgentEvent)

    // The strategy word still comes from the backend rather than being
    // re-derived from alpha here. The alpha VALUE moved out of the sentence
    // and into the gauge caption, where it is paired with the bar that shows
    // where it sits between "exact words" and "meaning".
    expect(line?.gauge?.caption).toContain('semantic heavy')
    expect(line?.gauge?.caption).toContain('0.85')
    expect(line?.gauge?.kind).toBe('alpha')
    expect(line?.gauge?.value).toBe(0.85)
  })

  it('does not repeat the "chosen per query" philosophy every single turn (#130)', () => {
    // The gauge right below already conveys "how literally" via its own
    // exact-words/meaning axis labels — this used to be restated in the
    // sentence on every single turn regardless of what the turn actually did.
    const line = narrate({
      type: 'query_evaluation',
      node: 'query_evaluator',
      timestamp: TS,
      query: 'gifts for photographers',
      alpha: 0.5,
      query_analysis: 'balanced',
      search_strategy: 'balanced',
    } as AgentEvent)

    expect(line?.text).not.toMatch(/configured once/i)
    expect(line?.text).not.toMatch(/chosen per query/i)
    expect(line?.text).toContain('balanced')
  })

  it('makes the search sentence reactive to where alpha actually landed (#130)', () => {
    const lexical = narrate({
      type: 'opensearch_query',
      node: 'retriever',
      timestamp: TS,
      query: 'tan boots',
      alpha: 0.1,
      intent: 'attribute_filter',
      query_type: 'hybrid',
    } as AgentEvent)
    const semantic = narrate({
      type: 'opensearch_query',
      node: 'retriever',
      timestamp: TS,
      query: 'gifts for photographers',
      alpha: 0.9,
      intent: 'search',
      query_type: 'hybrid',
    } as AgentEvent)

    // The two sentences must actually differ — previously both said the
    // identical "blending keyword matching with meaning" regardless of alpha.
    expect(lexical?.text).not.toBe(semantic?.text)
    expect(lexical?.text).toContain('exact words')
    expect(semantic?.text).toContain('meaning')
  })

  it('says nothing when a query expansion did not actually change the query', () => {
    expect(
      narrate({
        type: 'query_expansion',
        node: 'retriever',
        timestamp: TS,
        original_query: 'coffee maker',
        expanded_query: 'coffee maker',
        expansion_reason: 'no change',
      } as AgentEvent)
    ).toBeNull()
  })

  it('stays silent on the BM25 baseline query, which is a metrics artifact', () => {
    expect(
      narrate({
        type: 'opensearch_query',
        node: 'retriever',
        timestamp: TS,
        query: 'tan boots',
        alpha: 0.25,
        intent: 'attribute_filter',
        query_type: 'bm25_baseline',
      } as AgentEvent)
    ).toBeNull()
  })

  it('distinguishes a retry search from a first search via query_type', () => {
    const first = narrate({
      type: 'opensearch_query',
      node: 'retriever',
      timestamp: TS,
      query: 'tan boots',
      alpha: 0.25,
      intent: 'attribute_filter',
      query_type: 'hybrid',
      filter_summary: 'color: yellow',
    } as AgentEvent)
    const retry = narrate({
      type: 'opensearch_query',
      node: 'retriever',
      timestamp: TS,
      query: 'tan boots',
      alpha: 0.55,
      intent: 'attribute_filter',
      query_type: 'quality_gate_retry',
    } as AgentEvent)

    expect(first?.text).toContain('Filtered on color: yellow')
    expect(retry?.text).toContain('again')
  })

  it('says the top pick was promoted when reranking changed rank 1 specifically (#130)', () => {
    const line = narrate({
      type: 'reranker_result',
      node: 'reranker',
      timestamp: TS,
      reranker_type: 'cross-encoder',
      reranking_changed_order: true,
      results: [
        { source: 'b', score: 0.97, rank: 1, original_rank: 3, snippet: '', rank_change: 2 },
        { source: 'a', score: 0.9, rank: 2, original_rank: 1, snippet: '', rank_change: -1 },
      ],
    } as AgentEvent)

    expect(line?.text).toContain('promoted a new top pick')
    expect(line?.text).toContain('0.97')
  })

  it('says the top pick held when reranking changed order lower down only (#130)', () => {
    const line = narrate({
      type: 'reranker_result',
      node: 'reranker',
      timestamp: TS,
      reranker_type: 'cross-encoder',
      reranking_changed_order: true,
      results: [
        { source: 'a', score: 0.97, rank: 1, original_rank: 1, snippet: '', rank_change: 0 },
        { source: 'b', score: 0.9, rank: 2, original_rank: 3, snippet: '', rank_change: 1 },
      ],
    } as AgentEvent)

    expect(line?.text).toContain('the top pick held')
    expect(line?.text).not.toContain('promoted')
  })

  it('says the order already held up when reranking changed nothing', () => {
    const line = narrate({
      type: 'reranker_result',
      node: 'reranker',
      timestamp: TS,
      reranker_type: 'cross-encoder',
      reranking_changed_order: false,
      results: [
        { source: 'a', score: 0.97, rank: 1, original_rank: 1, snippet: '', rank_change: 0 },
      ],
    } as AgentEvent)

    expect(line?.text).toContain('the order already held up')
  })

  it('narrates a quality-gate retry as the loop firing, never as a better score', () => {
    const line = narrate({
      type: 'quality_gate',
      node: 'quality_gate',
      timestamp: TS,
      triggered: true,
      original_alpha: 0.85,
      new_alpha: 0.55,
      max_score: 0.3,
      threshold: 0.45,
      reason: 'RETRY (attribute_filter): score 0.300 < 0.45, alpha -> 0.55',
    } as AgentEvent)

    expect(line?.weight).toBe('moment')
    expect(line?.text).toContain('Searching again')
    expect(line?.text).not.toMatch(/better|improved|higher/i)
  })

  it('reports a passing quality gate as an ordinary step', () => {
    const line = narrate({
      type: 'quality_gate',
      node: 'quality_gate',
      timestamp: TS,
      triggered: false,
      original_alpha: 0.25,
      max_score: 0.56,
      threshold: 0.45,
      reason: 'PASS',
    } as AgentEvent)

    expect(line?.weight).toBe('step')
    expect(line?.text).toContain('Passed')
  })

  it('does not call it a pass when the score is still under the bar', () => {
    // Observed live on DEMO.md turn 1: after the retry was spent the gate
    // emitted triggered=false with max_score 0.34 against a 0.45 threshold,
    // and the panel announced "Passed the quality bar — 0.34 against 0.45".
    const line = narrate({
      type: 'quality_gate',
      node: 'quality_gate',
      timestamp: TS,
      triggered: false,
      original_alpha: 0.55,
      max_score: 0.34,
      threshold: 0.45,
      reason: 'Accepted after retry',
    } as AgentEvent)

    expect(line?.text).not.toMatch(/passed/i)
    expect(line?.text).toContain('Still under the bar')
    expect(line?.text).toContain('best available')
  })

  it('never claims a pass when nothing was retrieved to score', () => {
    // Observed live on DEMO.md's first query: filters matched no products, so
    // the reranker never ran and max_score was 0 — and the panel announced
    // "Passed the quality bar — 0.00 against 0.45", which is self-refuting.
    const line = narrate({
      type: 'quality_gate',
      node: 'quality_gate',
      timestamp: TS,
      triggered: false,
      original_alpha: 0.25,
      max_score: 0,
      threshold: 0.45,
      reason: 'PASS',
    } as AgentEvent)

    expect(line?.text).not.toMatch(/passed/i)
    expect(line?.text).toContain('Nothing came back to score')
  })

  it('ignores events that are not worth saying out loud', () => {
    expect(
      narrate({
        type: 'llm_response_chunk',
        node: 'agent',
        timestamp: TS,
        content: 'tok',
        is_complete: false,
      } as AgentEvent)
    ).toBeNull()
  })
})

describe('narrate — enrichment lifecycle', () => {
  it('announces the re-index while it is underway', () => {
    const line = narrate(enrichment({ status: 'started', canonical: 'brown' }))
    expect(line?.enrichment).toBe('started')
    expect(line?.weight).toBe('moment')
    expect(line?.text).toContain('Rebuilding')
  })

  it('distinguishes a CORRECTION from merely learning a new term', () => {
    const corrected = narrate(
      enrichment({
        status: 'complete',
        canonical: 'brown',
        corrected_from: 'yellow',
        docs_processed: 9618,
        duration_seconds: 19.4,
      })
    )
    const learned = narrate(
      enrichment({
        status: 'complete',
        variant: 'chrome',
        attribute_type: 'material',
        canonical: 'metal',
        docs_processed: 9618,
        duration_seconds: 19.4,
      })
    )

    expect(corrected?.label).toBe('Correction Applied')
    expect(corrected?.text).toContain('was tagged yellow')
    expect(corrected?.text).toContain('9,618')
    expect(corrected?.correctedFrom).toBe('yellow')

    expect(learned?.label).toBe('Catalog Learned')
    expect(learned?.text).not.toContain('was tagged')
  })

  it('falls back to the run URL wording when the cloud build gives no numbers', () => {
    const line = narrate(
      enrichment({
        status: 'complete',
        canonical: 'brown',
        corrected_from: 'yellow',
        reindex_mode: 'github',
        reindex_run_url: 'https://github.com/x/actions/runs/1',
      })
    )
    expect(line?.text).toContain('cloud build')
    expect(line?.reindexRunUrl).toBe('https://github.com/x/actions/runs/1')
  })

  it('states plainly that a failed rebuild left the tag unchanged', () => {
    const line = narrate(
      enrichment({ status: 'failed', canonical: 'brown', error: 'docker daemon not running' })
    )
    expect(line?.text).toContain('did not finish')
    expect(line?.text).toContain('unchanged')
  })

  it('surfaces a judge decline instead of leaving the panel silent', () => {
    const line = narrate(
      enrichment({ status: 'declined', error: "'tan' already resolves sensibly." })
    )
    expect(line?.label).toBe('Change Declined')
    expect(line?.text).toContain('turned it down')
  })
})

describe('narrate — ground truth reveal (#130)', () => {
  function summary(overrides: Partial<AgentEvent>): AgentEvent {
    return {
      type: 'pipeline_summary',
      timestamp: TS,
      has_ground_truth: false,
      query: 'cowboy boots women',
      optimizations: {},
      latency: [],
      ...overrides,
    } as AgentEvent
  }

  it('says nothing for the ordinary confidence-proxy case', () => {
    expect(narrate(summary({ has_ground_truth: false }))).toBeNull()
  })

  it('carries one stage per judged retrieval pass when real judgments exist', () => {
    const line = narrate(
      summary({
        has_ground_truth: true,
        stock_bm25: { ndcg10: 0.4693, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
        bm25: { ndcg10: 0.4441, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
        hybrid: { ndcg10: 0.852, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
        reranked: { ndcg10: 0.901, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
      })
    )

    expect(line?.node).toBe('ground_truth')
    expect(line?.weight).toBe('moment')
    expect(line?.groundTruthStages?.map((s) => s.stage)).toEqual([
      'stock_bm25',
      'bm25',
      'hybrid',
      'reranked',
    ])
    expect(line?.groundTruthStages?.[3].ndcg10).toBe(0.901)
    expect(line?.groundTruthStages?.[3].judgedCount).toBe(3)
    expect(line?.text).toContain('0.90')
  })

  it('omits a stage that was skipped rather than showing a fake zero', () => {
    // hybrid/reranked are omitted server-side when their optimization toggle
    // is off — must not be rendered as a judged 0.0 score.
    const line = narrate(
      summary({
        has_ground_truth: true,
        stock_bm25: { ndcg10: 0.47, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
        bm25: { ndcg10: 0.44, mrr: 1, recall20: 1, precision10: 0.3, judged_count: 3 },
      })
    )

    expect(line?.groundTruthStages?.map((s) => s.stage)).toEqual(['stock_bm25', 'bm25'])
  })
})

describe('visibleLines', () => {
  const line = (node: string, id: string) =>
    ({
      id,
      node,
      label: node,
      text: id,
      weight: 'step',
    }) as never

  it('keeps one line per pipeline stage, in the order the stages first ran', () => {
    const shown = visibleLines([
      line('intent_classifier', 'intent'),
      line('query_evaluator', 'alpha'),
      line('retriever', 'search'),
      line('reranker', 'rerank'),
      line('quality_gate', 'gate'),
    ])

    expect(shown.map((l) => l.node)).toEqual([
      'intent_classifier',
      'query_evaluator',
      'retriever',
      'reranker',
      'quality_gate',
    ])
  })

  it('never drops the earliest stage, however many events a turn fires', () => {
    // The regression this replaces: a sliding window of the most recent N
    // lines pushed "Intent Classifier" off the top before it was ever read.
    const shown = visibleLines([
      line('intent_classifier', 'intent'),
      line('query_evaluator', 'alpha'),
      line('query_rewriter', 'rewrite'),
      line('retriever', 'search'),
      line('reranker', 'rerank'),
      line('quality_gate', 'gate'),
    ])

    expect(shown[0].node).toBe('intent_classifier')
    expect(shown).toHaveLength(6)
  })

  it('collapses a quality-gate retry instead of duplicating half the turn', () => {
    // A retry re-runs search and reranking. Those must update their existing
    // lines, not append — otherwise one turn produces eight lines and the
    // opening stages scroll away.
    const shown = visibleLines([
      line('intent_classifier', 'intent'),
      line('retriever', 'search-1'),
      line('reranker', 'rerank-1'),
      line('quality_gate', 'gate-retry'),
      line('retriever', 'search-2'),
      line('reranker', 'rerank-2'),
      line('quality_gate', 'gate-final'),
    ])

    expect(shown).toHaveLength(4)
    expect(shown.map((l) => l.id)).toEqual(['intent', 'search-2', 'rerank-2', 'gate-final'])
    // and the stage keeps the slot it first occupied
    expect(shown[1].node).toBe('retriever')
  })

  it('cannot outgrow the panel — bounded by stage count, not event count', () => {
    const many = Array.from({ length: 40 }, (_, i) => line('retriever', `s${i}`))
    expect(visibleLines(many)).toHaveLength(1)
    expect(visibleLines(many)[0].id).toBe('s39')
  })

  it('shows the enrichment lifecycle as one advancing line', () => {
    const shown = visibleLines([
      line('intent_classifier', 'intent'),
      narrate(enrichment({ status: 'started' }))!,
      narrate(enrichment({ status: 'complete', canonical: 'brown', corrected_from: 'yellow' }))!,
    ])
    const enrichmentLines = shown.filter((l) => l.node === 'enrichment')

    expect(enrichmentLines).toHaveLength(1)
    expect(enrichmentLines[0].enrichment).toBe('complete')
  })

  it('respects the safety cap', () => {
    expect(MAX_VISIBLE_LINES).toBeGreaterThanOrEqual(6)
  })

  it('excludes ground_truth entirely — it renders in its own tab, not among the steps', () => {
    // Used to cap to a single ground-truth-only card (#130), on the
    // assumption ground truth only ever fires in its own dedicated bonus
    // scene. That assumption was false: lookup_judgments() runs on every
    // query in every demo, so a free-typed query mid-Arc-1 can trigger it
    // too, and hiding that turn's real pipeline context whenever it did was
    // surprising. NarratorPanel now renders ground_truth in a separate
    // "Ground Truth" tab instead, so visibleLines (which only ever feeds the
    // "Steps" tab) must return the ordinary pipeline lines untouched even
    // when a ground_truth line is mixed into its input.
    const fullPipeline = [
      line('intent_classifier', 'intent'),
      line('query_evaluator', 'alpha'),
      line('retriever', 'search'),
      line('reranker', 'rerank'),
      line('quality_gate', 'gate'),
    ]
    const groundTruth = { ...line('ground_truth', 'gt'), weight: 'moment' } as never

    const shown = visibleLines([...fullPipeline, groundTruth])

    expect(shown).toHaveLength(5)
    expect(shown.some((l) => l.node === 'ground_truth')).toBe(false)
    expect(shown.map((l) => l.node)).toEqual([
      'intent_classifier',
      'query_evaluator',
      'retriever',
      'reranker',
      'quality_gate',
    ])
  })

  // The enrichment card is roughly four ordinary lines tall. A full pipeline
  // plus that card overflowed a 1920x1080 viewport, and the panel does not
  // scroll by design, so the card and its re-run button rendered below the
  // fold and could not be reached — the arc's entire payoff, invisible at
  // exactly the resolution the demo is presented at (#108). It fit on the
  // larger development display, which is why it survived review.
  describe('when the enrichment card is present', () => {
    const fullPipeline = [
      line('intent_classifier', 'intent'),
      line('query_evaluator', 'alpha'),
      line('query_rewriter', 'rewrite'),
      line('retriever', 'search'),
      line('reranker', 'rerank'),
      line('quality_gate', 'gate'),
    ]

    const shown = () =>
      visibleLines([
        ...fullPipeline,
        narrate(enrichment({ status: 'complete', canonical: 'brown', corrected_from: 'yellow' }))!,
      ])

    it('sheds pipeline lines to make room for it', () => {
      expect(shown().length).toBeLessThan(fullPipeline.length)
    })

    it('always keeps the card itself, and keeps it last', () => {
      const lines = shown()
      expect(lines[lines.length - 1].node).toBe('enrichment')
      expect(lines.filter((l) => l.node === 'enrichment')).toHaveLength(1)
    })

    it('keeps the stages nearest the card rather than the earliest ones', () => {
      // The opposite of the no-card rule: here the card is the point of the
      // turn and the early stages are context the presenter has already
      // narrated by the time it appears.
      expect(shown().map((l) => l.node)).toEqual([
        'retriever',
        'reranker',
        'quality_gate',
        'enrichment',
      ])
    })

    it('does not disturb the cap on turns without a card', () => {
      expect(visibleLines(fullPipeline)).toHaveLength(6)
    })
  })
})
