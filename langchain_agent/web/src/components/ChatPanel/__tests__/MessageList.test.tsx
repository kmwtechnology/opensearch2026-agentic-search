/**
 * Tests for the MessageList pre-token status card label — specifically that
 * a tool-offer/correction check's reason-specific headline (#142; was one
 * generic "Checking whether a tool is needed" label) only appears when that
 * check is actually eligible to run this turn, not on every agent-node turn
 * before the first token (#106).
 */

import { describe, it, expect, beforeEach } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MessageList } from '../MessageList'
import { useChatStore } from '../../../stores/chatStore'
import { useObservabilityStore } from '../../../stores/observabilityStore'
import type { ChatMessage } from '../../../stores/chatStore'

const INITIAL_OBS = {
  isExecuting: true,
  currentNode: 'agent' as const,
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

function makeUserMessage(overrides: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: 'msg-1',
    role: 'user',
    content: 'Find brown boots',
    timestamp: new Date('2026-01-01'),
    ...overrides,
  }
}

beforeEach(() => {
  useObservabilityStore.setState(INITIAL_OBS)
  useChatStore.setState({
    messages: [makeUserMessage()],
    streamingContent: '',
    isProcessing: true,
  })
})

describe('MessageList — pre-token agent status label (#106)', () => {
  it('does NOT claim a tool check on a plain attribute_filter turn with results', () => {
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'attribute_filter',
        user_query: 'brown boots',
        reasoning: 'attribute lookup',
      },
      searchCandidates: [{ source: 'p1', snippet: 'a brown boot' }],
    })
    render(<MessageList />)
    expect(screen.queryByText('Checking whether a tag needs correcting')).not.toBeInTheDocument()
    expect(
      screen.queryByText('Checking whether the catalog is missing this attribute')
    ).not.toBeInTheDocument()
    expect(screen.getByText('Thinking through the answer')).toBeInTheDocument()
  })

  it('shows the correction headline + detail on a follow_up turn carrying dispute language', () => {
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'follow_up',
        user_query: "that's not tan, that's tagged yellow which is wrong",
        reasoning: 'dispute language',
      },
    })
    render(<MessageList />)
    expect(screen.getByText('Checking whether a tag needs correcting')).toBeInTheDocument()
    expect(
      screen.getByText('You may be disputing a tag from an earlier answer — deciding whether to correct it.')
    ).toBeInTheDocument()
  })

  it('does NOT claim a tag dispute on a refinement turn with no dispute language', () => {
    // Regression (PR review, #142): the backend runs _detect_correction_signal
    // BEFORE it will offer the correction tool, so a plain refinement like
    // arc 1 turn 2 goes straight to answer generation. Claiming "checking
    // whether a tag needs correcting" there is the #106 failure mode with a
    // more confident voice — specific, and specifically wrong.
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'refinement',
        user_query: 'only size 10',
        reasoning: 'narrowing the prior result set',
      },
      searchCandidates: [{ source: 'p1', snippet: 'a blue running shoe' }],
    })
    render(<MessageList />)
    expect(screen.queryByText('Checking whether a tag needs correcting')).not.toBeInTheDocument()
    expect(screen.getByText('Thinking through the answer')).toBeInTheDocument()
  })

  it('shows the gap headline + detail (naming the filter) on an attribute_filter turn with zero candidates', () => {
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'attribute_filter',
        user_query: 'camel colored coats',
        reasoning: 'attribute lookup',
      },
      searchCandidates: [],
      steps: [
        {
          id: 'step-retriever',
          node: 'retriever',
          status: 'complete',
          startTime: new Date(),
          events: [
            {
              type: 'opensearch_query',
              node: 'retriever',
              timestamp: new Date().toISOString(),
              query: 'camel colored coats',
              alpha: 0.25,
              intent: 'attribute_filter',
              query_type: 'hybrid',
              index: 'agentic_hybrid_search_docs',
              body: {},
              filter_summary: 'color: camel',
            },
          ],
        },
      ],
    })
    render(<MessageList />)
    expect(screen.getByText('Checking whether the catalog is missing this attribute')).toBeInTheDocument()
    expect(
      screen.getByText('No products matched color: camel — deciding whether to teach the catalog this term.')
    ).toBeInTheDocument()
  })

  it('shows the retry-gap headline + detail when the quality gate retried and still scored below the relevance floor', () => {
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'search',
        user_query: 'something obscure',
        reasoning: 'search',
      },
      qualityGate: {
        type: 'quality_gate',
        node: 'quality_gate',
        timestamp: new Date().toISOString(),
        triggered: true,
        original_alpha: 0.5,
        max_score: 0.05,
        threshold: 0.5,
        reason: 'low relevance',
      },
    })
    render(<MessageList />)
    expect(screen.getByText('Checking whether the catalog is missing something')).toBeInTheDocument()
    expect(
      screen.getByText('Nothing scored well even after retrying — deciding whether this is a catalog gap.')
    ).toBeInTheDocument()
  })
})
