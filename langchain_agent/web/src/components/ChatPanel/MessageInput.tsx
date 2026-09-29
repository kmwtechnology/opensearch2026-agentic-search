/**
 * MessageInput - Chat input form with send button.
 */

import clsx from 'clsx'
import { Send } from 'lucide-react'
import { KeyboardEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useChatStore } from '../../stores/chatStore'

export function MessageInput() {
  const [message, setMessage] = useState('')
  const { sendMessage } = useWebSocket()
  const { isConnected, connectionError, inputFocusTrigger } = useChatStore()
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [textareaHeight, setTextareaHeight] = useState<number>(0)

  useEffect(() => {
    if (inputFocusTrigger > 0 && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [inputFocusTrigger])

  const handleSubmit = useCallback(() => {
    const trimmed = message.trim()
    if (!trimmed || !isConnected) return

    sendMessage(trimmed)
    setMessage('')
  }, [message, isConnected, sendMessage])

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit]
  )

  const canSend = message.trim().length > 0 && isConnected

  useLayoutEffect(() => {
    if (!textareaRef.current) return

    setTextareaHeight(textareaRef.current.offsetHeight)

    let observer: ResizeObserver | null = null
    if (typeof ResizeObserver !== 'undefined') {
      observer = new ResizeObserver((entries) => {
        for (const entry of entries) {
          const height =
            entry.borderBoxSize?.[0]?.blockSize ||
            entry.contentRect?.height ||
            textareaRef.current?.offsetHeight ||
            entry.target.scrollHeight
          if (height) {
            setTextareaHeight(height)
          }
        }
      })

      observer.observe(textareaRef.current)
    }

    return () => {
      observer?.disconnect()
    }
  }, [message])

  return (
    <div className="p-4">
      <div className="flex items-stretch gap-2">
        <div className="flex-1 relative" ref={containerRef}>
          <label htmlFor="message-input" className="sr-only">
            Chat message
          </label>
          <textarea
            id="message-input"
            ref={textareaRef}
            value={message}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder={
              isConnected
                ? 'Search products, compare, or ask...'
                : 'Connecting...'
            }
            disabled={!isConnected}
            rows={1}
            aria-label="Chat message"
            aria-invalid={!isConnected ? 'true' : 'false'}
            aria-describedby={!isConnected ? 'connection-status' : undefined}
            className={clsx(
              'w-full resize-none rounded-lg border bg-[var(--color-stage-raised)] px-4 py-3 text-[1.375rem]',
              'text-[var(--color-stage-ink)] placeholder-gray-400',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              isConnected ? 'border-[var(--color-stage-border)]' : 'border-[#92400E]'
            )}
            style={{
              minHeight: '44px',
              maxHeight: '200px',
            }}
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={!canSend}
          aria-label="Send message"
          aria-disabled={!canSend}
          className={clsx(
            'flex-shrink-0 self-stretch w-12 flex items-center justify-center rounded-lg transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-white',
            canSend
              ? 'bg-blue-600 hover:bg-blue-700 text-white'
              : 'bg-[var(--color-stage-raised)] text-[var(--color-stage-ink-soft)] cursor-not-allowed'
          )}
          style={textareaHeight ? { height: `${textareaHeight}px` } : undefined}
        >
          <Send className="w-5 h-5" />
        </button>
      </div>

      {!isConnected && (
        <div
          id="connection-status"
          className={clsx(
            'mt-2 text-[1.25rem] font-medium',
            connectionError ? 'text-[#991B1B]' : 'text-[#92400E]'
          )}
        >
          {connectionError ? (
            <div className="flex items-center gap-2">
              <span>⚠️ {connectionError}</span>
              <span className="text-[1.25rem] text-[var(--color-stage-ink-soft)]">(Check that the server is running)</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 bg-[#92400E] rounded-full animate-pulse" />
              Connecting to server...
            </div>
          )}
        </div>
      )}
    </div>
  )
}
