/**
 * Tests for StepCard component — specifically that an enrichment_triggered
 * event makes itself visible in the collapsed header (no expand required)
 * with a distinct emerald treatment, since this is the moment presenters
 * most need to be unmissable during a live demo.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StepCard } from '../StepCard'
import { useObservabilityStore } from '../../../stores/observabilityStore'
import type { EnrichmentTriggeredEvent, ObservabilityStep } from '../../../types/events'

const INITIAL_OBS = {
  isExecuting: false,
  currentNode: null,
  steps: [],
  conversationContext: null,
  queryEvaluation: null,
  intentClassification: null,
  queryExpansion: null,
  qualityGate: null,
  searchCandidates: [],
  rerankedDocuments: [],
  pipelineSummary: null,
  enrichmentTriggered: null,
  historicalSnapshot: null,
  searchStatus: 'idle' as const,
  rerankerStatus: 'idle' as const,
  searchProgressMessage: null,
  rerankerProgressMessage: null,
  rerankerProgress: 0,
  expandedSteps: new Set<string>(),
  expandedEvents: new Set<string>(),
}

beforeEach(() => {
  useObservabilityStore.setState(INITIAL_OBS)
})

function makeStep(overrides: Partial<ObservabilityStep> = {}): ObservabilityStep {
  return {
    id: 'agent-1',
    node: 'agent',
    status: 'complete',
    startTime: new Date(),
    events: [],
    summary: 'Response generated (240 chars)',
    ...overrides,
  }
}

function makeEnrichmentEvent(overrides: Partial<EnrichmentTriggeredEvent> = {}): EnrichmentTriggeredEvent {
  return {
    type: 'enrichment_triggered',
    timestamp: new Date().toISOString(),
    node: 'agent',
    attribute_type: 'waterproof',
    variant: 'weatherproof',
    canonical: 'waterproof',
    ...overrides,
  }
}

describe('StepCard', () => {
  it('shows the generic step summary when no enrichment event is present', () => {
    render(<StepCard step={makeStep()} index={5} />)
    expect(screen.getByText('Response generated (240 chars)')).toBeInTheDocument()
  })

  it('shows the enrichment badge in the collapsed header without expanding', () => {
    const step = makeStep({ events: [makeEnrichmentEvent()] })
    const { container } = render(<StepCard step={step} index={5} />)

    expect(screen.getByText(/Enrichment:/)).toBeInTheDocument()
    expect(container.textContent).toContain('weatherproof')
    expect(container.textContent).toContain('waterproof')
    // The generic summary is replaced, not duplicated, when enrichment fires.
    expect(screen.queryByText('Response generated (240 chars)')).not.toBeInTheDocument()
  })

  it('still labels the step "LLM Agent" when enrichment fires', () => {
    const step = makeStep({ events: [makeEnrichmentEvent()] })
    render(<StepCard step={step} index={5} />)
    expect(screen.getByText('LLM Agent')).toBeInTheDocument()
  })
})

describe('StepCard reranker label (#87)', () => {
  function makeRerankerStep(reranker_type?: string): ObservabilityStep {
    return {
      id: 'reranker-1',
      node: 'reranker',
      status: 'complete',
      startTime: new Date(),
      summary: '40 documents reranked (max=0.558)',
      events: reranker_type
        ? [
            {
              type: 'reranker_result',
              timestamp: new Date().toISOString(),
              node: 'reranker',
              results: [],
              reranking_changed_order: false,
              reranker_type,
            } as any,
          ]
        : [],
    }
  }

  it('labels the step "Cross-Encoder Reranker" when reranker_type is cross-encoder', () => {
    render(<StepCard step={makeRerankerStep('cross-encoder')} index={4} />)
    expect(screen.getByText('Cross-Encoder Reranker')).toBeInTheDocument()
    expect(screen.queryByText('LLM Reranker')).not.toBeInTheDocument()
  })

  it('labels the step "LLM Reranker" when reranker_type is gemini', () => {
    render(<StepCard step={makeRerankerStep('gemini')} index={4} />)
    expect(screen.getByText('LLM Reranker')).toBeInTheDocument()
  })

  it('falls back to a neutral "Reranker" label before the result event arrives', () => {
    render(<StepCard step={makeRerankerStep()} index={4} />)
    expect(screen.getByText('Reranker')).toBeInTheDocument()
    expect(screen.queryByText('LLM Reranker')).not.toBeInTheDocument()
    expect(screen.queryByText('Cross-Encoder Reranker')).not.toBeInTheDocument()
  })
})
