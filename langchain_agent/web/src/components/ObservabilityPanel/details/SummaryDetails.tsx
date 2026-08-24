import { SummaryEvent, NodeStatus } from '../../../types/events'
import { useObservabilityStore } from '../../../stores/observabilityStore'

interface SummaryDetailsProps {
  event?: SummaryEvent
  status?: NodeStatus
}

export function SummaryDetails({ event, status }: SummaryDetailsProps) {
  const { intentClassification } = useObservabilityStore()

  if (!event) {
    // Node is running or hasn't emitted its event yet
    if (status === 'running') {
      return (
        <div className="space-y-2 text-sm text-gray-100">
          <div className="flex items-center gap-2">
            <div className="w-3 h-3 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-blue-300">Generating conversation summary...</span>
          </div>
          {intentClassification && (
            <p className="text-xs text-gray-400">
              Analyzing conversation history with the LLM to produce a concise summary of key facts, decisions, and open items.
            </p>
          )}
        </div>
      )
    }

    return (
      <div className="text-sm text-gray-400">
        Waiting for summary data...
      </div>
    )
  }

  return (
    <div className="space-y-2 text-sm text-gray-100">
      <div>
        <span className="font-semibold text-gray-200">Messages summarized:</span>{' '}
        <span className="text-amber-300">{event.message_count}</span>
      </div>
      <div>
        <span className="font-semibold text-gray-200">Summary:</span>
        <p className="mt-1 text-xs text-gray-300 leading-snug whitespace-pre-wrap">
          {event.summary_text ? event.summary_text : 'No summary was generated.'}
        </p>
      </div>
    </div>
  )
}
