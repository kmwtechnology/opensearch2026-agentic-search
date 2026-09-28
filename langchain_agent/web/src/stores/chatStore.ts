/**
 * Zustand store for chat state management.
 * Handles messages, streaming state, and the message queue.
 */

import { create } from 'zustand'
import { newThreadId } from '../utils/threadId'

// Message and citation types for chat display
export interface Citation {
  label: string
  url: string
  /** Amazon ASIN, present for ESCI products. */
  asin?: string
  /** Product photo URL (SQID, #147); absent when Amazon has none. */
  image_url?: string
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  timestamp: Date
  isStreaming?: boolean
  status?: 'queued'
  citations?: Citation[]
  corrected?: boolean
  originalContent?: string
  originalFaithfulness?: number
  correctedFaithfulness?: number
}

export interface QueuedMessage {
  id: string
  content: string
  timestamp: Date
}

interface ChatState {
  // Current conversation
  threadId: string | null
  messages: ChatMessage[]
  isProcessing: boolean
  streamingContent: string
  queuedMessages: QueuedMessage[]
  // A query to fire as soon as the NEXT thread's socket is established.
  // See startNewConversation() for why it cannot simply be sent inline.
  pendingAutoSend: string | null

  // WebSocket state
  isConnected: boolean
  isConnecting: boolean
  connectionError: string | null

  // Focus trigger - increments when input should be focused
  inputFocusTrigger: number

  // Actions
  setThreadId: (threadId: string) => void
  addMessage: (message: ChatMessage) => void
  updateMessageStatus: (id: string, status?: 'queued') => void
  completeTurn: (finalResponse: string | undefined, citations: Citation[]) => void
  correctLastAssistantMessage: (correctedContent: string, originalFaithfulness: number, correctedFaithfulness: number) => void
  setIsProcessing: (isProcessing: boolean) => void
  setStreamingContent: (content: string) => void
  appendStreamingContent: (chunk: string) => void
  finalizeStreaming: () => void
  startNewConversation: (autoSend?: string) => void
  clearPendingAutoSend: () => void
  setConnectionState: (connected: boolean, connecting: boolean, error: string | null) => void
  triggerInputFocus: () => void
  enqueueMessage: (message: QueuedMessage) => void
  dequeueMessage: () => QueuedMessage | null
}

export const useChatStore = create<ChatState>((set, get) => ({
  // Initial state
  threadId: null,
  messages: [],
  isProcessing: false,
  streamingContent: '',
  queuedMessages: [],
  pendingAutoSend: null,
  isConnected: false,
  isConnecting: false,
  connectionError: null,
  inputFocusTrigger: 0,

  // Actions
  setThreadId: (threadId) => set({ threadId }),

  addMessage: (message) => set((state) => ({
    messages: [...state.messages, message]
  })),

  updateMessageStatus: (id, status) => set((state) => ({
    messages: state.messages.map((message) => (
      message.id === id
        ? {
          ...message,
          status,
        }
        : message
    )),
  })),

  /**
   * Land the finished answer and its citations in a SINGLE update (#144).
   *
   * These used to arrive as two store writes on two different WebSocket
   * frames — `llm_response_chunk(is_complete)` finalized the text, then
   * `agent_complete` attached the citations. That is two render batches, and
   * since the product cards are keyed off the citations the answer visibly
   * rendered twice: once as a plain bullet list, then again as cards. One
   * `set` makes it one render, no reflow.
   */
  completeTurn: (finalResponse, citations) => set((state) => {
    const messages = [...state.messages]
    const lastIndex = messages.length - 1
    const last = messages[lastIndex]
    // Prefer the authoritative final response; fall back to what streamed.
    const content = finalResponse || state.streamingContent

    if (last && last.role === 'assistant' && last.isStreaming) {
      messages[lastIndex] = {
        ...last,
        content: content || last.content,
        isStreaming: false,
        citations,
      }
    } else if (content) {
      // No placeholder to fill — keep the answer rather than dropping it.
      messages.push({
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content,
        timestamp: new Date(),
        citations,
      })
    }

    return { messages, streamingContent: '', isProcessing: false }
  }),

  correctLastAssistantMessage: (correctedContent, originalFaithfulness, correctedFaithfulness) => set((state) => {
    const messages = [...state.messages]
    const lastIndex = messages.length - 1
    if (lastIndex >= 0 && messages[lastIndex].role === 'assistant') {
      messages[lastIndex] = {
        ...messages[lastIndex],
        originalContent: messages[lastIndex].content,
        content: correctedContent,
        corrected: true,
        originalFaithfulness,
        correctedFaithfulness,
      }
    }
    return { messages }
  }),

  setIsProcessing: (isProcessing) => set({ isProcessing }),

  setStreamingContent: (content) => set({ streamingContent: content }),

  appendStreamingContent: (chunk) => set((state) => ({
    streamingContent: state.streamingContent + chunk
  })),

  finalizeStreaming: () => {
    const { streamingContent, messages } = get()
    if (streamingContent) {
      const lastMessage = messages[messages.length - 1]
      if (lastMessage && lastMessage.role === 'assistant' && lastMessage.isStreaming) {
        set((state) => {
          const updatedMessages = [...state.messages]
          const lastIndex = updatedMessages.length - 1
          updatedMessages[lastIndex] = {
            ...updatedMessages[lastIndex],
            content: streamingContent,
            isStreaming: false,
          }
          return {
            messages: updatedMessages,
            streamingContent: '',
            isProcessing: false,
          }
        })
      } else {
        set({
          streamingContent: '',
          isProcessing: false,
        })
      }
    } else {
      set({ isProcessing: false })
    }
  },

  startNewConversation: (autoSend?: string) => {
    set({
      threadId: newThreadId(),
      messages: [],
      streamingContent: '',
      isProcessing: false,
      queuedMessages: [],
      // Sent by useWebSocket the moment the NEW thread's socket reports
      // connection_established (#103). It cannot be sent here: the socket for
      // the new thread does not exist yet, and sendOverWebSocket reads a
      // module-level currentThreadId set in connect() — so sending now would
      // either go out on the OLD thread or be dropped for a non-OPEN socket.
      pendingAutoSend: autoSend ?? null,
    })
  },

  clearPendingAutoSend: () => set({ pendingAutoSend: null }),

  setConnectionState: (connected, connecting, error) => set({
    isConnected: connected,
    isConnecting: connecting,
    connectionError: error,
  }),

  triggerInputFocus: () => set((state) => ({
    inputFocusTrigger: state.inputFocusTrigger + 1
  })),

  enqueueMessage: (message) => set((state) => ({
    queuedMessages: [...state.queuedMessages, message]
  })),

  dequeueMessage: () => {
    const { queuedMessages } = get()
    if (queuedMessages.length === 0) return null
    const [next, ...rest] = queuedMessages
    set({ queuedMessages: rest })
    return next
  },
}))
