import { describe, it, expect, beforeEach } from 'vitest'
import { useChatStore, type ChatMessage, type QueuedMessage } from '../chatStore'

const makeMessage = (overrides: Partial<ChatMessage> = {}): ChatMessage => ({
  id: 'msg-1',
  role: 'user',
  content: 'hello',
  timestamp: new Date('2026-01-01'),
  ...overrides,
})

const makeQueued = (overrides: Partial<QueuedMessage> = {}): QueuedMessage => ({
  id: 'q-1',
  content: 'queued message',
  timestamp: new Date('2026-01-01'),
  ...overrides,
})

const INITIAL_STATE = {
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

beforeEach(() => {
  useChatStore.setState(INITIAL_STATE)
})

describe('chatStore', () => {
  describe('addMessage', () => {
    it('appends a message to the messages array', () => {
      const { addMessage } = useChatStore.getState()
      addMessage(makeMessage())
      expect(useChatStore.getState().messages).toHaveLength(1)
    })

    it('appends multiple messages in order', () => {
      const { addMessage } = useChatStore.getState()
      addMessage(makeMessage({ id: '1', content: 'first' }))
      addMessage(makeMessage({ id: '2', content: 'second' }))
      const { messages } = useChatStore.getState()
      expect(messages).toHaveLength(2)
      expect(messages[0].content).toBe('first')
      expect(messages[1].content).toBe('second')
    })
  })

  describe('clearMessages', () => {
    it('resets messages to empty array', () => {
      const { addMessage, clearMessages } = useChatStore.getState()
      addMessage(makeMessage())
      clearMessages()
      expect(useChatStore.getState().messages).toHaveLength(0)
    })

    it('also clears streamingContent and queuedMessages', () => {
      useChatStore.setState({ streamingContent: 'partial', queuedMessages: [makeQueued()] })
      useChatStore.getState().clearMessages()
      const state = useChatStore.getState()
      expect(state.streamingContent).toBe('')
      expect(state.queuedMessages).toHaveLength(0)
    })
  })

  describe('setIsProcessing', () => {
    it('sets isProcessing to true', () => {
      useChatStore.getState().setIsProcessing(true)
      expect(useChatStore.getState().isProcessing).toBe(true)
    })

    it('sets isProcessing to false', () => {
      useChatStore.setState({ isProcessing: true })
      useChatStore.getState().setIsProcessing(false)
      expect(useChatStore.getState().isProcessing).toBe(false)
    })
  })

  describe('appendStreamingContent', () => {
    it('concatenates chunks in order', () => {
      const { appendStreamingContent } = useChatStore.getState()
      appendStreamingContent('Hello ')
      appendStreamingContent('world')
      expect(useChatStore.getState().streamingContent).toBe('Hello world')
    })

    it('starts from empty string', () => {
      useChatStore.getState().appendStreamingContent('chunk')
      expect(useChatStore.getState().streamingContent).toBe('chunk')
    })
  })

  describe('finalizeStreaming', () => {
    it('moves streamingContent into last assistant message and clears it', () => {
      const assistantMsg = makeMessage({ id: 'a1', role: 'assistant', content: '', isStreaming: true })
      useChatStore.setState({ messages: [assistantMsg], streamingContent: 'streamed text' })
      useChatStore.getState().finalizeStreaming()
      const state = useChatStore.getState()
      expect(state.messages[0].content).toBe('streamed text')
      expect(state.messages[0].isStreaming).toBe(false)
      expect(state.streamingContent).toBe('')
    })

    it('clears streamingContent even when last message is not a streaming assistant', () => {
      const userMsg = makeMessage({ id: 'u1', role: 'user', content: 'hi' })
      useChatStore.setState({ messages: [userMsg], streamingContent: 'orphan' })
      useChatStore.getState().finalizeStreaming()
      expect(useChatStore.getState().streamingContent).toBe('')
    })

    it('sets isProcessing to false when streamingContent is empty', () => {
      useChatStore.setState({ streamingContent: '', isProcessing: true })
      useChatStore.getState().finalizeStreaming()
      expect(useChatStore.getState().isProcessing).toBe(false)
    })
  })

  describe('setConnectionState', () => {
    it('sets all three connection fields', () => {
      useChatStore.getState().setConnectionState(true, false, null)
      const state = useChatStore.getState()
      expect(state.isConnected).toBe(true)
      expect(state.isConnecting).toBe(false)
      expect(state.connectionError).toBeNull()
    })

    it('sets connectionError when provided', () => {
      useChatStore.getState().setConnectionState(false, false, 'timeout')
      expect(useChatStore.getState().connectionError).toBe('timeout')
    })
  })

  describe('triggerInputFocus', () => {
    it('increments inputFocusTrigger on each call', () => {
      useChatStore.getState().triggerInputFocus()
      useChatStore.getState().triggerInputFocus()
      expect(useChatStore.getState().inputFocusTrigger).toBe(2)
    })

    it('starts at 0', () => {
      expect(useChatStore.getState().inputFocusTrigger).toBe(0)
    })
  })

  describe('enqueueMessage / dequeueMessage', () => {
    it('enqueue adds a message and dequeue returns it', () => {
      const msg = makeQueued()
      useChatStore.getState().enqueueMessage(msg)
      const result = useChatStore.getState().dequeueMessage()
      expect(result).toEqual(msg)
    })

    it('dequeue removes message from the queue', () => {
      useChatStore.getState().enqueueMessage(makeQueued())
      useChatStore.getState().dequeueMessage()
      expect(useChatStore.getState().queuedMessages).toHaveLength(0)
    })

    it('dequeue returns null when queue is empty', () => {
      const result = useChatStore.getState().dequeueMessage()
      expect(result).toBeNull()
    })

    it('dequeues messages in FIFO order', () => {
      useChatStore.getState().enqueueMessage(makeQueued({ id: 'first', content: 'one' }))
      useChatStore.getState().enqueueMessage(makeQueued({ id: 'second', content: 'two' }))
      const first = useChatStore.getState().dequeueMessage()
      const second = useChatStore.getState().dequeueMessage()
      expect(first?.content).toBe('one')
      expect(second?.content).toBe('two')
    })
  })

  describe('updateLastMessage', () => {
    it('updates content of the last message', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'm1', content: 'original' }))
      useChatStore.getState().updateLastMessage('updated')
      expect(useChatStore.getState().messages[0].content).toBe('updated')
    })

    it('sets isStreaming to false on updated message', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'm1', isStreaming: true }))
      useChatStore.getState().updateLastMessage('done')
      expect(useChatStore.getState().messages[0].isStreaming).toBe(false)
    })

    it('does nothing when messages array is empty', () => {
      expect(() => useChatStore.getState().updateLastMessage('anything')).not.toThrow()
      expect(useChatStore.getState().messages).toHaveLength(0)
    })
  })

  describe('correctLastAssistantMessage', () => {
    it('replaces content of the last assistant message with corrected version', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'a1', role: 'assistant', content: 'original answer' }))
      useChatStore.getState().correctLastAssistantMessage('corrected answer', 0.65, 0.92)
      const { messages } = useChatStore.getState()
      expect(messages[0].content).toBe('corrected answer')
    })

    it('saves original content before replacing', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'a1', role: 'assistant', content: 'original answer' }))
      useChatStore.getState().correctLastAssistantMessage('corrected answer', 0.65, 0.92)
      const { messages } = useChatStore.getState()
      expect(messages[0].originalContent).toBe('original answer')
    })

    it('sets corrected flag and faithfulness scores', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'a1', role: 'assistant', content: 'original' }))
      useChatStore.getState().correctLastAssistantMessage('fixed', 0.7, 0.95)
      const msg = useChatStore.getState().messages[0]
      expect(msg.corrected).toBe(true)
      expect(msg.originalFaithfulness).toBeCloseTo(0.7)
      expect(msg.correctedFaithfulness).toBeCloseTo(0.95)
    })

    it('does not touch the last user message', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'u1', role: 'user', content: 'user query' }))
      useChatStore.getState().correctLastAssistantMessage('corrected', 0.5, 0.9)
      const { messages } = useChatStore.getState()
      expect(messages[0].content).toBe('user query')
      expect(messages[0].corrected).toBeUndefined()
    })

    it('does nothing when messages array is empty', () => {
      expect(() =>
        useChatStore.getState().correctLastAssistantMessage('x', 0.5, 0.9)
      ).not.toThrow()
      expect(useChatStore.getState().messages).toHaveLength(0)
    })

    it('only corrects the last message when multiple messages exist', () => {
      useChatStore.getState().addMessage(makeMessage({ id: 'a1', role: 'assistant', content: 'first answer' }))
      useChatStore.getState().addMessage(makeMessage({ id: 'u1', role: 'user', content: 'follow-up' }))
      useChatStore.getState().addMessage(makeMessage({ id: 'a2', role: 'assistant', content: 'second answer' }))
      useChatStore.getState().correctLastAssistantMessage('corrected second', 0.6, 0.9)
      const { messages } = useChatStore.getState()
      expect(messages[0].content).toBe('first answer')
      expect(messages[0].corrected).toBeUndefined()
      expect(messages[2].content).toBe('corrected second')
      expect(messages[2].corrected).toBe(true)
    })
  })
})
