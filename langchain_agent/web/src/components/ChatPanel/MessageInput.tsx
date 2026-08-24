/**
 * MessageInput - Chat input form with send button and typeahead combobox.
 */

import clsx from 'clsx'
import { Send } from 'lucide-react'
import { KeyboardEvent, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import { useRecentSearches } from '../../hooks/useRecentSearches'
import { useWebSocket } from '../../hooks/useWebSocket'
import { useChatStore } from '../../stores/chatStore'
import { TypeaheadSuggestions, type Suggestion } from './TypeaheadSuggestions'

const TYPEAHEAD_MIN_CHARS = 3
const LISTBOX_ID = 'typeahead-listbox'

export function MessageInput() {
  const [message, setMessage] = useState('')
  const [showTypeahead, setShowTypeahead] = useState(false)
  const [typeaheadIndex, setTypeaheadIndex] = useState(-1)
  const [rowCount, setRowCount] = useState(0)
  const { sendMessage } = useWebSocket()
  const { isConnected, connectionError, inputFocusTrigger } = useChatStore()
  const { add: addRecent, recent } = useRecentSearches()
  const textareaRef = useRef<HTMLTextAreaElement | null>(null)
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [textareaHeight, setTextareaHeight] = useState<number>(0)

  useEffect(() => {
    if (inputFocusTrigger > 0 && textareaRef.current) {
      textareaRef.current.focus()
    }
  }, [inputFocusTrigger])

  const submitQuery = useCallback(
    (query: string) => {
      const trimmed = query.trim()
      if (!trimmed || !isConnected) return

      setShowTypeahead(false)
      setTypeaheadIndex(-1)
      addRecent(trimmed)
      sendMessage(trimmed)
      setMessage('')
    },
    [isConnected, addRecent, sendMessage]
  )

  const handleSubmit = useCallback(() => submitQuery(message), [message, submitQuery])

  // Accepting any suggestion (product, spelling, or recent) runs the search
  // using the suggestion's title verbatim — the original typed query is
  // discarded. Replaces an earlier behavior that appended products onto the
  // typed text and required the user to press Enter again.
  const handleSuggestionSelect = useCallback(
    (suggestion: Suggestion) => {
      submitQuery(suggestion.title)
    },
    [submitQuery]
  )

  // Dropdown is eligible to open in two distinct cases:
  //   1. Typed input crosses TYPEAHEAD_MIN_CHARS — fires from onChange/onFocus
  //      so the user gets live suggestions while typing.
  //   2. Empty input + recent searches — only when the user explicitly
  //      clicks back into the textarea (handled by onClick below).
  // We deliberately don't open the recent-searches dropdown on programmatic
  // focus (e.g. the auto-focus that fires after a query completes) because
  // it surprises the user when they're scrolling other panels.
  const typeaheadEligibleOnType = useCallback(
    (value: string) => value.trim().length >= TYPEAHEAD_MIN_CHARS,
    []
  )
  const typeaheadEligibleOnClick = useCallback(
    (value: string) => {
      const trimmed = value.trim()
      if (trimmed.length >= TYPEAHEAD_MIN_CHARS) return true
      if (trimmed.length === 0 && recent.length > 0) return true
      return false
    },
    [recent.length]
  )

  const handleKeyDown = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (showTypeahead && rowCount > 0) {
        if (e.key === 'ArrowDown') {
          e.preventDefault()
          setTypeaheadIndex((i) => Math.min(rowCount - 1, i + 1))
          return
        }
        if (e.key === 'ArrowUp') {
          e.preventDefault()
          setTypeaheadIndex((i) => Math.max(-1, i - 1))
          return
        }
        if (e.key === 'Escape') {
          e.preventDefault()
          setShowTypeahead(false)
          setTypeaheadIndex(-1)
          return
        }
        if (e.key === 'Tab' && typeaheadIndex >= 0) {
          // Tab accepts highlighted suggestion without moving focus.
          e.preventDefault()
          // Selection is handled by clicking; emit a synthetic keyboard trigger
          // via document.getElementById to keep the logic in one place.
          const el = document.getElementById(`typeahead-option-${typeaheadIndex}`)
          ;(el as HTMLButtonElement | null)?.click()
          return
        }
        if (e.key === 'Enter' && !e.shiftKey && typeaheadIndex >= 0) {
          // Enter on a highlighted suggestion: accept, don't submit.
          e.preventDefault()
          const el = document.getElementById(`typeahead-option-${typeaheadIndex}`)
          ;(el as HTMLButtonElement | null)?.click()
          return
        }
      }

      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault()
        handleSubmit()
      }
    },
    [handleSubmit, rowCount, showTypeahead, typeaheadIndex]
  )

  const canSend = message.trim().length > 0 && isConnected
  const activeDescendant =
    showTypeahead && typeaheadIndex >= 0 ? `typeahead-option-${typeaheadIndex}` : undefined

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
            onChange={(e) => {
              setMessage(e.target.value)
              setShowTypeahead(typeaheadEligibleOnType(e.target.value))
              setTypeaheadIndex(-1)
            }}
            onKeyDown={handleKeyDown}
            onFocus={() => setShowTypeahead(typeaheadEligibleOnType(message))}
            onClick={() => setShowTypeahead(typeaheadEligibleOnClick(message))}
            onBlur={() => {
              // Delay closing to allow click selection (handled by onMouseDown preventDefault too).
              setTimeout(() => setShowTypeahead(false), 200)
            }}
            placeholder={
              isConnected
                ? 'Search products, compare, or ask...'
                : 'Connecting...'
            }
            disabled={!isConnected}
            rows={1}
            role="combobox"
            aria-expanded={showTypeahead}
            aria-controls={LISTBOX_ID}
            aria-autocomplete="list"
            aria-activedescendant={activeDescendant}
            aria-label="Chat message"
            aria-invalid={!isConnected ? 'true' : 'false'}
            aria-describedby={!isConnected ? 'connection-status' : undefined}
            className={clsx(
              'w-full resize-none rounded-lg border bg-gray-800 px-4 py-3 text-sm',
              'text-gray-100 placeholder-gray-400',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent',
              'disabled:opacity-50 disabled:cursor-not-allowed',
              isConnected ? 'border-gray-700' : 'border-yellow-600'
            )}
            style={{
              minHeight: '44px',
              maxHeight: '200px',
            }}
          />
          <TypeaheadSuggestions
            query={message}
            isOpen={showTypeahead && isConnected}
            selectedIndex={typeaheadIndex}
            listboxId={LISTBOX_ID}
            onSelect={handleSuggestionSelect}
            onRowCountChange={setRowCount}
          />
        </div>

        <button
          onClick={handleSubmit}
          disabled={!canSend}
          aria-label="Send message"
          aria-disabled={!canSend}
          className={clsx(
            'flex-shrink-0 self-stretch w-12 flex items-center justify-center rounded-lg transition-colors',
            'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-900',
            canSend
              ? 'bg-blue-600 hover:bg-blue-700 text-white'
              : 'bg-gray-700 text-gray-500 cursor-not-allowed'
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
            'mt-2 text-xs font-medium',
            connectionError ? 'text-red-400' : 'text-yellow-500'
          )}
        >
          {connectionError ? (
            <div className="flex items-center gap-2">
              <span>⚠️ {connectionError}</span>
              <span className="text-xs text-gray-500">(Check that the server is running)</span>
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <span className="inline-block w-1.5 h-1.5 bg-yellow-500 rounded-full animate-pulse" />
              Connecting to server...
            </div>
          )}
        </div>
      )}
    </div>
  )
}
