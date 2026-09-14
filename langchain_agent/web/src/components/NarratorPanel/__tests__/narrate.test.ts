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

    expect(line?.text).toContain('semantic heavy')
    expect(line?.text).toContain('0.85')
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

describe('visibleLines', () => {
  const step = (id: string) => ({
    id,
    node: 'retriever' as const,
    label: 'Knowledge Search',
    text: id,
    weight: 'step' as const,
  })

  it('never returns more lines than the panel can show without scrolling', () => {
    const lines = Array.from({ length: 12 }, (_, i) => step(`s${i}`))
    expect(visibleLines(lines)).toHaveLength(MAX_VISIBLE_LINES)
  })

  it('keeps the newest lines', () => {
    const lines = Array.from({ length: 8 }, (_, i) => step(`s${i}`))
    expect(visibleLines(lines).at(-1)?.id).toBe('s7')
  })

  it('collapses the enrichment lifecycle into one advancing line, not four', () => {
    const lines = [
      step('a'),
      narrate(enrichment({ status: 'started' }))!,
      narrate(enrichment({ status: 'complete', canonical: 'brown', corrected_from: 'yellow' }))!,
    ]
    const shown = visibleLines(lines)
    const enrichmentLines = shown.filter((l) => l.node === 'enrichment')

    expect(enrichmentLines).toHaveLength(1)
    expect(enrichmentLines[0].enrichment).toBe('complete')
    // and it holds the position the lifecycle started in
    expect(shown[1].node).toBe('enrichment')
  })
})
