/**
 * ConversationItem - Single conversation in the sidebar list.
 */

import { useCallback, useState } from 'react'
import { MessageSquare, Trash2 } from 'lucide-react'
import { useChatStore, type ConversationSummary } from '../../stores/chatStore'
import { useObservabilityStore } from '../../stores/observabilityStore'
import { ErrorNotification } from '../ErrorNotification'
import { ConfirmDialog } from '../ConfirmDialog'
import { apiDelete } from '../../utils/api'
import clsx from 'clsx'

interface ConversationItemProps {
  conversation: ConversationSummary
  isActive: boolean
  onSelect?: () => void
}

export function ConversationItem({ conversation, isActive, onSelect }: ConversationItemProps) {
  const { loadConversation, setConversations, conversations } = useChatStore()
  const { clearState } = useObservabilityStore()
  const [deleteError, setDeleteError] = useState<string | null>(null)
  const [isDeleting, setIsDeleting] = useState(false)
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false)

  const handleSelect = useCallback(async () => {
    if (isActive) return

    clearState()
    await loadConversation(conversation.thread_id)
    onSelect?.()
  }, [isActive, conversation.thread_id, loadConversation, clearState, onSelect])

  const handleDelete = useCallback((e: React.MouseEvent) => {
    e.stopPropagation()
    setShowDeleteConfirm(true)
  }, [])

  const confirmDelete = useCallback(async () => {
    setDeleteError(null)
    setIsDeleting(true)
    try {
      const response = await apiDelete(`/api/conversations/${conversation.thread_id}`)

      // Accept both 200 OK and 204 No Content as success
      if (response.ok || response.status === 204) {
        // Successfully deleted - remove from list and close dialog
        const updatedConversations = conversations.filter((c) => c.thread_id !== conversation.thread_id)
        setConversations(updatedConversations)

        // If this was the active conversation, switch to another one or clear the chat
        if (isActive) {
          // The conversation sidebar will automatically switch to the next available
          // conversation, or the chat will show "New Conversation" state
          if (updatedConversations.length > 0) {
            // Let the parent component handle switching to the next conversation
            onSelect?.()
          }
        }

        setShowDeleteConfirm(false)
        return
      }

      // If not successful, log response body for debugging
      const responseText = await response.text()
      console.error(`Delete failed with status ${response.status}:`, responseText)
      setDeleteError('Failed to delete conversation. Please try again.')
    } catch (error) {
      console.error('Failed to delete conversation:', error)
      setDeleteError('Unable to delete conversation. Please check your connection.')
    } finally {
      setIsDeleting(false)
    }
  }, [conversation, setConversations, conversations, isActive, onSelect])

  // Format date as a consistent short timestamp that always includes the time,
  // so entries like "Thu" or "Yesterday" become "Thu 7:09 PM" / "Yesterday 7:09 PM".
  const formatDate = (dateString: string) => {
    const date = new Date(dateString)
    const now = new Date()
    const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })

    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate())
    const startOfDate = new Date(date.getFullYear(), date.getMonth(), date.getDate())
    const diffDays = Math.round((startOfToday.getTime() - startOfDate.getTime()) / (1000 * 60 * 60 * 24))

    if (diffDays === 0) {
      return `Today ${time}`
    } else if (diffDays === 1) {
      return `Yesterday ${time}`
    } else if (diffDays > 1 && diffDays < 7) {
      return `${date.toLocaleDateString([], { weekday: 'short' })} ${time}`
    } else {
      return `${date.toLocaleDateString([], { month: 'short', day: 'numeric' })} ${time}`
    }
  }

  return (
    <>
      <ConfirmDialog
        isOpen={showDeleteConfirm}
        title="Delete Conversation"
        message={`Are you sure you want to delete "${conversation.title}"? This cannot be undone.`}
        confirmText="Delete"
        cancelText="Cancel"
        isDangerous={true}
        isLoading={isDeleting}
        onConfirm={confirmDelete}
        onCancel={() => setShowDeleteConfirm(false)}
      />
      {deleteError && (
        <div className="px-2 pb-2">
          <ErrorNotification
            message={deleteError}
            onDismiss={() => setDeleteError(null)}
            autoClose={false}
          />
        </div>
      )}
      <div
        className={clsx(
          'w-full flex items-start gap-2 px-3 py-2 rounded-lg text-left transition-colors group',
          isActive
            ? 'bg-gray-800 text-white'
            : 'text-gray-400 hover:bg-gray-800/50 hover:text-gray-200'
        )}
      >
        <button
          onClick={handleSelect}
          disabled={isDeleting}
          aria-current={isActive ? 'page' : undefined}
          aria-label={`${conversation.title}${isActive ? ', current conversation' : ''}`}
          className="flex-1 min-w-0 flex items-start gap-2 overflow-hidden focus:outline-none focus:ring-2 focus:ring-blue-500 rounded disabled:opacity-50"
        >
          <MessageSquare className="w-4 h-4 mt-0.5 flex-shrink-0" aria-hidden="true" />

          <div className="flex-1 min-w-0 text-left overflow-hidden">
            <div className="text-sm truncate">{conversation.title}</div>
            <div
              className="text-xs text-gray-400 mt-0.5"
              title={new Date(conversation.updated_at || conversation.created_at).toLocaleString()}
            >
              {formatDate(conversation.updated_at || conversation.created_at)}
            </div>
          </div>
        </button>

        <button
          onClick={handleDelete}
          disabled={isDeleting}
          aria-label={`Delete conversation "${conversation.title}"`}
          className={clsx(
            'p-1 rounded transition-colors flex-shrink-0',
            'text-gray-400 hover:text-red-400 hover:bg-red-500/10 focus:outline-none focus:ring-2 focus:ring-red-500 disabled:opacity-50'
          )}
        >
          <Trash2 className="w-3.5 h-3.5" aria-hidden="true" />
        </button>
      </div>
    </>
  )
}
