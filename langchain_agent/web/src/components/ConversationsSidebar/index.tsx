/**
 * ConversationsSidebar - List of past conversations with management.
 */

import { useEffect, useCallback, useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, MessageSquare, RefreshCw, BookOpen, HelpCircle, LogOut } from 'lucide-react'
import { useAuthStore } from '../../stores/authStore'
import { useChatStore, type ConversationSummary } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { ConversationItem } from './ConversationItem'
import { ErrorNotification } from '../ErrorNotification'
import { SkeletonConversationItem } from '../SkeletonLoader'
import { apiGet, apiDelete } from '../../utils/api'

interface ConversationsSidebarProps {
  onConversationSelect?: () => void
}

export function ConversationsSidebar({ onConversationSelect }: ConversationsSidebarProps) {
  const {
    conversations,
    conversationsLoading,
    threadId,
    setConversations,
    setConversationsLoading,
    startNewConversation,
    clearMessages,
  } = useChatStore()

  const { clearState } = useObservabilityStore()
  const logout = useAuthStore((s) => s.logout)
  const [error, setError] = useState<string | null>(null)
  const [confirmingClearAll, setConfirmingClearAll] = useState(false)
  const [confirmingLogout, setConfirmingLogout] = useState(false)

  const handleLogout = useCallback(async () => {
    if (!confirmingLogout) {
      setConfirmingLogout(true)
      // Auto-revert the confirm state after 3 s so the button doesn't sit
      // primed forever after a misclick.
      setTimeout(() => setConfirmingLogout(false), 3000)
      return
    }
    await logout()
  }, [confirmingLogout, logout])

  const fetchConversations = useCallback(async () => {
    setConversationsLoading(true)
    setError(null)
    try {
      const response = await apiGet('/api/conversations?limit=20')
      if (response.ok) {
        const data: ConversationSummary[] = await response.json()
        setConversations(data)
      } else {
        setError('Failed to load conversations. Please try again.')
      }
    } catch (error) {
      console.error('Failed to fetch conversations:', error)
      setError('Unable to connect to server. Please check your connection and try again.')
    } finally {
      setConversationsLoading(false)
    }
  }, [setConversations, setConversationsLoading])

  // Fetch conversations on mount - eslint-disable-next-line intentional async in effect
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchConversations()
  }, [fetchConversations])

  const handleNewConversation = useCallback(() => {
    startNewConversation()
    clearMessages()
    clearState()
  }, [startNewConversation, clearMessages, clearState])

  // Auto-cancel confirmation after 3 seconds
  useEffect(() => {
    if (!confirmingClearAll) return
    const timer = setTimeout(() => setConfirmingClearAll(false), 3000)
    return () => clearTimeout(timer)
  }, [confirmingClearAll])

  const handleClearAll = useCallback(async () => {
    // First click: show confirmation state
    if (!confirmingClearAll) {
      setConfirmingClearAll(true)
      return
    }

    // Second click: execute delete
    setConfirmingClearAll(false)
    setError(null)
    try {
      const response = await apiDelete('/api/conversations')

      if (response.ok || response.status === 204) {
        setConversations([])
        handleNewConversation()
      } else {
        setError('Failed to delete conversations. Please try again.')
      }
    } catch (error) {
      console.error('Failed to clear conversations:', error)
      setError('Unable to delete conversations. Please check your connection and try again.')
    }
  }, [confirmingClearAll, setConversations, handleNewConversation])

  return (
    <div className="flex flex-col h-full bg-gray-950 border-r border-gray-800">
      {/* Error notification */}
      {error && (
        <div className="px-4 pt-4">
          <ErrorNotification message={error} onDismiss={() => setError(null)} />
        </div>
      )}

      {/* Header */}
      <div className="px-4 py-4 border-b border-gray-800">
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-300">Conversations</h2>
          <button
            onClick={fetchConversations}
            aria-label="Refresh conversations"
            className="p-1.5 text-gray-400 hover:text-gray-200 transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
            title="Refresh conversations"
          >
            <RefreshCw className={`w-4 h-4 ${conversationsLoading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        <button
          onClick={handleNewConversation}
          className="w-full flex items-center justify-center gap-2 px-3 py-2 bg-blue-600 hover:bg-blue-700 rounded-lg text-sm text-white transition-colors focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 focus:ring-offset-gray-950"
        >
          <Plus className="w-4 h-4" />
          New Chat
        </button>
      </div>

      {/* Conversation list */}
      <div className="flex-1 overflow-y-auto py-2">
        {conversationsLoading ? (
          <SkeletonConversationItem count={5} />
        ) : conversations.length === 0 ? (
          <div className="px-4 py-8 text-center text-gray-500 text-sm">
            <MessageSquare className="w-8 h-8 mx-auto mb-2 opacity-50" />
            <p>No conversations yet</p>
            <p className="text-xs mt-1">Start chatting to create one</p>
          </div>
        ) : (
          <div className="space-y-1 px-2">
            {conversations.map((conversation) => (
              <ConversationItem
                key={conversation.thread_id}
                conversation={conversation}
                isActive={conversation.thread_id === threadId}
                onSelect={onConversationSelect}
              />
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div className="px-4 py-3 border-t border-gray-800 space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <Link
            to="/guide"
            className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm bg-gray-800 text-gray-300 hover:bg-gray-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950"
            title="User guide and tutorials"
          >
            <HelpCircle className="w-4 h-4" />
            Guide
          </Link>
          <Link
            to="/swagger"
            className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-sm bg-gray-800 text-gray-300 hover:bg-gray-700 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950"
            title="Swagger UI — FastAPI auto-generated reference"
          >
            <BookOpen className="w-4 h-4" />
            API
          </Link>
        </div>
        {conversations.length > 0 && (
          <button
            onClick={handleClearAll}
            className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-red-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950 ${
              confirmingClearAll
                ? 'bg-red-900/70 text-red-300 hover:bg-red-800'
                : 'bg-gray-800 text-gray-300 hover:bg-red-900/50 hover:text-red-400'
            }`}
          >
            <Trash2 className="w-4 h-4" />
            {confirmingClearAll ? 'Click again to confirm' : 'Clear All'}
          </button>
        )}
        <button
          onClick={handleLogout}
          aria-label={confirmingLogout ? 'Click again to confirm sign out' : 'Sign out'}
          title="Sign out — clears the session cookie and returns to the login screen"
          className={`w-full flex items-center justify-center gap-2 px-3 py-2 rounded-lg text-sm transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 focus-visible:ring-offset-2 focus-visible:ring-offset-gray-950 ${
            confirmingLogout
              ? 'bg-blue-900/70 text-blue-200 hover:bg-blue-800'
              : 'bg-gray-800 text-gray-300 hover:bg-gray-700 hover:text-gray-100'
          }`}
        >
          <LogOut className="w-4 h-4" />
          {confirmingLogout ? 'Click again to confirm' : 'Sign out'}
        </button>
      </div>
    </div>
  )
}
