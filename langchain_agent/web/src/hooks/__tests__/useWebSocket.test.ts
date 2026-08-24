import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useWebSocket } from '../useWebSocket'
import { useChatStore } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'

// ── Mock WebSocket ──────────────────────────────────────────────────────────

interface MockWs {
  send: ReturnType<typeof vi.fn>
  close: ReturnType<typeof vi.fn>
  readyState: number
  onopen: ((event: Event) => void) | null
  onmessage: ((event: MessageEvent) => void) | null
  onerror: ((event: Event) => void) | null
  onclose: ((event: CloseEvent) => void) | null
}

let mockWs: MockWs

// Stub window.location for the ws:// URL builder
Object.defineProperty(window, 'location', {
  value: { protocol: 'http:', host: 'localhost:3000' },
  writable: true,
})

const CHAT_INITIAL = {
  threadId: null,
  messages: [],
  isProcessing: false,
  streamingContent: '',
  queuedMessages: [],
  isConnected: false,
  isConnecting: false,
  connectionError: null,
  conversations: [],
  conversationsLoading: false,
  inputFocusTrigger: 0,
}

const OBS_INITIAL = {
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
  mockWs = {
    send: vi.fn(),
    close: vi.fn(),
    readyState: WebSocket.OPEN,
    onopen: null,
    onmessage: null,
    onerror: null,
    onclose: null,
  }

  // WebSocket must be a proper constructor
  class MockWebSocket {
    send = mockWs.send
    close = mockWs.close
    readyState = mockWs.readyState
    onopen: ((e: Event) => void) | null = null
    onmessage: ((e: MessageEvent) => void) | null = null
    onerror: ((e: Event) => void) | null = null
    onclose: ((e: CloseEvent) => void) | null = null
    constructor() {
      // Wire instance callbacks back to mockWs so tests can trigger them
      Object.defineProperties(mockWs, {
        onopen: {
          get: () => this.onopen,
          set: (v) => { this.onopen = v },
          configurable: true,
        },
        onmessage: {
          get: () => this.onmessage,
          set: (v) => { this.onmessage = v },
          configurable: true,
        },
        onerror: {
          get: () => this.onerror,
          set: (v) => { this.onerror = v },
          configurable: true,
        },
        onclose: {
          get: () => this.onclose,
          set: (v) => { this.onclose = v },
          configurable: true,
        },
      })
    }
  }
  // Merge static fields from native WebSocket
  ;(MockWebSocket as any).OPEN = WebSocket.OPEN

  vi.stubGlobal('WebSocket', MockWebSocket)

  // Reset module-level singleton by disconnecting — render a fresh hook and call disconnect
  const { result } = renderHook(() => useWebSocket())
  act(() => { result.current.disconnect() })

  // Reset stores
  act(() => {
    useChatStore.setState(CHAT_INITIAL)
    useObservabilityStore.setState(OBS_INITIAL)
  })
})

afterEach(() => {
  vi.unstubAllGlobals()
})

// Helper: render hook, connect, and fire onopen
function setupConnected() {
  const { result } = renderHook(() => useWebSocket())
  act(() => {
    result.current.connect('thread-1')
  })
  act(() => {
    mockWs.onopen?.(new Event('open'))
  })
  return result
}

// Helper: send a raw event object through mockWs.onmessage
function sendEvent(event: object) {
  act(() => {
    mockWs.onmessage?.({ data: JSON.stringify(event) } as MessageEvent)
  })
}

// ── Tests ────────────────────────────────────────────────────────────────────

describe('useWebSocket', () => {
  describe('connect', () => {
    it('sets isConnecting then isConnected after open', () => {
      const { result } = renderHook(() => useWebSocket())

      act(() => {
        result.current.connect('thread-1')
      })
      // After connect() but before onopen: isConnecting=true
      expect(useChatStore.getState().isConnecting).toBe(true)
      expect(useChatStore.getState().isConnected).toBe(false)

      act(() => {
        mockWs.onopen?.(new Event('open'))
      })
      expect(useChatStore.getState().isConnected).toBe(true)
      expect(useChatStore.getState().isConnecting).toBe(false)
    })
  })

  describe('llm_response_chunk', () => {
    it('appends content to streamingContent', () => {
      setupConnected()
      sendEvent({ type: 'llm_response_chunk', timestamp: 't', content: 'Hello', is_complete: false })
      expect(useChatStore.getState().streamingContent).toBe('Hello')
    })

    it('appends multiple chunks in order', () => {
      setupConnected()
      sendEvent({ type: 'llm_response_chunk', timestamp: 't', content: 'Hello', is_complete: false })
      sendEvent({ type: 'llm_response_chunk', timestamp: 't', content: ' world', is_complete: false })
      expect(useChatStore.getState().streamingContent).toBe('Hello world')
    })

    it('with is_complete finalizes streaming', () => {
      setupConnected()
      // Add a streaming assistant message first
      act(() => {
        useChatStore.getState().addMessage({
          id: 'a1', role: 'assistant', content: '', timestamp: new Date(), isStreaming: true,
        })
      })
      sendEvent({ type: 'llm_response_chunk', timestamp: 't', content: 'Done', is_complete: true })
      const state = useChatStore.getState()
      // streamingContent should be cleared after finalize
      expect(state.streamingContent).toBe('')
    })
  })

  describe('agent_complete', () => {
    it('finalizes streaming and ends execution', () => {
      setupConnected()
      act(() => {
        useObservabilityStore.setState({ isExecuting: true })
        useChatStore.getState().addMessage({
          id: 'a1', role: 'assistant', content: '', timestamp: new Date(), isStreaming: true,
        })
      })
      sendEvent({
        type: 'agent_complete',
        timestamp: 't',
        final_response: 'The answer.',
        citations: [],
        thread_id: 'thread-1',
        title: 'Test conversation',
      })
      expect(useChatStore.getState().streamingContent).toBe('')
      expect(useObservabilityStore.getState().isExecuting).toBe(false)
    })

    it('with citations sets citations on last message', () => {
      setupConnected()
      act(() => {
        useChatStore.getState().addMessage({
          id: 'a1', role: 'assistant', content: '', timestamp: new Date(), isStreaming: true,
        })
      })
      const citations = [{ url: 'https://example.com', title: 'Example', text: 'text' }]
      sendEvent({
        type: 'agent_complete',
        timestamp: 't',
        final_response: 'Answer',
        citations,
        thread_id: 'thread-1',
        title: 'Test',
      })
      const lastMsg = useChatStore.getState().messages.at(-1)
      expect(lastMsg?.citations).toEqual(citations)
    })
  })

  describe('agent_error', () => {
    it('sets connection error state', () => {
      setupConnected()
      sendEvent({ type: 'agent_error', timestamp: 't', error: 'Something went wrong' })
      const state = useChatStore.getState()
      expect(state.connectionError).toBe('Something went wrong')
      expect(state.isConnected).toBe(false)
    })
  })

  describe('node_start', () => {
    it('calls obsStore.startNode', () => {
      setupConnected()
      sendEvent({
        type: 'node_start',
        timestamp: 't',
        node: 'retriever',
        input_summary: 'hybrid search',
      })
      const { steps } = useObservabilityStore.getState()
      expect(steps).toHaveLength(1)
      expect(steps[0].node).toBe('retriever')
      expect(steps[0].status).toBe('running')
    })
  })

  describe('node_end', () => {
    it('calls obsStore.endNode with durationMs', () => {
      setupConnected()
      sendEvent({ type: 'node_start', timestamp: 't', node: 'retriever' })
      sendEvent({ type: 'node_end', timestamp: 't', node: 'retriever', duration_ms: 180 })
      const { steps } = useObservabilityStore.getState()
      expect(steps[0].status).toBe('complete')
      expect(steps[0].durationMs).toBe(180)
    })
  })
})
