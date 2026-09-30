/**
 * Component tests for IntentClassifierDetails
 * Tests intent badge display, confidence scoring, and query expansion
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { IntentClassifierDetails } from '../IntentClassifierDetails'
import type { IntentClassificationEvent, QueryExpansionEvent } from '../../../../types/events'

function intentEvent(overrides: Partial<IntentClassificationEvent> = {}): IntentClassificationEvent {
  return {
    type: 'intent_classification',
    node: 'intent_classifier',
    timestamp: new Date().toISOString(),
    intent: 'search',
    confidence: 0.95,
    reasoning: 'User is searching for a product',
    user_query: 'Find wireless headphones',
    ...overrides,
  }
}

const expansion: QueryExpansionEvent = {
  type: 'query_expansion',
  node: 'retriever',
  timestamp: new Date().toISOString(),
  original_query: 'Any cheaper?',
  expanded_query: 'Find cheaper product alternatives',
  expansion_reason: 'Resolved pronoun reference',
}

describe('IntentClassifierDetails Component', () => {
  it('renders loading state when no event provided', () => {
    const { container } = render(<IntentClassifierDetails />)
    expect(screen.getByText(/Classifying intent/i)).toBeInTheDocument()
    expect(container.querySelector('.animate-pulse')).toBeInTheDocument()
  })

  it('renders intent, reasoning and query', () => {
    render(<IntentClassifierDetails event={intentEvent()} />)
    expect(screen.getByText('search')).toBeInTheDocument()
    expect(screen.getByText('User is searching for a product')).toBeInTheDocument()
    expect(screen.getByText('Find wireless headphones')).toBeInTheDocument()
  })

  it('shows dash for empty query', () => {
    render(<IntentClassifierDetails event={intentEvent({ user_query: '' })} />)
    expect(screen.getByText('—')).toBeInTheDocument()
  })

  describe('Confidence', () => {
    it('shows high confidence (>= 0.7) as a green percentage with no warning', () => {
      render(<IntentClassifierDetails event={intentEvent({ confidence: 0.85 })} />)
      // Projector palette (#103): #065F46 clears 7:1 on the light ground.
      expect(screen.getByText('85%').className).toContain('#065F46')
      expect(screen.queryByText(/Low confidence/i)).not.toBeInTheDocument()
    })

    it('shows low confidence (< 0.7) in rust with the clarification warning', () => {
      render(<IntentClassifierDetails event={intentEvent({ confidence: 0.65 })} />)
      // The same rust the quality gate uses.
      expect(screen.getByText('65%').className).toContain('#9A3412')
      expect(screen.getByText(/Low confidence may trigger clarification/i)).toBeInTheDocument()
    })

    it('handles boundary confidence values', () => {
      for (const confidence of [0, 0.01, 0.69, 0.7, 1.0]) {
        const { unmount } = render(<IntentClassifierDetails event={intentEvent({ confidence })} />)
        expect(screen.getByText(`${Math.round(confidence * 100)}%`)).toBeInTheDocument()
        unmount()
      }
    })

    it('defaults a missing confidence to 100%', () => {
      render(<IntentClassifierDetails event={intentEvent({ confidence: undefined })} />)
      expect(screen.getByText('100%')).toBeInTheDocument()
    })
  })

  describe('Query Expansion', () => {
    it('displays original query, expanded query and reason when provided', () => {
      render(<IntentClassifierDetails event={intentEvent()} queryExpansion={expansion} />)
      expect(screen.getByText(/QUERY EXPANDED/i)).toBeInTheDocument()
      expect(screen.getByText('Any cheaper?')).toBeInTheDocument()
      expect(screen.getByText('Find cheaper product alternatives')).toBeInTheDocument()
      expect(screen.getByText('Resolved pronoun reference')).toBeInTheDocument()
    })

    it('does not display expansion when null', () => {
      render(<IntentClassifierDetails event={intentEvent()} queryExpansion={null} />)
      expect(screen.queryByText(/QUERY EXPANDED/i)).not.toBeInTheDocument()
    })
  })
})
