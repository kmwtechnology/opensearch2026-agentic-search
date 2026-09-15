/**
 * ChatPanel - Main chat interface container.
 * Displays message history and input form.
 */

import { useCallback } from 'react'
import { MessageList } from './MessageList'
import { MessageInput } from './MessageInput'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useChatStore } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { StopCircle } from 'lucide-react'
import clsx from 'clsx'

export function ChatPanel() {
  const { isProcessing } = useChatStore()
  const { isExecuting } = useObservabilityStore()
  const { stopExecution } = useWebSocket()

  const handleStop = useCallback(() => {
    stopExecution()
  }, [stopExecution])


  return (
    <div className="flex h-full w-full flex-col bg-[var(--color-stage-surface)]">
      {/* Header */}
      <div className="flex items-center justify-between border-b-2 border-[var(--color-stage-border-soft)] px-7 py-5">
        <div className="flex items-center gap-2">
          <h1 className="text-[length:var(--text-stage-body)] font-semibold text-[var(--color-stage-ink)]">Chat</h1>
          {(isProcessing || isExecuting) && (
            <span
              className="node-badge node-badge-running"
              aria-live="polite"
              aria-label="Processing response"
            >
              <span className="w-2 h-2 bg-blue-400 rounded-full animate-pulse mr-1.5" aria-hidden="true" />
              Processing
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            onClick={handleStop}
            disabled={!isProcessing && !isExecuting}
            className={clsx(
              'flex items-center gap-1 rounded-lg px-3 py-2 text-[1.25rem] font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-white',
              isProcessing || isExecuting
                ? 'bg-red-600 text-white hover:bg-red-700 focus:ring-red-500'
                : 'bg-[var(--color-stage-raised)] text-[var(--color-stage-ink-soft)] cursor-not-allowed focus:ring-blue-500'
            )}
          >
            <StopCircle className="w-4 h-4" aria-hidden="true" />
            Stop
          </button>
        </div>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-hidden">
        <MessageList />
      </div>

      {/* Input */}
      <div className="border-t border-[var(--color-stage-border)]">
        <MessageInput />
      </div>
    </div>
  )
}
