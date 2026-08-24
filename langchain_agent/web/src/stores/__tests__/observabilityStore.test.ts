import { describe, it, expect, beforeEach } from 'vitest'
import { useObservabilityStore } from '../observabilityStore'

const INITIAL_STATE = {
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
  searchStatus: 'idle' as const,
  rerankerStatus: 'idle' as const,
  searchProgressMessage: null,
  rerankerProgressMessage: null,
  rerankerProgress: 0,
  expandedSteps: new Set<string>(),
  expandedEvents: new Set<string>(),
}

beforeEach(() => {
  useObservabilityStore.setState({ ...INITIAL_STATE })
})

describe('observabilityStore', () => {
  describe('startExecution', () => {
    it('resets all state and sets isExecuting true', () => {
      // Pre-populate some state
      useObservabilityStore.setState({
        searchCandidates: [{ product_id: 'p1', title: 'X', score: 0.9 }] as any,
        queryEvaluation: { type: 'query_evaluation' } as any,
        steps: [{ id: 'x', node: 'retriever', status: 'complete', startTime: new Date(), events: [] }] as any,
      })
      useObservabilityStore.getState().startExecution()
      const state = useObservabilityStore.getState()
      expect(state.isExecuting).toBe(true)
      expect(state.steps).toHaveLength(0)
      expect(state.searchCandidates).toHaveLength(0)
      expect(state.queryEvaluation).toBeNull()
      expect(state.currentNode).toBeNull()
    })
  })

  describe('endExecution', () => {
    it('sets isExecuting false', () => {
      useObservabilityStore.setState({ isExecuting: true })
      useObservabilityStore.getState().endExecution()
      expect(useObservabilityStore.getState().isExecuting).toBe(false)
    })

    it('sets currentNode to null', () => {
      useObservabilityStore.setState({ isExecuting: true, currentNode: 'retriever' as any })
      useObservabilityStore.getState().endExecution()
      expect(useObservabilityStore.getState().currentNode).toBeNull()
    })
  })

  describe('startNode', () => {
    it('adds a running step', () => {
      useObservabilityStore.getState().startNode('retriever')
      const { steps } = useObservabilityStore.getState()
      expect(steps).toHaveLength(1)
      expect(steps[0].node).toBe('retriever')
      expect(steps[0].status).toBe('running')
    })

    it('auto-expands the new step', () => {
      useObservabilityStore.getState().startNode('retriever')
      const { steps, expandedSteps } = useObservabilityStore.getState()
      expect(expandedSteps.has(steps[0].id)).toBe(true)
    })

    it('stores summary on the step when provided', () => {
      useObservabilityStore.getState().startNode('reranker', 'Reranking 15 candidates')
      const { steps } = useObservabilityStore.getState()
      expect(steps[0].summary).toBe('Reranking 15 candidates')
    })
  })

  describe('endNode', () => {
    it('marks the matching step complete', () => {
      useObservabilityStore.getState().startNode('retriever')
      useObservabilityStore.getState().endNode('retriever', 120)
      const { steps } = useObservabilityStore.getState()
      expect(steps[0].status).toBe('complete')
    })

    it('sets durationMs on the step', () => {
      useObservabilityStore.getState().startNode('retriever')
      useObservabilityStore.getState().endNode('retriever', 250)
      const { steps } = useObservabilityStore.getState()
      expect(steps[0].durationMs).toBe(250)
    })

    it('sets currentNode to null after endNode', () => {
      useObservabilityStore.getState().startNode('retriever')
      useObservabilityStore.getState().endNode('retriever', 100)
      expect(useObservabilityStore.getState().currentNode).toBeNull()
    })
  })

  describe('addEvent', () => {
    it('query_evaluation updates queryEvaluation field', () => {
      const event = {
        type: 'query_evaluation' as const,
        timestamp: '2026-01-01T00:00:00Z',
        node: 'query_evaluator' as const,
        query: 'wireless headphones',
        alpha: 0.6,
        query_analysis: 'semantic query',
        search_strategy: 'semantic-heavy' as const,
      }
      useObservabilityStore.getState().addEvent(event)
      expect(useObservabilityStore.getState().queryEvaluation).toEqual(event)
    })

    it('intent_classification updates intentClassification field', () => {
      const event = {
        type: 'intent_classification' as const,
        timestamp: '2026-01-01T00:00:00Z',
        node: 'intent_classifier' as const,
        intent: 'search',
        user_query: 'headphones',
        reasoning: 'product discovery',
        confidence: 0.9,
      }
      useObservabilityStore.getState().addEvent(event)
      expect(useObservabilityStore.getState().intentClassification).toEqual(event)
    })

    it('hybrid_search_result sets searchStatus to done and updates candidates', () => {
      const candidates = [{ product_id: 'p1', title: 'Headphones', score: 0.95 }]
      const event = {
        type: 'hybrid_search_result' as const,
        timestamp: '2026-01-01T00:00:00Z',
        candidates,
      }
      useObservabilityStore.getState().addEvent(event as any)
      const state = useObservabilityStore.getState()
      expect(state.searchStatus).toBe('done')
      expect(state.searchCandidates).toEqual(candidates)
    })

    it('search_progress updates searchProgressMessage', () => {
      const event = {
        type: 'search_progress' as const,
        timestamp: '2026-01-01T00:00:00Z',
        message: 'Searching OpenSearch...',
      }
      useObservabilityStore.getState().addEvent(event as any)
      expect(useObservabilityStore.getState().searchProgressMessage).toBe('Searching OpenSearch...')
    })

    it('pipeline_summary updates pipelineSummary field', () => {
      const event = {
        type: 'pipeline_summary' as const,
        timestamp: '2026-01-01T00:00:00Z',
        node: 'agent' as const,
        has_judgments: false,
        stages: [],
      }
      useObservabilityStore.getState().addEvent(event as any)
      expect(useObservabilityStore.getState().pipelineSummary).toEqual(event)
    })

    it('appends to current running step events', () => {
      useObservabilityStore.getState().startNode('retriever')
      const event = {
        type: 'search_progress' as const,
        timestamp: '2026-01-01T00:00:00Z',
        node: 'retriever' as const,
        message: 'Fetching...',
      }
      useObservabilityStore.getState().addEvent(event as any)
      const { steps } = useObservabilityStore.getState()
      expect(steps[0].events).toHaveLength(1)
      expect(steps[0].events[0]).toEqual(event)
    })
  })

  describe('toggleStepExpanded', () => {
    it('adds stepId to expandedSteps when not present', () => {
      useObservabilityStore.getState().toggleStepExpanded('step-1')
      expect(useObservabilityStore.getState().expandedSteps.has('step-1')).toBe(true)
    })

    it('removes stepId from expandedSteps when already present', () => {
      useObservabilityStore.getState().toggleStepExpanded('step-1')
      useObservabilityStore.getState().toggleStepExpanded('step-1')
      expect(useObservabilityStore.getState().expandedSteps.has('step-1')).toBe(false)
    })
  })

  describe('toggleEventExpanded', () => {
    it('adds eventId to expandedEvents when not present', () => {
      useObservabilityStore.getState().toggleEventExpanded('event-1')
      expect(useObservabilityStore.getState().expandedEvents.has('event-1')).toBe(true)
    })

    it('removes eventId from expandedEvents when already present', () => {
      useObservabilityStore.getState().toggleEventExpanded('event-1')
      useObservabilityStore.getState().toggleEventExpanded('event-1')
      expect(useObservabilityStore.getState().expandedEvents.has('event-1')).toBe(false)
    })
  })

  describe('clearState', () => {
    it('resets steps to empty array', () => {
      useObservabilityStore.getState().startNode('retriever')
      useObservabilityStore.getState().clearState()
      expect(useObservabilityStore.getState().steps).toHaveLength(0)
    })

    it('resets expandedSteps to empty set', () => {
      useObservabilityStore.getState().toggleStepExpanded('step-1')
      useObservabilityStore.getState().clearState()
      expect(useObservabilityStore.getState().expandedSteps.size).toBe(0)
    })

    it('resets pipelineSummary to null', () => {
      useObservabilityStore.setState({ pipelineSummary: { type: 'pipeline_summary' } as any })
      useObservabilityStore.getState().clearState()
      expect(useObservabilityStore.getState().pipelineSummary).toBeNull()
    })

    it('resets historicalSnapshot to null', () => {
      useObservabilityStore.getState().hydrateSnapshot({
        thread_id: 'foo',
        has_data: true,
        user_query: 'q',
        intent: 'search',
        intent_confidence: 0.9,
        reasoning: 'r',
        alpha: 0.5,
        query_analysis: 'a',
        reranker_max_score: 0.8,
        quality_gate_retried: false,
        quality_gate_reason: 'PASS',
        latency: { reranker_latency_ms: 100 },
      })
      useObservabilityStore.getState().clearState()
      expect(useObservabilityStore.getState().historicalSnapshot).toBeNull()
    })
  })

  describe('hydrateSnapshot', () => {
    it('stores a snapshot object', () => {
      const snapshot = {
        thread_id: 'conv-1',
        has_data: true,
        user_query: 'find headphones',
        intent: 'search',
        intent_confidence: 0.92,
        reasoning: 'product search request',
        alpha: 0.6,
        query_analysis: 'looking for audio gear',
        reranker_max_score: 0.95,
        quality_gate_retried: false,
        quality_gate_reason: 'PASS',
        latency: { bm25_latency_ms: 30, reranker_latency_ms: 200 },
      }
      useObservabilityStore.getState().hydrateSnapshot(snapshot)
      expect(useObservabilityStore.getState().historicalSnapshot).toEqual(snapshot)
    })

    it('clears the snapshot when called with null', () => {
      useObservabilityStore.setState({
        historicalSnapshot: { thread_id: 'x', has_data: true } as any,
      })
      useObservabilityStore.getState().hydrateSnapshot(null)
      expect(useObservabilityStore.getState().historicalSnapshot).toBeNull()
    })
  })
})
