/**
 * Tests for SearchDetails component.
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { SearchDetails } from '../SearchDetails'
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

describe('SearchDetails (retriever mode)', () => {
  describe('idle state with no data', () => {
    it('shows waiting message when nothing is running and no candidates', () => {
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText(/waiting for search results/i)).toBeInTheDocument()
    })
  })

  describe('running state', () => {
    it('shows "in progress" banner when searchStatus is running', () => {
      useObservabilityStore.setState({ searchStatus: 'running' })
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText(/in progress/i)).toBeInTheDocument()
    })
  })

  describe('with search candidates', () => {
    const candidates = [
      { product_id: 'p1', title: 'Headphones', source: 'doc-1.json', score: 0.92, snippet: 'Great headphones' },
      { product_id: 'p2', title: 'Earbuds', source: 'doc-2.json', score: 0.85, snippet: 'Compact earbuds' },
    ]

    beforeEach(() => {
      useObservabilityStore.setState({
        searchCandidates: candidates as any,
        searchStatus: 'done',
      })
    })

    it('shows Search Candidates header', () => {
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText(/search candidates/i)).toBeInTheDocument()
    })

    it('shows the count of candidates found', () => {
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText(/2 found/i)).toBeInTheDocument()
    })

    it('renders candidate source names', () => {
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText('doc-1.json')).toBeInTheDocument()
      expect(screen.getByText('doc-2.json')).toBeInTheDocument()
    })

    it('shows search complete banner', () => {
      render(<SearchDetails mode="retriever" />)
      expect(screen.getByText(/complete/i)).toBeInTheDocument()
    })
  })
})

describe('SearchDetails (reranker mode)', () => {
  describe('idle state', () => {
    it('shows waiting message when no candidates and no reranked docs', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText(/waiting for search results/i)).toBeInTheDocument()
    })
  })

  describe('running state', () => {
    it('shows reranking in progress banner', () => {
      useObservabilityStore.setState({ rerankerStatus: 'running' })
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText(/reranking results/i)).toBeInTheDocument()
    })
  })

  describe('with reranked documents', () => {
    const rerankedDocs = [
      {
        rank: 1,
        source: 'product-123',
        score: 0.95,
        rank_change: 2,
        snippet: 'Best headphones',
        page_content: 'Full content here',
        vector_score: 0.9,
        text_score: 0.85,
        rrf_score: undefined,
        url: undefined,
      },
      {
        rank: 2,
        source: 'product-456',
        score: 0.80,
        rank_change: 0,
        snippet: 'Good headphones',
        page_content: undefined,
        vector_score: undefined,
        text_score: undefined,
        rrf_score: undefined,
        url: 'https://example.com/product',
      },
    ]

    beforeEach(() => {
      useObservabilityStore.setState({
        rerankedDocuments: rerankedDocs as any,
        rerankerStatus: 'done',
      })
    })

    it('shows Reranked Results header', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText(/reranked results/i)).toBeInTheDocument()
    })

    it('shows document count', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText(/2 documents/i)).toBeInTheDocument()
    })

    it('shows document sources', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText('product-123')).toBeInTheDocument()
    })

    it('shows reranker score', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText('0.950')).toBeInTheDocument()
    })

    it('shows "Reranking complete" banner', () => {
      render(<SearchDetails mode="reranker" />)
      expect(screen.getByText(/reranking complete/i)).toBeInTheDocument()
    })

    it('shows document URL as a link when available', () => {
      render(<SearchDetails mode="reranker" />)
      const link = screen.getByRole('link', { name: /example.com/i })
      expect(link).toBeInTheDocument()
      expect(link).toHaveAttribute('href', 'https://example.com/product')
    })

    it('expands document to show component scores when View more is clicked', async () => {
      const user = userEvent.setup()
      render(<SearchDetails mode="reranker" />)
      const viewMoreButtons = screen.getAllByText(/view more/i)
      await user.click(viewMoreButtons[0])
      expect(screen.getByText(/vector:/i)).toBeInTheDocument()
    })
  })
})
