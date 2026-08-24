/**
 * Component tests for IntentClassifierDetails
 * Tests intent badge display, confidence scoring, and query expansion
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { IntentClassifierDetails } from '../IntentClassifierDetails'
import type { IntentClassificationEvent, QueryExpansionEvent } from '../../../../types/events'

describe('IntentClassifierDetails Component', () => {
  describe('Loading State', () => {
    it('renders loading state when no event provided', () => {
      render(<IntentClassifierDetails />)
      expect(screen.getByText(/Classifying intent/i)).toBeInTheDocument()
    })

    it('shows animated pulse during loading', () => {
      const { container } = render(<IntentClassifierDetails />)
      const loadingElement = container.querySelector('.animate-pulse')
      expect(loadingElement).toBeInTheDocument()
    })
  })

  describe('Intent Display', () => {
    const mockEvent: IntentClassificationEvent = {
      type: 'intent_classification',
      node: 'intent_classifier',
      timestamp: new Date().toISOString(),
      intent: 'search',
      confidence: 0.95,
      reasoning: 'User is searching for a product',
      user_query: 'Find wireless headphones',
    }

    it('renders intent label and value', () => {
      render(<IntentClassifierDetails event={mockEvent} />)
      expect(screen.getByText(/Intent:/i)).toBeInTheDocument()
      expect(screen.getByText('search')).toBeInTheDocument()
    })

    it('displays different intent types', () => {
      const intents = ['search', 'comparison', 'attribute_filter', 'follow_up', 'summary']
      
      intents.forEach(intent => {
        const event: IntentClassificationEvent = {
          ...mockEvent,
          intent: intent as any,
        }
        const { unmount } = render(<IntentClassifierDetails event={event} />)
        expect(screen.getByText(intent)).toBeInTheDocument()
        unmount()
      })
    })
  })

  describe('Confidence Display', () => {
    it('shows confidence as percentage', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.85,
        reasoning: 'Test',
        user_query: 'Find headphones',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText(/Confidence:/i)).toBeInTheDocument()
      expect(screen.getByText('85%')).toBeInTheDocument()
    })

    it('displays confidence bar with correct width', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.75,
        reasoning: 'Test',
        user_query: 'Test',
        }
      const { container } = render(<IntentClassifierDetails event={event} />)
      const confidenceBar = container.querySelector('div[style*="width"]')
      expect(confidenceBar).toBeInTheDocument()
    })

    it('uses green color for high confidence (>= 0.7)', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.95,
        reasoning: 'Test',
        user_query: 'Test',
        }
      render(<IntentClassifierDetails event={event} />)
      const confidenceText = screen.getByText('95%')
      expect(confidenceText.className).toContain('green')
    })

    it('uses yellow color for low confidence (< 0.7)', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.65,
        reasoning: 'Test',
        user_query: 'Test',
        }
      render(<IntentClassifierDetails event={event} />)
      const confidenceText = screen.getByText('65%')
      expect(confidenceText.className).toContain('yellow')
    })
  })

  describe('Low Confidence Warning', () => {
    it('shows warning for low confidence (< 0.7)', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.55,
        reasoning: 'Test',
        user_query: 'Test',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText(/Low confidence/i)).toBeInTheDocument()
      expect(screen.getByText(/clarification/i)).toBeInTheDocument()
    })

    it('does not show warning for high confidence', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.95,
        reasoning: 'Test',
        user_query: 'Test',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.queryByText(/Low confidence/i)).not.toBeInTheDocument()
    })
  })

  describe('Reasoning and Query Display', () => {
    it('displays reasoning text', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.9,
        reasoning: 'User is searching for products',
        user_query: 'Find headphones',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText(/Reason:/i)).toBeInTheDocument()
      expect(screen.getByText('User is searching for products')).toBeInTheDocument()
    })

    it('displays user query', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.9,
        reasoning: 'Test',
        user_query: 'Find wireless headphones',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText(/Query:/i)).toBeInTheDocument()
      expect(screen.getByText('Find wireless headphones')).toBeInTheDocument()
    })

    it('shows dash for empty query', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.9,
        reasoning: 'Test',
        user_query: '',
        }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText('—')).toBeInTheDocument()
    })
  })

  describe('Query Expansion', () => {
    const baseEvent: IntentClassificationEvent = {
      type: 'intent_classification',
      node: 'intent_classifier',
      timestamp: new Date().toISOString(),
      intent: 'follow_up',
      confidence: 0.88,
      reasoning: 'Follow-up',
      user_query: 'Cheaper?',
    }

    it('displays query expansion section when provided', () => {
      const expansion: QueryExpansionEvent = {
        type: 'query_expansion',
        node: 'retriever',
        timestamp: new Date().toISOString(),
        original_query: 'Cheaper?',
        expanded_query: 'Find cheaper wireless headphones',
        expansion_reason: 'Expanded vague reference',
      }
      render(<IntentClassifierDetails event={baseEvent} queryExpansion={expansion} />)
      expect(screen.getByText(/QUERY EXPANDED/i)).toBeInTheDocument()
    })

    it('displays original and expanded queries', () => {
      const expansion: QueryExpansionEvent = {
        type: 'query_expansion',
        node: 'retriever',
        timestamp: new Date().toISOString(),
        original_query: 'Any cheaper?',
        expanded_query: 'Find cheaper product alternatives',
        expansion_reason: 'Resolved pronoun reference',
      }
      render(<IntentClassifierDetails event={baseEvent} queryExpansion={expansion} />)
      expect(screen.getByText('Any cheaper?')).toBeInTheDocument()
      expect(screen.getByText('Find cheaper product alternatives')).toBeInTheDocument()
    })

    it('displays expansion reason', () => {
      const expansion: QueryExpansionEvent = {
        type: 'query_expansion',
        node: 'retriever',
        timestamp: new Date().toISOString(),
        original_query: 'Cheaper?',
        expanded_query: 'Find cheaper products',
        expansion_reason: 'Resolved vague pronoun to product category',
      }
      render(<IntentClassifierDetails event={baseEvent} queryExpansion={expansion} />)
      expect(screen.getByText('Resolved vague pronoun to product category')).toBeInTheDocument()
    })

    it('does not display expansion when null', () => {
      render(<IntentClassifierDetails event={baseEvent} queryExpansion={null} />)
      expect(screen.queryByText(/QUERY EXPANDED/i)).not.toBeInTheDocument()
    })

    it('does not display expansion when undefined', () => {
      render(<IntentClassifierDetails event={baseEvent} />)
      expect(screen.queryByText(/QUERY EXPANDED/i)).not.toBeInTheDocument()
    })
  })

  describe('Edge Cases', () => {
    it('handles boundary confidence values', () => {
      const confidences = [0, 0.01, 0.7, 0.69, 1.0]
      
      confidences.forEach(confidence => {
        const event: IntentClassificationEvent = {
          type: 'intent_classification',
          node: 'intent_classifier',
          timestamp: new Date().toISOString(),
          intent: 'search',
          confidence,
          reasoning: 'Test',
          user_query: 'Test',
            }
        const { unmount } = render(<IntentClassifierDetails event={event} />)
        const percent = Math.round(confidence * 100)
        expect(screen.getByText(`${percent}%`)).toBeInTheDocument()
        unmount()
      })
    })

    it('handles very long reasoning text', () => {
      const longText = 'A'.repeat(500)
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: 0.9,
        reasoning: longText,
        user_query: 'Test',
      }
      render(<IntentClassifierDetails event={event} />)
      expect(screen.getByText(longText)).toBeInTheDocument()
    })

    it('handles missing confidence gracefully', () => {
      const event: IntentClassificationEvent = {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        confidence: undefined as any,
        reasoning: 'Test',
        user_query: 'Test',
      }
      render(<IntentClassifierDetails event={event} />)
      // Should default to 1.0 (100%)
      expect(screen.getByText('100%')).toBeInTheDocument()
    })
  })
})
