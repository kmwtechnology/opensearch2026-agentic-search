/**
 * Tests for the MessageList pre-token status card label — specifically that
 * "Checking whether a tool is needed" only appears when a tool-offer/
 * correction check is actually eligible to run this turn, not on every
 * agent-node turn before the first token (#106).
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
    expect(screen.queryByText('Checking whether a tool is needed')).not.toBeInTheDocument()
    expect(screen.getByText('Thinking through the answer')).toBeInTheDocument()
  })

  it('shows the tool-check label on a follow_up turn (correction gate eligible)', () => {
    useObservabilityStore.setState({
      intentClassification: {
        type: 'intent_classification',
        node: 'intent_classifier',
        timestamp: new Date().toISOString(),
        intent: 'follow_up',
        user_query: 'no, those are brown not tan',
        reasoning: 'dispute language',
      },
    })
    render(<MessageList />)
    expect(screen.getByText('Checking whether a tool is needed')).toBeInTheDocument()
  })

  it('shows the tool-check label on an attribute_filter turn with zero candidates (enrichment gap gate)', () => {
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
    })
    render(<MessageList />)
    expect(screen.getByText('Checking whether a tool is needed')).toBeInTheDocument()
  })

  it('shows the tool-check label when the quality gate retried and still scored below the relevance floor', () => {
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
    expect(screen.getByText('Checking whether a tool is needed')).toBeInTheDocument()
  })
})
