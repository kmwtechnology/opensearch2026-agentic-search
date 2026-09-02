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
    attribute_type: 'material',
    variant: 'chrome',
    canonical: 'metal',
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
    expect(container.textContent).toContain('chrome')
    expect(container.textContent).toContain('metal')
    // The generic summary is replaced, not duplicated, when enrichment fires.
    expect(screen.queryByText('Response generated (240 chars)')).not.toBeInTheDocument()
  })

  it('still labels the step "LLM Agent" when enrichment fires', () => {
    const step = makeStep({ events: [makeEnrichmentEvent()] })
    render(<StepCard step={step} index={5} />)
    expect(screen.getByText('LLM Agent')).toBeInTheDocument()
  })
})
