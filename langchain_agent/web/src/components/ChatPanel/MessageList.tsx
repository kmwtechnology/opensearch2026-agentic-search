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
    if (latestEvent.type === 'document_grading_summary') {
      return `${latestEvent.relevant_count}/${latestEvent.total_count} relevant`
    }
    if (latestEvent.type === 'response_grading') {
      return `Score: ${(latestEvent.score * 100).toFixed(0)}%`
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
    return (
      <div className="flex flex-col items-center justify-center h-full text-gray-500 px-4">
        <div className="text-center max-w-lg">
          <h3 className="text-lg font-medium text-gray-300 mb-1">
            Product Search Agent
          </h3>
          <p className="text-xs text-gray-600 mb-4">
            An AI-powered e-commerce product search agent with hybrid search & reranking
          </p>

          <div className="text-left space-y-3">
            <div>
              <div className="text-xs font-medium text-gray-400 mb-1">
                Search — RAG-powered Q&A with hybrid search & reranking
              </div>
              <div className="text-xs text-gray-600 space-y-0.5">
                <div>"Find me wireless headphones under $50"</div>
                <div>"What are the best-rated running shoes?"</div>
              </div>
            </div>

            <div>
              <div className="text-xs font-medium text-amber-600/80 mb-1">
                Compare — find and compare products by attributes
              </div>
              <div className="text-xs text-gray-600 space-y-0.5">
                <div>"Compare Sony and Bose noise-canceling headphones"</div>
                <div>"Show me blue Nike sneakers"</div>
              </div>
            </div>

            <div>
              <div className="text-xs font-medium text-teal-600/80 mb-1">
                Discover — explore products by brand, color, or category
              </div>
              <div className="text-xs text-gray-600 space-y-0.5">
                <div>"What brands of laptops are available?"</div>
                <div>"Show me products from Samsung"</div>
              </div>
            </div>

            <div>
              <div className="text-xs font-medium text-purple-500/80 mb-1">
                Summarize — recap your conversation so far
              </div>
              <div className="text-xs text-gray-600">
                <div>"Summarize what we've discussed"</div>
              </div>
            </div>
          </div>

          <div className="mt-4 pt-3 border-t border-gray-800 text-xs text-gray-600 space-y-0.5">
            <div>Multi-turn memory · Smart citations with GitHub links · Real-time observability panel</div>
          </div>
        </div>
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
        <div className="flex items-center gap-2 text-gray-500" aria-live="polite" aria-label="Agent processing">
          <div className="flex gap-1">
            <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse" aria-hidden="true" />
          </div>
          <div className="text-sm">
            {currentNode ? (
              <span className="flex items-center gap-2">
                <span className="font-medium text-blue-400">
                  {getNodeDisplayName(currentNode)}
                </span>
                {getCurrentStepSummary() && (
                  <span className="text-gray-400">• {getCurrentStepSummary()}</span>
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
