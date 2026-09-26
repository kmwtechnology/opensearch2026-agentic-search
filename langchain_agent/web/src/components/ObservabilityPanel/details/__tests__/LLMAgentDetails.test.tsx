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
      events: [
        makeEnrichmentEvent({ attribute_type: 'waterproof', variant: 'weatherproof', canonical: 'waterproof' }),
      ],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText(/re-tagging the matching products live/i)).toBeInTheDocument()
  })

  it('shows completed copy once the step is done', () => {
    const step = makeStep({
      status: 'complete',
      events: [makeEnrichmentEvent()],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText(/catalog re-indexed/i)).toBeInTheDocument()
  })

  it('shows the real measured duration and doc count once complete (#80)', () => {
    const step = makeStep({
      status: 'complete',
      events: [makeEnrichmentEvent({ duration_seconds: 21.5, docs_processed: 9618 })],
    })
    const { container } = render(<LLMAgentDetails step={step} />)

    expect(container.textContent).toContain('9618 products in 21.5s')
  })

  it('reports re-tagged of scanned for a scoped re-tag (#147)', () => {
    const step = makeStep({
      status: 'complete',
      events: [makeEnrichmentEvent({ duration_seconds: 0.8, docs_processed: 31, docs_scanned: 274 })],
    })
    const { container } = render(<LLMAgentDetails step={step} />)

    expect(container.textContent).toContain('31 of 274 matching products re-tagged in 0.8s')
  })

  it('falls back to generic completed copy when duration_seconds is not available', () => {
    const step = makeStep({
      status: 'complete',
      events: [makeEnrichmentEvent({ duration_seconds: undefined, docs_processed: undefined })],
    })
    const { container } = render(<LLMAgentDetails step={step} />)

    expect(container.textContent).not.toMatch(/\d+(\.\d+)?s/)
    expect(screen.getByText(/catalog re-indexed\. this query/i)).toBeInTheDocument()
  })

  it('does not show a live/running duration while the step is still in progress', () => {
    const step = makeStep({
      status: 'running',
      events: [makeEnrichmentEvent({ duration_seconds: 21.5, docs_processed: 9618 })],
    })
    render(<LLMAgentDetails step={step} />)

    expect(screen.getByText(/re-tagging the matching products live/i)).toBeInTheDocument()
    expect(screen.queryByText(/9618 products/i)).not.toBeInTheDocument()
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
