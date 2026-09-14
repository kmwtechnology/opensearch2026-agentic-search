/**
 * MessageList - Displays chat messages with auto-scroll.
 */

import { useEffect, useRef, useMemo } from 'react'
import { useChatStore } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { Message } from './Message'

export function MessageList() {
  const { messages, streamingContent, isProcessing } = useChatStore()
  const { currentNode, steps } = useObservabilityStore()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const scrollTimeoutRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  // Map node IDs to user-friendly display names
  const getNodeDisplayName = (node: string): string => {
    const names: Record<string, string> = {
      query_evaluator: 'Evaluating query',
      retriever: 'Searching documents',
      agent: 'Generating response',
    }
    return names[node] || 'Processing'
  }

  // Get a brief summary of the current step
  const getCurrentStepSummary = (): string | null => {
    if (!currentNode || !steps.length) return null
    const currentStep = steps.find(s => s.node === currentNode)
    if (!currentStep || !currentStep.events.length) return null

    // Get the most recent event for this step
    const latestEvent = currentStep.events[currentStep.events.length - 1]

    // Extract summary based on event type
    if (latestEvent.type === 'hybrid_search_result') {
      return `Found ${latestEvent.candidate_count} candidates`
    }

    return null
  }

  // Auto-scroll to bottom on new messages (throttled to ~60fps with requestAnimationFrame)
  useEffect(() => {
    // Cancel any pending scroll request
    if (scrollTimeoutRef.current) {
      cancelAnimationFrame(scrollTimeoutRef.current)
    }

    // Schedule scroll on next animation frame (throttles to ~60fps)
    scrollTimeoutRef.current = requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    })

    // Cleanup on unmount or when dependencies change
    return () => {
      if (scrollTimeoutRef.current) {
        cancelAnimationFrame(scrollTimeoutRef.current)
      }
    }
  }, [messages, streamingContent])

  // Show streaming content in the last message if it's an assistant message (memoized)
  const displayMessages = useMemo(() => {
    return messages.map((msg, index) => {
      if (
        index === messages.length - 1 &&
        msg.role === 'assistant' &&
        msg.isStreaming &&
        streamingContent
      ) {
        return { ...msg, content: streamingContent }
      }
      return msg
    })
  }, [messages, streamingContent])

  if (messages.length === 0) {
    // Deliberately almost empty (#103). This used to be a feature tour —
    // a product blurb, four intent categories and eight sample queries. On a
    // projected demo that is a wall of 16px text the audience reads instead
    // of listening, and every word of it is either said out loud by the
    // presenter or already shown in the demo header.
    return (
      <div className="flex h-full items-center justify-center px-6">
        <p className="text-center text-[length:var(--text-stage-body)] font-medium text-[var(--color-stage-ink-soft)]">
          Ask a question to begin.
        </p>
      </div>
    )
  }

  return (
    <div className="h-full overflow-y-auto px-4 py-4 space-y-4" role="log" aria-live="polite" aria-label="Chat messages">
      {displayMessages.map((message) => (
        <Message key={message.id} message={message} />
      ))}

      {/* Show typing indicator when processing but no streaming content yet */}
      {isProcessing && !streamingContent && messages[messages.length - 1]?.role !== 'assistant' && (
        <div className="flex items-center gap-2 text-[var(--color-stage-ink-soft)]" aria-live="polite" aria-label="Agent processing">
          <div className="flex gap-1">
            <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" aria-hidden="true" />
          </div>
          <div className="text-[1.375rem]">
            {currentNode ? (
              <span className="flex items-center gap-2">
                <span className="font-medium text-blue-400">
                  {getNodeDisplayName(currentNode)}
                </span>
                {getCurrentStepSummary() && (
                  <span className="text-[var(--color-stage-ink-soft)]">• {getCurrentStepSummary()}</span>
                )}
              </span>
            ) : (
              <span>Agent is thinking...</span>
            )}
          </div>
        </div>
      )}

      <div ref={messagesEndRef} />
    </div>
  )
}
