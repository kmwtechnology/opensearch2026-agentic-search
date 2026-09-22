/**
 * WebSocket hook for real-time communication with the agent API.
 * Handles connection, message sending, and event processing.
 */

import { useCallback, useRef } from 'react'
import { useChatStore, type ChatMessage } from '../stores/chatStore'
import { useObservabilityStore } from '../stores/observabilityStore'
import { useOptimizationsStore } from '../stores/optimizationsStore'
import type { AgentEvent, NodeName } from '../types/events'

// Singleton WebSocket instance
let wsInstance: WebSocket | null = null
let currentThreadId: string | null = null

interface UseWebSocketReturn {
  isConnected: boolean
  isConnecting: boolean
  error: string | null
  connect: (threadId: string) => void
  disconnect: (options?: { preserveThreadId?: boolean }) => void
  sendMessage: (message: string) => void
  stopExecution: () => void
}

export function useWebSocket(): UseWebSocketReturn {
  const { isConnected, isConnecting, connectionError, setConnectionState } = useChatStore()

  const threadIdRef = useRef<string | null>(null)

  const sendOverWebSocket = useCallback((message: string, options?: { messageId?: string }) => {
    if (!wsInstance || wsInstance.readyState !== WebSocket.OPEN) {
      setConnectionState(false, false, 'WebSocket not connected')
      return false
    }

    const chatStore = useChatStore.getState()
    const obsStore = useObservabilityStore.getState()

    if (options?.messageId) {
      chatStore.updateMessageStatus(options.messageId, undefined)
    } else {
      const userMessage: ChatMessage = {
        id: `msg-${Date.now()}`,
        role: 'user',
        content: message,
        timestamp: new Date(),
      }
      chatStore.addMessage(userMessage)
    }

    // Set processing state
    chatStore.setIsProcessing(true)

    // Clear previous observability state and start new execution
    obsStore.clearState()
    obsStore.startExecution()

    // Send message over WebSocket
    const optimizations = useOptimizationsStore.getState().optimizations
    const payload = {
      type: 'chat_message',
      message,
      thread_id: currentThreadId,
      optimizations,
    }

    wsInstance.send(JSON.stringify(payload))
    return true
  }, [setConnectionState])

  const sendNextQueuedMessage = useCallback(() => {
    const chatStore = useChatStore.getState()
    const next = chatStore.dequeueMessage()
    if (!next) return
    sendOverWebSocket(next.content, { messageId: next.id })
  }, [sendOverWebSocket])

  const handleMessage = useCallback((data: AgentEvent) => {
    const chatStore = useChatStore.getState()
    const obsStore = useObservabilityStore.getState()

    // Add event to observability store
    obsStore.addEvent(data)

    switch (data.type) {
      case 'connection_established': {
        console.log('WebSocket connected:', data)
        // Flush a query queued by startNewConversation(autoSend) — the
        // "re-run search with corrected taxonomy" button (#103). It has to
        // wait for THIS event rather than a timeout: sendOverWebSocket reads
        // the module-level currentThreadId that connect() sets, and bails on
        // a socket that is not OPEN, so firing early would either go out on
        // the old thread or vanish. A dropped query on stage is the exact
        // failure this indirection exists to prevent.
        const pending = chatStore.pendingAutoSend
        if (pending) {
          chatStore.clearPendingAutoSend()
          sendOverWebSocket(pending)
        }
        break
      }

      case 'node_start':
        obsStore.startNode(data.node as NodeName, data.input_summary)
        break

      case 'node_end':
        obsStore.endNode(data.node as NodeName, data.duration_ms, data.output_summary)
        break

      case 'llm_response_start':
        // Start streaming - add placeholder assistant message
        chatStore.addMessage({
          id: `msg-${Date.now()}`,
          role: 'assistant',
          content: '',
          timestamp: new Date(),
          isStreaming: true,
        })
        chatStore.setStreamingContent('')
        break

      case 'llm_response_chunk':
        if (data.content) {
          chatStore.appendStreamingContent(data.content)
        }
        // Deliberately NOT finalized here (#144). The last token arrives one
        // frame before `agent_complete` brings the citations, so finalizing
        // now would commit the answer without them — and the product cards
        // are keyed off the citations, so the audience would watch the list
        // render as plain bullets and then re-render as cards. `agent_complete`
        // commits both together; `agent_error` is the escape hatch.
        break

      case 'agent_complete': {
        // Commit the answer and its citations in one store write, so the
        // message renders exactly once — see completeTurn in chatStore (#144).
        chatStore.completeTurn(data.final_response, data.citations || [])
        chatStore.triggerInputFocus()
        obsStore.endExecution()

        // Update conversation list with the new/updated conversation
        if (data.thread_id && data.title) {
          chatStore.upsertConversation({
            thread_id: data.thread_id,
            title: data.title,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString(),
          })
        }
        sendNextQueuedMessage()
        break
      }

      case 'llm_response_corrected':
        chatStore.correctLastAssistantMessage(
          data.corrected_content,
          data.original_faithfulness,
          data.corrected_faithfulness,
        )
        break

      case 'agent_error':
        console.error('Agent error:', data.error)
        chatStore.setConnectionState(false, false, data.error)
        chatStore.finalizeStreaming()
        obsStore.endExecution()
        break

      default:
        // Other events are handled by addEvent above
        break
    }
  }, [sendNextQueuedMessage, sendOverWebSocket])

  const connect = useCallback(
    (threadId: string) => {
      // If already connected to this thread, do nothing
      if (wsInstance?.readyState === WebSocket.OPEN && currentThreadId === threadId) {
        console.log('Already connected to this thread, skipping')
        return
      }

      console.log('Starting new WebSocket connection for thread:', threadId)

      // Close existing connection if any
      if (wsInstance) {
        console.log('Closing previous WebSocket connection')
        wsInstance.close()
        wsInstance = null
      }

      // Set connecting state
      setConnectionState(false, true, null)
      threadIdRef.current = threadId
      currentThreadId = threadId

      // Build WebSocket URL using current window location
      // When frontend and API are on the same domain (Cloud Run), this uses the current origin
      // No API key needed - authentication is based on origin header
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const host = window.location.host

      const url = `${protocol}//${host}/ws/chat?thread_id=${threadId}`
      console.log('Connecting to WebSocket:', url)

      const ws = new WebSocket(url)

      ws.onopen = () => {
        console.log('WebSocket onopen event fired')
        setConnectionState(true, false, null)
        // Also update Zustand chat store to ensure state consistency
        useChatStore.getState().setConnectionState(true, false, null)
        console.log('WebSocket connected - state updated')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as AgentEvent
          handleMessage(data)
        } catch (e) {
          console.error('Failed to parse WebSocket message:', e)
        }
      }

      ws.onerror = (event) => {
        console.error('WebSocket error:', event)
        setConnectionState(false, false, 'WebSocket connection error')
      }

      ws.onclose = () => {
        // Only update state if this is still the current WebSocket instance
        // This prevents stale onclose handlers from overwriting state when switching conversations
        if (wsInstance === ws) {
          setConnectionState(false, false, null)
          wsInstance = null
        }
        console.log('WebSocket disconnected')
      }

      wsInstance = ws
    },
    [handleMessage, setConnectionState]
  )

  const disconnect = useCallback(
    (options?: { preserveThreadId?: boolean }) => {
      if (wsInstance) {
        wsInstance.close()
        wsInstance = null
      }
      if (options?.preserveThreadId) {
        currentThreadId = threadIdRef.current
      } else {
        threadIdRef.current = null
        currentThreadId = null
      }
      setConnectionState(false, false, null)
    },
    [setConnectionState]
  )

  const sendMessage = useCallback((message: string) => {
    if (!wsInstance || wsInstance.readyState !== WebSocket.OPEN) {
      setConnectionState(false, false, 'WebSocket not connected')
      return
    }

    const chatStore = useChatStore.getState()
    if (chatStore.isProcessing) {
      const timestamp = new Date()
      const queuedMessage: ChatMessage = {
        id: `msg-${Date.now()}`,
        role: 'user',
        content: message,
        timestamp,
        status: 'queued',
      }
      chatStore.addMessage(queuedMessage)
      chatStore.enqueueMessage({
        id: queuedMessage.id,
        content: message,
        timestamp,
      })
      return
    }

    sendOverWebSocket(message)
  }, [sendOverWebSocket, setConnectionState])

  const stopExecution = useCallback(() => {
    if (!wsInstance || wsInstance.readyState !== WebSocket.OPEN) {
      // If no connection, just clean up state
      useObservabilityStore.getState().endExecution()
      useChatStore.getState().finalizeStreaming()
      useChatStore.getState().setIsProcessing(false)
      return
    }

    // Send stop signal to backend
    try {
      wsInstance.send(JSON.stringify({
        type: 'stop_execution',
        thread_id: threadIdRef.current,
      }))
    } catch (e) {
      console.error('Failed to send stop signal:', e)
    }

    // Immediately clean up UI state
    useObservabilityStore.getState().endExecution()
    useChatStore.getState().finalizeStreaming()
    useChatStore.getState().setIsProcessing(false)
  }, [])

  return {
    isConnected,
    isConnecting,
    error: connectionError,
    connect,
    disconnect,
    sendMessage,
    stopExecution,
  }
}
