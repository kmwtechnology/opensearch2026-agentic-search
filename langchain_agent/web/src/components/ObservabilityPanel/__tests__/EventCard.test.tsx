/**
 * Tests for EventCard component.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { EventCard } from '../EventCard'
import { useObservabilityStore } from '../../../stores/observabilityStore'
import type { AgentEvent } from '../../../types/events'

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

function makeEvent(overrides: Partial<AgentEvent> = {}): AgentEvent {
  return {
    type: 'query_evaluation',
    timestamp: new Date().toISOString(),
    node: 'query_evaluator',
    ...overrides,
  } as AgentEvent
}

describe('EventCard', () => {
  describe('header display', () => {
    it('shows the event type label', () => {
      render(<EventCard event={makeEvent({ type: 'query_evaluation' })} index={0} />)
      expect(screen.getByText('Query Evaluation')).toBeInTheDocument()
    })

    it('shows the label for hybrid_search_start events', () => {
      render(<EventCard event={makeEvent({ type: 'hybrid_search_start' })} index={0} />)
      expect(screen.getByText('Search Start')).toBeInTheDocument()
    })

    it('shows the label for agent_complete events', () => {
      render(<EventCard event={makeEvent({ type: 'agent_complete' })} index={0} />)
      expect(screen.getByText('Agent Complete')).toBeInTheDocument()
    })

    it('shows the label for agent_error events', () => {
      render(<EventCard event={makeEvent({ type: 'agent_error' })} index={0} />)
      expect(screen.getByText('Agent Error')).toBeInTheDocument()
    })

    it('falls back to the raw type string for unknown event types', () => {
      render(<EventCard event={makeEvent({ type: 'unknown_custom_event' })} index={0} />)
      expect(screen.getByText('unknown_custom_event')).toBeInTheDocument()
    })

    it('shows the Raw toggle button', () => {
      render(<EventCard event={makeEvent()} index={0} />)
      expect(screen.getByText(/raw/i)).toBeInTheDocument()
    })
  })

  describe('expand/collapse', () => {
    it('does not show expanded content initially', () => {
      render(
        <EventCard
          event={{ ...makeEvent(), query: 'test query', alpha: 0.6, query_analysis: 'semantic', search_strategy: 'balanced' } as any}
          index={0}
        />
      )
      // Expanded details show alpha percentage but only when expanded
      expect(screen.queryByText(/alpha/i)).not.toBeInTheDocument()
    })

    it('expands the card when the header button is clicked', async () => {
      const user = userEvent.setup()
      const event = {
        ...makeEvent(),
        query: 'test query',
        alpha: 0.6,
        query_analysis: 'semantic heavy',
        search_strategy: 'balanced',
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Query Evaluation'))
      expect(screen.getByText(/alpha/i)).toBeInTheDocument()
    })

    it('collapses the card on second click', async () => {
      const user = userEvent.setup()
      const event = {
        ...makeEvent(),
        query: 'test query',
        alpha: 0.6,
        query_analysis: 'semantic heavy',
        search_strategy: 'balanced',
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Query Evaluation'))
      await user.click(screen.getByText('Query Evaluation'))
      expect(screen.queryByText(/alpha/i)).not.toBeInTheDocument()
    })
  })

  describe('raw view toggle', () => {
    it('shows raw JSON when the Raw button is clicked', async () => {
      const user = userEvent.setup()
      const event = {
        ...makeEvent(),
        query: 'raw-query',
        alpha: 0.5,
        query_analysis: 'a',
        search_strategy: 'balanced',
      } as any

      const { container } = render(<EventCard event={event} index={0} />)
      // First expand so the content area is visible
      await user.click(screen.getByText('Query Evaluation'))
      // Then switch to raw view using the button's title attribute
      await user.click(screen.getByTitle('Toggle raw JSON view'))
      // Raw view renders JSON in a <pre> element
      const pre = container.querySelector('pre')
      expect(pre).not.toBeNull()
      expect(pre?.textContent).toContain('query_evaluation')
    })
  })

  describe('event-specific details', () => {
    it('shows document_grade details when expanded', async () => {
      const user = userEvent.setup()
      const event = {
        type: 'document_grade',
        timestamp: new Date().toISOString(),
        node: 'retriever',
        source: 'doc-1',
        relevant: true,
        score: 0.88,
        reasoning: 'Highly relevant',
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Document Grade'))
      expect(screen.getByText('doc-1')).toBeInTheDocument()
      expect(screen.getByText('Highly relevant')).toBeInTheDocument()
    })

    it('shows agent_error details when expanded', async () => {
      const user = userEvent.setup()
      const event = {
        type: 'agent_error',
        timestamp: new Date().toISOString(),
        node: 'agent',
        error: 'Something exploded',
        recoverable: false,
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Agent Error'))
      expect(screen.getByText('Something exploded')).toBeInTheDocument()
    })

    it('shows query_transformation details when expanded', async () => {
      const user = userEvent.setup()
      const event = {
        type: 'query_transformation',
        timestamp: new Date().toISOString(),
        node: 'retriever',
        iteration: 1,
        max_iterations: 3,
        original_query: 'wireless headphones',
        transformed_query: 'noise-canceling wireless headphones',
        reasons: ['More specific'],
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Query Transform'))
      expect(screen.getByText('wireless headphones')).toBeInTheDocument()
      expect(screen.getByText('noise-canceling wireless headphones')).toBeInTheDocument()
      expect(screen.getByText('More specific')).toBeInTheDocument()
    })

    it('shows tool_call details when expanded', async () => {
      const user = userEvent.setup()
      const event = {
        type: 'tool_call',
        timestamp: new Date().toISOString(),
        node: 'agent',
        tool_name: 'search_products',
        tool_args: { query: 'headphones' },
      } as any

      render(<EventCard event={event} index={0} />)
      await user.click(screen.getByText('Tool Call'))
      expect(screen.getByText('search_products')).toBeInTheDocument()
    })
  })

  describe('expandedEvents store integration', () => {
    it('toggles expandedEvents in the observability store', async () => {
      const user = userEvent.setup()
      const event = makeEvent()

      render(<EventCard event={event} index={5} />)
      await user.click(screen.getByText('Query Evaluation'))

      const { expandedEvents } = useObservabilityStore.getState()
      expect(expandedEvents.size).toBe(1)
    })
  })
})
