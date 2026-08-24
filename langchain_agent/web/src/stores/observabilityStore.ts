/**
 * Zustand store for observability state management.
 * Tracks agent execution steps and events.
 */

import { create } from 'zustand'
import type {
  AgentEvent,
  NodeName,
  NodeStatus,
  ObservabilityStep,
  PipelineSummaryEvent,
  QueryEvaluationEvent,
  DocumentGradingSummaryEvent,
  ResponseGradingEvent,
  SearchCandidate,
  RerankedDocument,
  ConversationContextEvent,
  IntentClassificationEvent,
  QueryExpansionEvent,
  QualityGateEvent,
} from '../types/events'

// Snapshot of a historical conversation's last observability state, hydrated
// from the backend's GET /api/conversations/{thread_id}/observability endpoint.
// Mirrors api/routes/conversations.py::ObservabilitySnapshot.
export interface ObservabilitySnapshot {
  thread_id: string
  has_data: boolean
  user_query: string | null
  intent: string | null
  intent_confidence: number | null
  reasoning: string | null
  alpha: number | null
  query_analysis: string | null
  reranker_max_score: number | null
  quality_gate_retried: boolean | null
  quality_gate_reason: string | null
  latency: Record<string, number>
}

interface ObservabilityState {
  // Current execution state
  isExecuting: boolean
  currentNode: NodeName | null
  steps: ObservabilityStep[]

  // Conversation context
  conversationContext: ConversationContextEvent | null

  // Key event data for display
  queryEvaluation: QueryEvaluationEvent | null
  intentClassification: IntentClassificationEvent | null
  queryExpansion: QueryExpansionEvent | null
  qualityGate: QualityGateEvent | null
  searchCandidates: SearchCandidate[]
  rerankedDocuments: RerankedDocument[]
  documentGradingSummary: DocumentGradingSummaryEvent | null
  responseGrading: ResponseGradingEvent | null
  pipelineSummary: PipelineSummaryEvent | null

  // Historical snapshot — populated when user clicks a past conversation
  // and we hydrate from a checkpoint instead of a live stream.
  historicalSnapshot: ObservabilitySnapshot | null

  // Search status for interim messages ('idle' | 'running' | 'done')
  searchStatus: 'idle' | 'running' | 'done'
  rerankerStatus: 'idle' | 'running' | 'done'

  // Progress messages for real-time display
  searchProgressMessage: string | null
  rerankerProgressMessage: string | null
  rerankerProgress: number

  // UI state
  expandedSteps: Set<string>
  expandedEvents: Set<string>

  // Actions
  startExecution: () => void
  endExecution: () => void
  addEvent: (event: AgentEvent) => void
  startNode: (node: NodeName, summary?: string) => void
  endNode: (node: NodeName, durationMs: number, summary?: string) => void
  toggleStepExpanded: (stepId: string) => void
  toggleEventExpanded: (eventId: string) => void
  clearState: () => void
  hydrateSnapshot: (snapshot: ObservabilitySnapshot | null) => void
}

export const useObservabilityStore = create<ObservabilityState>((set, get) => ({
  // Initial state
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
  searchStatus: 'idle',
  rerankerStatus: 'idle',
  searchProgressMessage: null,
  rerankerProgressMessage: null,
  rerankerProgress: 0,
  expandedSteps: new Set(),
  expandedEvents: new Set(),

  // Actions
  startExecution: () => set({
    isExecuting: true,
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
    historicalSnapshot: null,
    searchStatus: 'idle',
    rerankerStatus: 'idle',
    searchProgressMessage: null,
    rerankerProgressMessage: null,
    rerankerProgress: 0,
  }),

  endExecution: () => set({
    isExecuting: false,
    currentNode: null,
    searchProgressMessage: null,
    rerankerProgressMessage: null,
  }),

  addEvent: (event) => {
    const state = get()

    // Update specific event data based on type
    switch (event.type) {
      case 'conversation_context':
        set({ conversationContext: event as ConversationContextEvent })
        break

      case 'query_evaluation':
        set({ queryEvaluation: event as QueryEvaluationEvent })
        break

      case 'intent_classification':
        set({ intentClassification: event as IntentClassificationEvent })
        break

      case 'query_expansion':
        set({ queryExpansion: event as QueryExpansionEvent })
        break

      case 'quality_gate':
        set({ qualityGate: event as QualityGateEvent })
        break

      case 'hybrid_search_start':
        set({ searchStatus: 'running', rerankerStatus: 'idle' })
        break

      case 'hybrid_search_result':
        set({
          searchStatus: 'done',
          searchCandidates: (event as { candidates: SearchCandidate[] }).candidates,
          rerankerStatus: 'idle',
        })
        break

      case 'reranker_start':
        set({ rerankerStatus: 'running' })
        break

      case 'reranker_result':
        set({
          rerankerStatus: 'done',
          rerankedDocuments: (event as { results: RerankedDocument[] }).results,
        })
        break

      case 'document_grading_summary':
        set({ documentGradingSummary: event as DocumentGradingSummaryEvent })
        break

      case 'response_grading':
        set({ responseGrading: event as ResponseGradingEvent })
        break

      case 'pipeline_summary':
        set({ pipelineSummary: event as PipelineSummaryEvent })
        break

      case 'search_progress':
        set({ searchProgressMessage: (event as { message: string }).message })
        break

      case 'reranker_progress':
        set({
          rerankerProgressMessage: (event as { message: string }).message,
          rerankerProgress: (event as { progress: number }).progress,
        })
        break

    }

    // Add event to its specified node's step, or current step if no node specified
    if (state.steps.length > 0) {
      set((s) => {
        const steps = [...s.steps]

        // Determine which step to add the event to
        // First check if the event has a node attribute and a running step for that node exists
        let targetStepIndex = -1
        if (event.node) {
          targetStepIndex = steps.findIndex(
            (step) => step.node === event.node && step.status === 'running'
          )
        }

        // If no running step for the event's node, use the current node
        if (targetStepIndex < 0 && s.currentNode) {
          targetStepIndex = steps.findIndex(
            (step) => step.node === s.currentNode && step.status === 'running'
          )
        }

        if (targetStepIndex >= 0) {
          steps[targetStepIndex] = {
            ...steps[targetStepIndex],
            events: [...steps[targetStepIndex].events, event],
          }
        }
        return { steps }
      })
    }
  },

  startNode: (node, summary) => {
    const stepId = `${node}-${Date.now()}`

    set((state) => ({
      currentNode: node,
      steps: [
        ...state.steps,
        {
          id: stepId,
          node,
          status: 'running' as NodeStatus,
          startTime: new Date(),
          events: [],
          summary,
        },
      ],
      expandedSteps: new Set([...state.expandedSteps, stepId]),
    }))
  },

  endNode: (node, durationMs, summary) => {
    set((state) => {
      const steps = [...state.steps]
      const stepIndex = steps.findIndex(
        (step) => step.node === node && step.status === 'running'
      )

      if (stepIndex >= 0) {
        steps[stepIndex] = {
          ...steps[stepIndex],
          status: 'complete',
          endTime: new Date(),
          durationMs,
          summary: summary || steps[stepIndex].summary,
        }
      }

      return {
        steps,
        currentNode: null,
      }
    })
  },

  toggleStepExpanded: (stepId) => set((state) => {
    const expandedSteps = new Set(state.expandedSteps)
    if (expandedSteps.has(stepId)) {
      expandedSteps.delete(stepId)
    } else {
      expandedSteps.add(stepId)
    }
    return { expandedSteps }
  }),

  toggleEventExpanded: (eventId) => set((state) => {
    const expandedEvents = new Set(state.expandedEvents)
    if (expandedEvents.has(eventId)) {
      expandedEvents.delete(eventId)
    } else {
      expandedEvents.add(eventId)
    }
    return { expandedEvents }
  }),

  clearState: () => set({
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
    searchStatus: 'idle',
    rerankerStatus: 'idle',
    expandedSteps: new Set(),
    expandedEvents: new Set(),
  }),

  hydrateSnapshot: (snapshot) => set({ historicalSnapshot: snapshot }),
}))
