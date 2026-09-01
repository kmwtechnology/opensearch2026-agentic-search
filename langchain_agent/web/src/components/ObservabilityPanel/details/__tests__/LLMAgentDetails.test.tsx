/**
 * Tests for LLMAgentDetails component — specifically the enrichment
 * flywheel banner, which must be clear and prominent (shown first, not
 * buried in the generic Tool Calls list) whenever trigger_enrichment fires.
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { LLMAgentDetails } from '../LLMAgentDetails'
import type { EnrichmentTriggeredEvent, ObservabilityStep } from '../../../../types/events'

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

function makeStep(overrides: Partial<ObservabilityStep> = {}): ObservabilityStep {
  return {
    id: 'agent-1',
    node: 'agent',
    status: 'complete',
    startTime: new Date(),
    events: [],
    ...overrides,
  }
}

describe('LLMAgentDetails', () => {
  it('renders nothing enrichment-related when no enrichment_triggered event is present', () => {
    render(<LLMAgentDetails step={makeStep()} />)
    expect(screen.queryByText(/Catalog Enrichment Triggered/i)).not.toBeInTheDocument()
  })

  it('shows the prominent enrichment banner when the event is present', () => {
    const step = makeStep({ events: [makeEnrichmentEvent()] })
    const { container } = render(<LLMAgentDetails step={step} />)

    expect(screen.getByText('Catalog Enrichment Triggered')).toBeInTheDocument()
    expect(container.textContent).toContain('camel')
    expect(container.textContent).toContain('brown')
  })

  it('shows in-progress copy while the step is still running', () => {
    const step = makeStep({
      status: 'running',
      events: [makeEnrichmentEvent({ attribute_type: 'material', variant: 'chrome', canonical: 'metal' })],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText(/re-indexing the catalog live/i)).toBeInTheDocument()
  })

  it('shows completed copy once the step is done', () => {
    const step = makeStep({
      status: 'complete',
      events: [makeEnrichmentEvent()],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText(/catalog re-indexed/i)).toBeInTheDocument()
  })

  it('omits the canonical clause when the tool call did not resolve one', () => {
    const step = makeStep({
      events: [makeEnrichmentEvent({ canonical: undefined })],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText('Catalog Enrichment Triggered')).toBeInTheDocument()
    expect(screen.queryByText(/resolved to canonical bucket/i)).not.toBeInTheDocument()
  })

  it('still renders the raw tool call alongside the prominent banner', () => {
    const step = makeStep({
      events: [
        makeEnrichmentEvent(),
        {
          type: 'tool_call',
          timestamp: new Date().toISOString(),
          node: 'agent',
          tool_name: 'trigger_enrichment',
          tool_args: { variant: 'camel', canonical: 'brown', attribute_type: 'color' },
        } as any,
      ],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText('Catalog Enrichment Triggered')).toBeInTheDocument()
    expect(screen.getByText('trigger_enrichment')).toBeInTheDocument()
  })
})
