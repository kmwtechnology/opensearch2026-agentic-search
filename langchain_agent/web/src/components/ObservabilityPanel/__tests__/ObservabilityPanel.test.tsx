/**
 * Tests for the ObservabilityPanel header — specifically the persistent
 * enrichment-flywheel banner, the most prominent possible surface (visible
 * even without looking at the step timeline) for the moment the agent
 * decides to fix the catalog instead of just the query.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ObservabilityPanel } from '../index'
import { useObservabilityStore } from '../../../stores/observabilityStore'
import type { EnrichmentTriggeredEvent } from '../../../types/events'

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
  documentGradingSummary: null,
  responseGrading: null,
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

function makeEnrichmentEvent(overrides: Partial<EnrichmentTriggeredEvent> = {}): EnrichmentTriggeredEvent {
  return {
    type: 'enrichment_triggered',
    timestamp: new Date().toISOString(),
    node: 'agent',
    attribute_type: 'color',
    variant: 'camel',
    canonical: 'brown',
    ...overrides,
  }
}

describe('ObservabilityPanel', () => {
  it('shows no enrichment banner when nothing has been triggered', () => {
    render(<ObservabilityPanel />)
    expect(screen.queryByText(/Catalog Enrichment Triggered/i)).not.toBeInTheDocument()
  })

  it('shows the enrichment banner once trigger_enrichment has fired', () => {
    useObservabilityStore.setState({ enrichmentTriggered: makeEnrichmentEvent() })
    const { container } = render(<ObservabilityPanel />)

    expect(screen.getByText(/Catalog Enrichment Triggered/i)).toBeInTheDocument()
    expect(container.textContent).toContain('color')
    expect(container.textContent).toContain('camel')
  })

  it('says "in progress" while still executing and "complete" once done', () => {
    useObservabilityStore.setState({
      enrichmentTriggered: makeEnrichmentEvent(),
      isExecuting: true,
    })
    const { rerender } = render(<ObservabilityPanel />)
    expect(screen.getByText(/in progress/i)).toBeInTheDocument()

    useObservabilityStore.setState({ isExecuting: false })
    rerender(<ObservabilityPanel />)
    expect(screen.getByText(/complete/i)).toBeInTheDocument()
  })
})
