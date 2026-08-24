/**
 * Tests for QueryEvaluatorDetails component.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { QueryEvaluatorDetails } from '../QueryEvaluatorDetails'
import { useObservabilityStore } from '../../../../stores/observabilityStore'

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

const makeQueryEvaluation = (overrides = {}) => ({
  type: 'query_evaluation' as const,
  timestamp: new Date().toISOString(),
  node: 'query_evaluator' as const,
  query: 'wireless headphones',
  alpha: 0.7,
  query_analysis: 'User is looking for audio gear',
  search_strategy: 'semantic-heavy' as const,
  ...overrides,
})

describe('QueryEvaluatorDetails', () => {
  describe('loading state', () => {
    it('shows waiting message when no query evaluation is available', () => {
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText(/waiting for query evaluation/i)).toBeInTheDocument()
    })
  })

  describe('with query evaluation data', () => {
    beforeEach(() => {
      useObservabilityStore.setState({ queryEvaluation: makeQueryEvaluation() as any })
    })

    it('shows the search strategy badge', () => {
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('semantic-heavy')).toBeInTheDocument()
    })

    it('shows the alpha as percentage semantic weight', () => {
      render(<QueryEvaluatorDetails />)
      // 0.7 alpha => 70% semantic weight
      expect(screen.getByText('70%')).toBeInTheDocument()
      expect(screen.getByText(/semantic weight/i)).toBeInTheDocument()
    })

    it('shows the query analysis text', () => {
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('User is looking for audio gear')).toBeInTheDocument()
    })

    it('renders lexical/semantic scale labels', () => {
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('Lexical (BM25)')).toBeInTheDocument()
      expect(screen.getByText('Semantic (Vector)')).toBeInTheDocument()
    })
  })

  describe('different strategies', () => {
    it('shows lexical-heavy strategy', () => {
      useObservabilityStore.setState({
        queryEvaluation: makeQueryEvaluation({ search_strategy: 'lexical-heavy', alpha: 0.2 }) as any,
      })
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('lexical-heavy')).toBeInTheDocument()
      expect(screen.getByText('20%')).toBeInTheDocument()
    })

    it('shows balanced strategy', () => {
      useObservabilityStore.setState({
        queryEvaluation: makeQueryEvaluation({ search_strategy: 'balanced', alpha: 0.5 }) as any,
      })
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('balanced')).toBeInTheDocument()
      expect(screen.getByText('50%')).toBeInTheDocument()
    })
  })

  describe('edge cases', () => {
    it('handles alpha of 0 (fully lexical)', () => {
      useObservabilityStore.setState({
        queryEvaluation: makeQueryEvaluation({ alpha: 0 }) as any,
      })
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('0%')).toBeInTheDocument()
    })

    it('handles alpha of 1 (fully semantic)', () => {
      useObservabilityStore.setState({
        queryEvaluation: makeQueryEvaluation({ alpha: 1 }) as any,
      })
      render(<QueryEvaluatorDetails />)
      expect(screen.getByText('100%')).toBeInTheDocument()
    })
  })
})
