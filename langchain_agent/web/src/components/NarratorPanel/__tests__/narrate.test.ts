import { describe, expect, it } from 'vitest'
import { narrate, visibleLines } from '../narrate'
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
  it('announces a GAP fill while the re-index is underway (#142: say why, not just that)', () => {
    const line = narrate(enrichment({ status: 'started', canonical: 'brown' }))
    expect(line?.enrichment).toBe('started')
    expect(line?.text).toContain('No products are tagged')
    expect(line?.text).toContain('tan')
  })

  it('drops the redundant "as a X" clause when the term and attribute type are the same word', () => {
    const line = narrate(
      enrichment({
        status: 'started',
        variant: 'waterproof',
        attribute_type: 'waterproof',
        canonical: 'waterproof',
      })
    )
    expect(line?.text).toBe(
      'No products are tagged “waterproof” yet — teaching the catalog this term and re-indexing live.'
    )
    expect(line?.text).not.toContain('as a waterproof')
  })

  it('announces a CORRECTION in progress while the re-index is underway, distinctly from a gap', () => {
    // corrected_from at "started" time is the CURRENT mapping (threaded
    // through from the value-judge lookup, before enrich_attribute even
    // runs) — present means this is a correction, not a fresh addition.
    const line = narrate(
      enrichment({ status: 'started', canonical: 'brown', corrected_from: 'yellow' })
    )
    expect(line?.text).toContain('currently mapped to')
    expect(line?.text).toContain('yellow')
    expect(line?.text).not.toContain('No products are tagged')
  })

  it('narrates a scoped re-tag as checked-vs-changed, not a full rebuild (#147)', () => {
    const line = narrate(
      enrichment({
        status: 'complete',
        canonical: 'brown',
        corrected_from: 'yellow',
        docs_processed: 31,
        docs_scanned: 274,
        duration_seconds: 0.8,
      })
    )
    expect(line?.text).toContain('Re-checked the 274 products that mention it; re-tagged 31 in 0.8s.')
    expect(line?.text).not.toContain('Rebuilt')
  })

  it('distinguishes a CORRECTION from merely learning a new term', () => {
    const corrected = narrate(
      enrichment({
        status: 'complete',
        canonical: 'brown',
        corrected_from: 'yellow',
        docs_processed: 679,
        docs_scanned: 905,
        duration_seconds: 0.9,
      })
    )
    const learned = narrate(
      enrichment({
        status: 'complete',
        variant: 'weatherproof',
        attribute_type: 'waterproof',
        canonical: 'waterproof',
        docs_processed: 12,
        docs_scanned: 40,
        duration_seconds: 0.4,
      })
    )

    expect(corrected?.label).toBe('Correction Applied')
    expect(corrected?.text).toContain('was tagged yellow')
    expect(corrected?.text).toContain('re-tagged 679')
    expect(corrected?.correctedFrom).toBe('yellow')

    expect(learned?.label).toBe('Catalog Learned')
    expect(learned?.text).not.toContain('was tagged')
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

describe('visibleLines', () => {
  const line = (node: string, id: string) =>
    ({
      id,
      node,
      label: node,
      text: id,
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
})
